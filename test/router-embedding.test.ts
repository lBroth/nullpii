import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { EmbeddingRouter } from '../src/router-embedding.js';

function stagePrototypes(payload: Record<string, unknown>): string {
  const dir = mkdtempSync(join(tmpdir(), 'nullpii-router-'));
  writeFileSync(join(dir, 'router-embeddings.json'), JSON.stringify(payload));
  return dir;
}

describe('EmbeddingRouter', () => {
  it('throws if init() is called without a prototypes file', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'nullpii-router-empty-'));
    const r = new EmbeddingRouter(dir);
    await expect(r.init()).rejects.toThrow(/missing prototypes file/);
  });

  it('rejects malformed prototypes JSON', async () => {
    const dir = stagePrototypes({ domains: ['a'], prototypes: 'not-an-array' });
    const r = new EmbeddingRouter(dir);
    await expect(r.init()).rejects.toThrow(/malformed/);
  });

  it('rejects domains/prototypes length mismatch', async () => {
    const dir = stagePrototypes({
      domains: ['a', 'b'],
      prototypes: [[1, 0, 0]], // only one row
    });
    const r = new EmbeddingRouter(dir);
    await expect(r.init()).rejects.toThrow(/domains.length=2 != prototypes.length=1/);
  });

  it('routes the input to its closest prototype (cosine sim)', async () => {
    // Three orthogonal unit-vector prototypes. Embedding aligns with the
    // second; router should pick `legal`.
    const dir = stagePrototypes({
      embedder: 'test',
      domains: ['devops', 'legal', 'narrative'],
      prototypes: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
    });
    const r = new EmbeddingRouter(dir);
    await r.init();
    const decision = r.route(Float32Array.from([0.1, 0.95, 0.0]));
    expect(decision.domain).toBe('legal');
    expect(decision.score).toBeCloseTo(0.95, 5);
    expect(decision.gated).toBe(false);
  });

  it('honors gate margin: top below margin → fallback to runner-up', async () => {
    // Top score 0.51, runner-up 0.50, margin 0.01 < 0.10 gate → fallback.
    const dir = stagePrototypes({
      embedder: 'test',
      domains: ['enterprise', 'narrative'],
      prototypes: [
        [0.51, 0.0],
        [0.5, 0.0],
      ],
      gates: { enterprise: 0.1 },
    });
    const r = new EmbeddingRouter(dir);
    await r.init();
    const decision = r.route(Float32Array.from([1.0, 0.0]));
    expect(decision.domain).toBe('narrative');
    expect(decision.gated).toBe(true);
    expect(decision.runnerUpScore).toBeGreaterThan(decision.score);
  });

  it('does NOT gate when margin clears the threshold', async () => {
    const dir = stagePrototypes({
      embedder: 'test',
      domains: ['enterprise', 'narrative'],
      prototypes: [
        [1.0, 0.0],
        [0.0, 1.0],
      ],
      gates: { enterprise: 0.1 },
    });
    const r = new EmbeddingRouter(dir);
    await r.init();
    const decision = r.route(Float32Array.from([1.0, 0.0]));
    expect(decision.domain).toBe('enterprise');
    expect(decision.gated).toBe(false);
  });

  it('does NOT gate domains that have no entry in `gates`', async () => {
    // narrowly winning domain with NO gate config → still wins.
    const dir = stagePrototypes({
      embedder: 'test',
      domains: ['legal', 'narrative'],
      prototypes: [
        [0.51, 0.0],
        [0.5, 0.0],
      ],
      gates: { enterprise: 0.1 }, // gate set on a different domain
    });
    const r = new EmbeddingRouter(dir);
    await r.init();
    const decision = r.route(Float32Array.from([1.0, 0.0]));
    expect(decision.domain).toBe('legal');
    expect(decision.gated).toBe(false);
  });

  it('listDomains returns domains in file order', async () => {
    const dir = stagePrototypes({
      embedder: 'test',
      domains: ['c', 'a', 'b'],
      prototypes: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
    });
    const r = new EmbeddingRouter(dir);
    await r.init();
    expect(r.listDomains()).toEqual(['c', 'a', 'b']);
  });
});
