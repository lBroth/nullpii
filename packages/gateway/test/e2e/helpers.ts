// SPDX-License-Identifier: Apache-2.0
//
// Shared pieces of the gateway's real-ONNX end-to-end suite. The unit
// suite next door mocks the engine; these files run the gateway on the
// real GLiNER model, so they check what the mocks cannot: that the values
// a prompt or a tool result holds are found by the model, masked before
// they leave, and restored only where the gateway's rules allow.
//
// Gates, as in the core suite (`test/e2e/sanitize-real-onnx.test.ts`):
//   - skipped unless `NULLPII_E2E=1` is set in the environment;
//   - `NULLPII_MODEL_DIR` must point to a directory containing
//     `model.onnx`, `tokenizer.json`, `gliner_config.json` and
//     `tokenizer_config.json`.
//
// Assertions are robust to model scores: a value is absent, or restored
// equal to the original, never an exact placeholder id or score.

import debug from 'debug';
import { DEFAULT_RESTORE_TOOLS, NullPii, PLACEHOLDER_REGEX } from 'nullpii';
import type { GatewayConfig } from '../../src/config.js';
import { BASE_TEST_CONFIG } from '../fixtures.js';

const log = debug('nullpii:gateway:e2e');

const E2E_ENV = 'NULLPII_E2E';
const MODEL_DIR_ENV = 'NULLPII_MODEL_DIR';
const E2E_ON = process.env[E2E_ENV] === '1';
const MODEL_DIR = process.env[MODEL_DIR_ENV];

/** True unless both gates are set; every e2e `describe` skips on it. */
export const SKIP = !E2E_ON || !MODEL_DIR;

if (SKIP) {
  log('skipping the gateway real-ONNX suite: set %s=1 and %s=<model dir>', E2E_ENV, MODEL_DIR_ENV);
}

/** Loading the model (about 1.2 GB) and its first inference. */
export const WARMUP_TIMEOUT_MS = 120_000;
/** One test: a handful of model calls, with room for a slow CI CPU. */
export const TEST_TIMEOUT_MS = 30_000;

/** Values the core suite proves the real model detects. */
export const PII = {
  person: 'Claude Dupont',
  email: 'john.smith@acme.io',
  iban: 'GB29 NWBK 6016 1331 9268 19',
  awsKey: 'AKIAIOSFODNN7EXAMPLE',
} as const;

/** Every fixture value: none may reach an upstream or a held tool. */
export const ALL_PII: readonly string[] = Object.values(PII);

/** A user prompt holding a person and an email. */
export const PROMPT = `Please email ${PII.person} at ${PII.email} about the overdue invoice.`;

/** A tool result, as prose, holding a person, an IBAN and an AWS key. */
export const TOOL_RESULT_TEXT = `Customer ${PII.person}, IBAN ${PII.iban}, deploy key ${PII.awsKey}.`;

/** The unit suite's base config with the production restore tools
 * (`DEFAULT_RESTORE_TOOLS`) instead of the made-up tools it adds. */
export const E2E_CONFIG: GatewayConfig = {
  ...BASE_TEST_CONFIG,
  restoreTools: new Set(DEFAULT_RESTORE_TOOLS),
};

const WARMUP_TEXT = 'warmup';

/** The real engine on the CPU backend, its model loaded and run once so
 * the first test does not carry the load. */
export async function startRealEngine(): Promise<NullPii> {
  if (!MODEL_DIR) throw new Error(`${MODEL_DIR_ENV} is not set`);
  const np = new NullPii({ modelDir: MODEL_DIR, backend: 'cpu' });
  await np.sanitize(WARMUP_TEXT);
  return np;
}

/** A fresh global copy: a shared global regex carries `lastIndex`. */
function placeholderPattern(): RegExp {
  return new RegExp(PLACEHOLDER_REGEX.source, 'g');
}

/** Every placeholder in `text`, once per occurrence, in order. */
export function placeholdersIn(text: string): string[] {
  return [...text.matchAll(placeholderPattern())].map((m) => m[0]);
}

/** The distinct placeholders in `text`, in order of first occurrence. */
export function distinctPlaceholders(text: string): string[] {
  return [...new Set(placeholdersIn(text))];
}

/** How many placeholders of each label `text` holds, under the lower-case
 * label names `capturedByLabel` uses. */
export function placeholderLabels(text: string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const m of text.matchAll(placeholderPattern())) {
    const label = (m[1] ?? '').toLowerCase();
    counts[label] = (counts[label] ?? 0) + 1;
  }
  return counts;
}

/** The session prefix a placeholder carries (its last segment). */
export function sessionPrefixOf(placeholder: string): string {
  const prefix = new RegExp(PLACEHOLDER_REGEX.source).exec(placeholder)?.[3];
  if (prefix === undefined) throw new Error('not a placeholder');
  return prefix;
}

/** The fixture values that appear in `text`: what leaked. */
export function leaked(text: string, values: readonly string[] = ALL_PII): string[] {
  return values.filter((value) => text.includes(value));
}

/** The sum of a per-label count. */
export function total(counts: Readonly<Record<string, number | undefined>>): number {
  return Object.values(counts).reduce<number>((sum, n) => sum + (n ?? 0), 0);
}

/** `text` cut in the middle of its first placeholder, so a stream sends
 * that placeholder in two pieces. */
export function splitInsideFirstPlaceholder(text: string): [string, string] {
  const first = placeholderPattern().exec(text);
  if (first === null) throw new Error('no placeholder to split');
  const at = first.index + Math.floor(first[0].length / 2);
  return [text.slice(0, at), text.slice(at)];
}
