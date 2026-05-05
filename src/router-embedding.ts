// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import debug from 'debug';
import { fileExists } from './paths.js';

const log = debug('nullpii:router-embedding');

/** On-disk layout of `router-embeddings.json` (Python writer in
 * `packages/eval/scripts/release/export_router_artifacts.py`). */
interface RouterEmbeddingsFile {
  embedder: string;
  prefix?: string;
  domains: string[];
  prototypes: number[][];
  gates?: Record<string, number>;
}

/** Result of routing a single input. */
export interface RouteDecision {
  /** Selected domain — used as the key into the per-domain ONNX bundle. */
  readonly domain: string;
  /** Cosine similarity vs the chosen domain's prototype. */
  readonly score: number;
  /** Cosine similarity vs the runner-up. Useful for diagnostics. */
  readonly runnerUpScore: number;
  /** True if the chosen domain was rejected by its `gate` margin
   * (`score - runnerUpScore < gate`) and the runner-up was selected
   * instead. */
  readonly gated: boolean;
}

/**
 * Cosine-similarity router over per-domain prototype vectors.
 *
 * Mirrors `EmbeddingDomainRouter` (Python — `packages/eval/src/nullpii_eval/router.py`).
 *
 * Gating: each domain may carry a `gate` margin in `router-embeddings.json`.
 * If the top domain wins by less than its gate, the runner-up is
 * selected instead. Used for the `enterprise` route which proved
 * over-attractive on dev-paste in pre-bench validation.
 */
export class EmbeddingRouter {
  private prototypes: Float32Array[] = [];
  private domains: string[] = [];
  private gates: Record<string, number> = {};
  private loaded = false;

  constructor(private readonly modelDir: string) {}

  async init(): Promise<void> {
    if (this.loaded) return;
    const path = join(this.modelDir, 'router-embeddings.json');
    if (!(await fileExists(path))) {
      throw new Error(`router-embedding: missing prototypes file at ${path}`);
    }
    log('loading prototypes from %s', path);
    const raw = JSON.parse(readFileSync(path, 'utf-8')) as RouterEmbeddingsFile;
    if (!Array.isArray(raw.domains) || !Array.isArray(raw.prototypes)) {
      throw new Error('router-embedding: malformed prototypes JSON');
    }
    if (raw.domains.length !== raw.prototypes.length) {
      throw new Error(
        `router-embedding: domains.length=${raw.domains.length} != prototypes.length=${raw.prototypes.length}`,
      );
    }
    this.domains = raw.domains.slice();
    this.prototypes = raw.prototypes.map((row) => Float32Array.from(row));
    this.gates = raw.gates ?? {};
    this.loaded = true;
    log('loaded %d domains: %s', this.domains.length, this.domains.join(','));
  }

  /** Route a single input embedding. Embedding MUST be L2-normalised
   * (DistiluseEncoder always returns normalised vectors). Returns the
   * selected domain + diagnostic scores. */
  route(embedding: Float32Array): RouteDecision {
    if (!this.loaded) {
      throw new Error('router-embedding: not initialised, call init() first');
    }
    if (this.prototypes.length === 0) {
      throw new Error('router-embedding: no prototypes loaded');
    }

    // Cosine similarity = dot product (both unit-norm).
    const scores: { domain: string; score: number }[] = [];
    for (let i = 0; i < this.prototypes.length; i++) {
      const proto = this.prototypes[i];
      const dom = this.domains[i];
      if (proto === undefined || dom === undefined) continue;
      let dot = 0;
      const dim = Math.min(embedding.length, proto.length);
      for (let d = 0; d < dim; d++) {
        dot += (embedding[d] ?? 0) * (proto[d] ?? 0);
      }
      scores.push({ domain: dom, score: dot });
    }

    scores.sort((a, b) => b.score - a.score);
    const top = scores[0];
    const runnerUp = scores[1];
    if (top === undefined || runnerUp === undefined) {
      throw new Error('router-embedding: fewer than 2 prototype scores');
    }

    // Gate check: if `top.domain` has a gate and the margin is too
    // small, fall back to the runner-up.
    const gateMargin = this.gates[top.domain];
    if (gateMargin !== undefined && top.score - runnerUp.score < gateMargin) {
      log(
        'gated %s (score=%f, runner-up=%s @%f, margin=%f < %f) → fallback %s',
        top.domain,
        top.score,
        runnerUp.domain,
        runnerUp.score,
        top.score - runnerUp.score,
        gateMargin,
        runnerUp.domain,
      );
      return {
        domain: runnerUp.domain,
        score: runnerUp.score,
        runnerUpScore: top.score,
        gated: true,
      };
    }

    return {
      domain: top.domain,
      score: top.score,
      runnerUpScore: runnerUp.score,
      gated: false,
    };
  }

  /** Domain list in the order they appear in the prototypes file. */
  listDomains(): readonly string[] {
    return this.domains;
  }
}
