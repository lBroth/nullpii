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
const TOKEN = 'Qm7Xv2Lp9Rk4Tz8Wn3Bc6Yd1Hf5Jg0Sa';
/** Credentials only the model finds (no recognizer owns these shapes),
 * each with the value that must not reach the output. 0.5.4 masked every
 * one under the policies below. With the default's prompt the model files
 * several under a category those policies leave readable (`private_url`,
 * `account_number`, `private_driver_license`); the secret pass
 * (`secret-pass.ts`) keeps them masked. */
const MODEL_ONLY_SECRETS: ReadonlyArray<readonly [string, string]> = [
  [`const API_KEY = "${TOKEN}";`, TOKEN],
  [`git clone https://oauth2:${TOKEN.slice(0, 20)}@gitlab.com/acme/app.git`, TOKEN.slice(0, 20)],
  [`https://api.example.com/v1/data?access_token=${TOKEN}`, TOKEN],
  [`curl "https://api.acme.io/items?api_key=${TOKEN}"`, TOKEN],
  ['Authorization: Basic YWRtaW46UW03WHYyTHA5Ums0', 'YWRtaW46UW03WHYyTHA5Ums0'],
  [
    'Authorization: token 272d1371c17149d439536b3216fdaeeb975729fa',
    '272d1371c17149d439536b3216fdaeeb975729fa',
  ],
  ['License key: JB7K-2M9Q-PX4L-V8RT', 'JB7K-2M9Q-PX4L-V8RT'],
  ['Windows product key: VK7JG-NPHTM-C97JM-9MPGT-3V66T', 'VK7JG-NPHTM-C97JM-9MPGT-3V66T'],
  ['password=Xk9#mQ2vL7pR4tZ', 'Xk9#mQ2vL7pR4tZ'],
  ['DATABASE_URL=postgres://app:Xk9mQ2vL7pR4tZ@db.internal:5432/app', 'Xk9mQ2vL7pR4tZ'],
];
/** The policies that leave readable a category the default masks, and
 * under which 0.5.4 masked every credential above. */
const PARTIAL_POLICIES: ReadonlyArray<readonly [string, readonly PiiCategory[]]> = [
  ['the secrets-only preset', ALL_BUT_SECRET],
  ['URLs readable', [...DEFAULT_DISABLED_CATEGORIES, 'private_url']],
  ['account numbers readable', [...DEFAULT_DISABLED_CATEGORIES, 'account_number']],
  ['licences readable', [...DEFAULT_DISABLED_CATEGORIES, 'private_driver_license']],
];

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

  const DEFAULT_POLICY: readonly [string, readonly PiiCategory[]] = [
    'the default policy',
    DEFAULT_DISABLED_CATEGORIES,
  ];
  it.each([DEFAULT_POLICY, ...PARTIAL_POLICIES])(
    'under %s, masks the credentials only the model finds',
    async (name, disabledCategories) => {
      np.updatePolicy({ disabledCategories });
      try {
        for (const [text, value] of MODEL_ONLY_SECRETS) {
          const out = await np.sanitize(text);
          expect({ text, leaked: out.sanitized.includes(value) }).toEqual({ text, leaked: false });
          // Under secrets-only nothing but secrets is masked.
          if (name === 'the secrets-only preset') {
            const labels = new Set(out.spans.map((s) => s.label));
            expect({ text, labels: [...labels] }).toEqual({ text, labels: ['secret'] });
          }
        }
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
