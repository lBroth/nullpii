#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Mechanical verdicts for the A/B loop (PROTOCOL.md). No judgement here:
// the rules are the thresholds below, applied to two harness outputs.
//
//   node compare.mjs fingerprint <baseline.json> <candidate.json>
//   node compare.mjs latency     <baseline.json> <candidate.json>
//
// Exit code 0 = ACCEPT-eligible on this axis, 1 = REJECT.

import { readFileSync } from 'node:fs';

const T1_MIN_GAIN_PCT = 5;
const T1_MAX_REGRESSION_PCT = 3;
const T1_NOISE_MULTIPLIER = 2;
const T1_GATED_SIZES = ['30000', '100000'];
const MAX_LISTED_DIFFS = 15;

function load(path) {
  return JSON.parse(readFileSync(path, 'utf-8'));
}

function hasOverlapOrOutOfRange(spans, textLength) {
  const sorted = [...spans].sort((a, b) => a[1] - b[1]);
  for (let i = 0; i < sorted.length; i++) {
    const [, start, end] = sorted[i];
    if (start < 0 || (textLength !== undefined && end > textLength)) return true;
    if (i > 0 && start < sorted[i - 1][2]) return true;
  }
  return false;
}

/** Same ordering as the harness: span order is not part of the output contract. */
function canonical(spans) {
  return JSON.stringify([...spans].sort((a, b) => a[1] - b[1] || a[2] - b[2] || (a[0] < b[0] ? -1 : 1)));
}

function compareFingerprints(base, cand) {
  const byId = new Map(base.docs.map((d) => [d.id, d.spans]));
  if (cand.docs.length !== base.docs.length || cand.docs.some((d) => !byId.has(d.id))) {
    throw new Error('fingerprint corpora differ: compare runs of the same harness version');
  }
  const changed = cand.docs.filter((d) => canonical(byId.get(d.id)) !== canonical(d.spans));
  if (changed.length === 0) {
    return { identical: true, verdict: 'IDENTICAL', changed: 0 };
  }
  const explained = changed.filter((d) => hasOverlapOrOutOfRange(byId.get(d.id)));
  return {
    identical: false,
    changed: changed.length,
    changedWhereBaselineOverlapped: explained.length,
    unexplained: changed
      .filter((d) => !explained.includes(d))
      .slice(0, MAX_LISTED_DIFFS)
      .map((d) => ({ id: d.id, base: byId.get(d.id), cand: d.spans })),
    verdict: changed.length === explained.length ? 'CHANGED_ONLY_WHERE_BASELINE_WRONG' : 'CHANGED',
  };
}

function compareLatency(base, cand) {
  const rows = {};
  let gained = false;
  let regressed = false;
  for (const size of Object.keys(base.bySize)) {
    const b = base.bySize[size];
    const c = cand.bySize[size];
    const deltaPct = ((b.p50 - c.p50) / b.p50) * 100;
    const noisePct = Math.max(b.spreadPct, c.spreadPct) * T1_NOISE_MULTIPLIER;
    const significantGain = deltaPct >= T1_MIN_GAIN_PCT && deltaPct > noisePct;
    if (T1_GATED_SIZES.includes(size) && significantGain) gained = true;
    if (-deltaPct > T1_MAX_REGRESSION_PCT) regressed = true;
    rows[size] = {
      baseP50: round(b.p50),
      candP50: round(c.p50),
      gainPct: round(deltaPct),
      noisePct: round(noisePct),
      significantGain,
    };
  }
  return { rows, verdict: gained && !regressed ? 'FASTER' : regressed ? 'REGRESSED' : 'NO_SIGNIFICANT_GAIN' };
}

function round(x) {
  return Math.round(x * 10) / 10;
}

const [mode, basePath, candPath] = process.argv.slice(2);
const base = load(basePath);
const cand = load(candPath);
const result = mode === 'fingerprint' ? compareFingerprints(base, cand) : compareLatency(base, cand);
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
const pass = ['IDENTICAL', 'CHANGED_ONLY_WHERE_BASELINE_WRONG', 'FASTER'].includes(result.verdict);
process.exitCode = pass ? 0 : 1;
