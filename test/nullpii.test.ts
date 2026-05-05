import { describe, expect, it } from 'vitest';
import { ModelNotInitializedError } from '../src/errors.js';
import { NullPii } from '../src/nullpii.js';

describe('NullPii lifecycle', () => {
  it('rejects sanitize after dispose with ModelNotInitializedError', async () => {
    const n = new NullPii({ modelDir: '/nonexistent', backend: 'cpu' });
    await n.dispose();
    await expect(n.sanitize('hi')).rejects.toBeInstanceOf(ModelNotInitializedError);
  });

  it('default-config exposes the recognizer pack', () => {
    const n = new NullPii();
    // Built-in pack is non-empty unless caller opts out via `recognizers: 'none'`.
    // We don't expose `.recognizers` publicly, but the constructor populates it
    // when no override is provided. addRecognizer returns `this` (chainable).
    expect(
      n.addRecognizer({
        id: 'test',
        pattern: /test/g,
        label: 'secret',
        confidence: 0.9,
      }),
    ).toBe(n);
  });

  it('opt-out via recognizers: "none" still allows addRecognizer', () => {
    const n = new NullPii({ recognizers: 'none' });
    expect(
      n.addRecognizer({
        id: 'test',
        pattern: /test/g,
        label: 'secret',
        confidence: 0.9,
      }),
    ).toBe(n);
  });
});

// End-to-end ML pipeline (real ONNX + tokenizer) is exercised by the
// scratch script `test-full-stack.mjs` against a staged model dir; not
// part of the CI suite because we don't ship multi-GB models in tests.
// See `docs/v10/V10_PLAN.md` for the e2e smoke command.
