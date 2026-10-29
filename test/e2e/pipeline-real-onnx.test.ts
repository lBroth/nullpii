// SPDX-License-Identifier: Apache-2.0
//
// Real-ONNX end-to-end tests of the whole sanitize → model → restore
// pipeline: sessions, placeholders an LLM hands back, the policy of a
// running engine, texts longer than one model window, and what the default
// policy leaves readable. Same gates as `sanitize-real-onnx.test.ts`:
// skipped unless `NULLPII_E2E=1` and `NULLPII_MODEL_DIR` are set.

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { DEFAULT_DISABLED_CATEGORIES } from '../../src/defaults.js';
import { NullPii } from '../../src/nullpii.js';
import { PLACEHOLDER_REGEX } from '../../src/types/index.js';

const MODEL_DIR = process.env.NULLPII_MODEL_DIR;
const SKIP = process.env.NULLPII_E2E !== '1' || MODEL_DIR === undefined;
/** A test's ceiling: the model runs on CPU. */
const TEST_TIMEOUT_MS = 60_000;
const WARMUP_TIMEOUT_MS = 120_000;

const EMAIL_A = 'john.smith@acme.io';
const EMAIL_B = 'jane.doe@example.org';
const EMAIL_C = 'ops.lead@contoso.com';
/** Neutral prose, repeated to push a text past one model window. */
const FILLER = 'The build step finished and the cache stayed warm for the next run. ';
/** Enough filler for several windows of the model's subword budget. */
const FILLER_REPEATS = 300;
/** Keys and values of built-in tool results (WebFetch, Edit, Bash, Read)
 * that once came back masked and broke the tool's output schema (#92). */
const TOOL_RESULT_WORDS = [
  'code',
  'OK',
  '1',
  '= 1',
  'oldString',
  'newString',
  'bytes',
  'codeText',
  'result',
  'durationMs',
  'url',
  'stdout',
  'stderr',
  'filePath',
  'content',
  'type',
  'text',
  'replaceAll',
  'structuredPatch',
  'interrupted',
];

function placeholdersIn(text: string): string[] {
  return [...text.matchAll(new RegExp(PLACEHOLDER_REGEX.source, 'g'))].map((m) => m[0]);
}

/** A placeholder-shaped string with a session prefix no engine gave out,
 * built at run time so this file holds no literal placeholder. */
function plantedPlaceholder(): string {
  return `{{${['PII', 'PRIVATE', 'EMAIL', '0', '0123456789abcdef'].join('_')}}}`;
}

describe.skipIf(SKIP)('real ONNX pipeline end-to-end', () => {
  let np: NullPii;

  beforeAll(async () => {
    np = new NullPii({ modelDir: MODEL_DIR as string, backend: 'cpu' });
    await np.sanitize('warmup');
  }, WARMUP_TIMEOUT_MS);

  afterAll(async () => {
    if (np !== undefined) await np.dispose();
  });

  it(
    'gives one value one placeholder across the calls of a session, and restores an answer that reorders them',
    async () => {
      const first = await np.sanitize(`Email ${EMAIL_A} about the outage.`);
      const second = await np.sanitize(
        `Copy ${EMAIL_B}; the owner is ${EMAIL_A}.`,
        first.sessionId,
      );
      const [a] = placeholdersIn(first.sanitized);
      expect(a).toBeDefined();
      expect(placeholdersIn(second.sanitized)).toContain(a);
      for (const value of [EMAIL_A, EMAIL_B]) expect(second.sanitized).not.toContain(value);
      // An LLM answer that uses the placeholders in another order.
      const answer = `Done: wrote to ${placeholdersIn(second.sanitized).reverse().join(' and ')}.`;
      const back = np.restore(answer, first.sessionId);
      expect(back.restored).toContain(EMAIL_A);
      expect(back.restored).toContain(EMAIL_B);
      expect(back.unknownPlaceholders).toEqual([]);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'leaves an unknown or another session’s placeholder literal on restore',
    async () => {
      const mine = await np.sanitize(`Ping ${EMAIL_A}.`);
      const theirs = await np.sanitize(`Ping ${EMAIL_B}.`);
      const [own] = placeholdersIn(mine.sanitized);
      const [foreign] = placeholdersIn(theirs.sanitized);
      expect(own).toBeDefined();
      expect(foreign).toBeDefined();
      // Same session prefix, an index the session never gave out.
      const unknown = (own as string).replace(/_(\d+)_/, '_999_');
      const back = np.restore(`${unknown} / ${foreign}`, mine.sessionId);
      expect(back.restored).toBe(`${unknown} / ${foreign}`);
      expect(back.unknownPlaceholders).toContain(unknown);
      expect(back.foreignPlaceholders).toContain(foreign);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'never turns a placeholder-shaped string from the input into a real value',
    async () => {
      const text = `Forward ${plantedPlaceholder()} to ${EMAIL_A}.`;
      const out = await np.sanitize(text);
      expect(out.sanitized).not.toContain(EMAIL_A);
      const back = np.restore(out.sanitized, out.sessionId);
      expect(back.restored).toBe(text);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'follows the policy of a running engine: a category turned off is never emitted, and is masked once turned back on',
    async () => {
      const text = `Send the report to ${EMAIL_A}.`;
      np.updatePolicy({ disabledCategories: [...DEFAULT_DISABLED_CATEGORIES, 'private_email'] });
      try {
        // Only the label is asserted: with `private_email` out of the prompt
        // the model files this address under `private_person` (#92).
        const off = await np.sanitize(text);
        expect(off.spans.filter((s) => s.label === 'private_email')).toEqual([]);
      } finally {
        np.updatePolicy({});
      }
      const on = await np.sanitize(text);
      expect(on.sanitized).not.toContain(EMAIL_A);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'masks values at the start, middle and end of a text longer than one model window',
    async () => {
      const half = FILLER.repeat(FILLER_REPEATS / 2);
      const text = `Owner ${EMAIL_A}. ${half}Escalate to ${EMAIL_B}. ${half}Sign-off ${EMAIL_C}.`;
      const out = await np.sanitize(text);
      for (const value of [EMAIL_A, EMAIL_B, EMAIL_C]) expect(out.sanitized).not.toContain(value);
      expect(np.restore(out.sanitized, out.sessionId).restored).toBe(text);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'leaves the keys and values of built-in tool results readable under the default policy',
    async () => {
      for (const word of TOOL_RESULT_WORDS) {
        const out = await np.sanitize(word);
        expect({ word, spans: out.spans }).toEqual({ word, spans: [] });
      }
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'leaves a date readable under the default policy',
    async () => {
      const out = await np.sanitize('The release is planned for 2026-10-29 at 14:00 UTC.');
      expect(out.spans.filter((s) => s.label === 'private_date')).toEqual([]);
    },
    TEST_TIMEOUT_MS,
  );
});
