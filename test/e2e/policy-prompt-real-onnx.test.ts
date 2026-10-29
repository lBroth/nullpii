// SPDX-License-Identifier: Apache-2.0
//
// Real-ONNX regression tests for #92: a policy decides what is masked, not
// which labels the model is prompted with. Turning categories off used to
// shrink the prompt, which moved the model's scores: `secret` prompted alone
// flagged the keys of built-in tool results, and an email with its category
// off came back masked as a person. Same gates as `sanitize-real-onnx.test.ts`.

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { DEFAULT_DISABLED_CATEGORIES } from '../../src/defaults.js';
import { NullPii } from '../../src/nullpii.js';
import { PII_LABELS, type PiiCategory } from '../../src/types/labels.js';

const MODEL_DIR = process.env.NULLPII_MODEL_DIR;
const SKIP = process.env.NULLPII_E2E !== '1' || MODEL_DIR === undefined;
const TEST_TIMEOUT_MS = 60_000;
const WARMUP_TIMEOUT_MS = 120_000;

/** Every category but `secret`: the secrets-only preset. */
const ALL_BUT_SECRET = PII_LABELS.filter((l): l is PiiCategory => l !== 'O' && l !== 'secret');
/** Keys and values of built-in tool results that the secrets-only preset
 * flagged before the fix (scores 0.05–0.11). */
const FLAGGED_BEFORE = ['code', 'OK', '= 1', 'oldString', 'newString'];
const EMAIL = 'john.smith@acme.io';

describe.skipIf(SKIP)('#92 · the policy does not shrink the prompt (real ONNX)', () => {
  let np: NullPii;

  beforeAll(async () => {
    np = new NullPii({ modelDir: MODEL_DIR as string, backend: 'cpu' });
    await np.sanitize('warmup');
  }, WARMUP_TIMEOUT_MS);

  afterAll(async () => {
    if (np !== undefined) await np.dispose();
  });

  it(
    'under the secrets-only preset, leaves tool-result words readable and still masks a key',
    async () => {
      np.updatePolicy({ disabledCategories: ALL_BUT_SECRET });
      try {
        for (const word of FLAGGED_BEFORE) {
          const out = await np.sanitize(word);
          expect({ word, spans: out.spans }).toEqual({ word, spans: [] });
        }
        const key = await np.sanitize('Leak: AKIAIOSFODNN7EXAMPLE — rotate now.');
        expect(key.sanitized).not.toContain('AKIAIOSFODNN7EXAMPLE');
      } finally {
        np.updatePolicy({});
      }
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'leaves an email readable when its category is off, rather than masking it as a person',
    async () => {
      const text = `Send the report to ${EMAIL}.`;
      np.updatePolicy({ disabledCategories: [...DEFAULT_DISABLED_CATEGORIES, 'private_email'] });
      try {
        const out = await np.sanitize(text);
        expect(out.sanitized).toBe(text);
      } finally {
        np.updatePolicy({});
      }
    },
    TEST_TIMEOUT_MS,
  );
});
