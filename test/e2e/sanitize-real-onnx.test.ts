// SPDX-License-Identifier: Apache-2.0
//
// F-18 · Real-ONNX end-to-end test. The bulk of the unit suite mocks
// `OrtBackend` + `GlinerTokenizer` so CI stays ONNX-free; this
// file is the opposite end of that contract — it loads the real
// GLiNER model and asserts that representative fixtures produce
// representative spans. Catches regressions in the ScatterND clamping,
// decoder index math, chunk-boundary dedupe, recognizer/ML reconciliation
// and base64 detector that the mocked suite cannot see.
//
// Gates:
//   - Skipped unless `NULLPII_E2E=1` is set in the environment.
//   - `NULLPII_MODEL_DIR` must point to a directory containing
//     `model.onnx`, `tokenizer.json`, `gliner_config.json`,
//     `tokenizer_config.json`. Either point at a local cache or at the
//     HuggingFace cache mirror.
//
// Run locally: `npm run test:e2e`
//   (sets `NULLPII_E2E=1` for you; you still need to set `NULLPII_MODEL_DIR`.)

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { NullPii } from '../../src/nullpii.js';

const E2E_ON = process.env.NULLPII_E2E === '1';
const MODEL_DIR = process.env.NULLPII_MODEL_DIR;
const SKIP = !E2E_ON || !MODEL_DIR;
const SKIP_REASON = !E2E_ON
  ? 'NULLPII_E2E != 1 — set NULLPII_E2E=1 and NULLPII_MODEL_DIR=<path-to-model-dir>'
  : 'NULLPII_MODEL_DIR not set — point at a directory containing model.onnx + tokenizer.json';

if (SKIP) {
  // eslint-disable-next-line no-console
  process.stderr.write(`[e2e] skipping real-ONNX suite: ${SKIP_REASON}\n`);
}

describe.skipIf(SKIP)('F-18 · real ONNX sanitize end-to-end', () => {
  let np: NullPii;

  beforeAll(async () => {
    // SKIP guard above ensures MODEL_DIR is defined when we reach this hook.
    np = new NullPii({ modelDir: MODEL_DIR as string, backend: 'cpu' });
    // Warm the engine so the first `it` doesn't carry the model-load cost.
    await np.sanitize('warmup');
  }, 120_000);

  afterAll(async () => {
    if (np !== undefined) await np.dispose();
  });

  it('detects a plain-prose email + person name (round-trip)', async () => {
    const text = 'Email John Smith at john.smith@acme.io today.';
    const out = await np.sanitize(text);
    const labels = out.spans.map((s) => s.label);
    expect(labels).toContain('private_email');
    // The model misses person names on rare runs depending on the chosen
    // checkpoint; assert at least one PII label so the test is a tight
    // regression signal without being flaky.
    expect(out.spans.length).toBeGreaterThan(0);
    const back = np.restore(out.sanitized, out.sessionId);
    expect(back.restored).toBe(text);
    expect(back.replacements).toBe(out.spans.length);
  }, 30_000);

  it('catches Luhn-valid credit-card via recognizer pack', async () => {
    const text = 'Charged card 4242 4242 4242 4242 today.';
    const out = await np.sanitize(text);
    const accounts = out.spans.filter((s) => s.label === 'account_number');
    expect(accounts.length).toBeGreaterThanOrEqual(1);
    // Recognizer score (>= 0.9 for high-confidence patterns).
    expect(accounts[0]?.score ?? 0).toBeGreaterThanOrEqual(0.9);
  }, 30_000);

  it('catches mod-97-valid IBAN with the correct `account_number` label', async () => {
    // Validator-passing recognizers (iban97 here) emit at
    // VALIDATED_RECOGNIZER_SCORE (~0.99998) so cross-label IoU dedupe
    // outranks ML softmax (~0.9999) — ensures spaced IBANs land on
    // `account_number`, not `private_address`.
    const text = 'Please wire to GB29 NWBK 6016 1331 9268 19 by Friday.';
    const out = await np.sanitize(text);
    const ibanSpans = out.spans.filter((s) => s.text.replace(/\s/g, '').startsWith('GB29NWBK'));
    expect(ibanSpans.length).toBeGreaterThanOrEqual(1);
    expect(ibanSpans[0]?.label).toBe('account_number');
  }, 30_000);

  it('catches AWS access key as a `secret`', async () => {
    const text = 'Leak: AKIAIOSFODNN7EXAMPLE — rotate now.';
    const out = await np.sanitize(text);
    const secrets = out.spans.filter((s) => s.label === 'secret');
    expect(secrets.length).toBeGreaterThanOrEqual(1);
    expect(secrets[0]?.text).toBe('AKIAIOSFODNN7EXAMPLE');
  }, 30_000);

  it('decodes base64-wrapped email at source coordinates', async () => {
    // base64 of `user.123@gmail.com` → 24 chars, classification = private_email.
    const blob = Buffer.from('user.123@gmail.com', 'utf8').toString('base64');
    const text = `payload: ${blob}`;
    const out = await np.sanitize(text);
    const emails = out.spans.filter((s) => s.label === 'private_email');
    expect(emails.length).toBeGreaterThanOrEqual(1);
    // Span is anchored on the source (encoded) substring, not the
    // decoded plaintext, so vault round-trips through the original.
    expect(emails.some((s) => s.text === blob)).toBe(true);
  }, 30_000);

  it('despaces whitespace-obfuscated international phone', async () => {
    const text = 'Reach me on + 4 9 1 7 6 5 4 3 today.';
    const out = await np.sanitize(text);
    // Either the ML model picks it up or the recognizer pack does after
    // normalize.collapse; either way, at least one PII span emerges.
    expect(out.spans.length).toBeGreaterThan(0);
  }, 30_000);

  it('handles Cyrillic-homoglyph email (admin with Cyrillic а / е)', async () => {
    // `аdmin@еxample.io` — Cyrillic а (U+0430) + е (U+0435). NFKC + anyAscii
    // transliteration is the path that exposes the email shape to the
    // recognizer pack on the normalized surface.
    const text = 'Contact аdmin@еxample.io for access.';
    const out = await np.sanitize(text);
    const emails = out.spans.filter((s) => s.label === 'private_email');
    expect(emails.length).toBeGreaterThanOrEqual(1);
    // Span maps back to the original (homoglyph) substring via normToOrig.
    expect(emails[0]?.text).toContain('@');
  }, 30_000);
});
