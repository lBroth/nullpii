// SPDX-License-Identifier: Apache-2.0
//
// F-02 regression tests. The convenience `sanitize()` helper must not create
// a fresh NullPii (and therefore a fresh ORT session + vault) on every call
// when the caller passes a non-empty but cacheable config. Custom recognizers
// are intentionally not cached (regex/fn aren't structurally hashable) and
// must surface a warning so callers know to manage the lifecycle themselves.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let backendConstructCount = 0;

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    constructor() {
      backendConstructCount += 1;
    }
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return { logits: new Float32Array(0), textLength: 0, maxWidth: 1, numClasses: 8 };
    }
    async dispose(): Promise<void> {}
  }
  return { OrtBackend };
});

vi.mock('../src/gliner-tokenizer.js', async () => {
  const actual = await vi.importActual<typeof import('../src/gliner-tokenizer.js')>(
    '../src/gliner-tokenizer.js',
  );
  class GlinerTokenizer {
    async encode(): Promise<{
      inputIds: BigInt64Array;
      attentionMask: BigInt64Array;
      wordsMask: BigInt64Array;
      numWords: number;
      words: readonly string[];
      seqLen: number;
      truncated: boolean;
    }> {
      return {
        inputIds: BigInt64Array.from([0n]),
        attentionMask: BigInt64Array.from([1n]),
        wordsMask: BigInt64Array.from([0n]),
        numWords: 0,
        words: [],
        seqLen: 1,
        truncated: false,
      };
    }
  }
  return { ...actual, GlinerTokenizer };
});

// Skip the HF download path — both backend + tokenizer are mocked above, so
// `modelDir` is only used as a string label inside the mocked classes.
vi.stubEnv('NULLPII_MODEL_DIR', '/fake');

// Import AFTER vi.mock so the singleton module picks up the stubs.
const { sanitize, __resetEngineCacheForTests } = await import('../src/nullpii.js');

beforeEach(() => {
  __resetEngineCacheForTests();
  backendConstructCount = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('F-02 · convenience sanitize() lifecycle', () => {
  it('bare sanitize(text) reuses a single shared engine across N calls', async () => {
    await sanitize('Email a@acme.io');
    await sanitize('Email b@acme.io');
    await sanitize('Email c@acme.io');
    // Today: passes (the `_shared` no-arg path already caches).
    expect(backendConstructCount).toBe(1);
  });

  it('sanitize(text, cacheableConfig) reuses the same engine for matching config', async () => {
    // Config that's structurally hashable (no recognizers / no regex / no fn).
    // Two calls with the same `{ backend: 'cpu' }` should hit the engine cache,
    // not create a fresh NullPii on each call.
    await sanitize('Email a@acme.io', { backend: 'cpu' });
    await sanitize('Email b@acme.io', { backend: 'cpu' });
    await sanitize('Email c@acme.io', { backend: 'cpu' });
    // Today: FAILS — backendConstructCount === 3 because the fast-path
    // `Object.keys(config).length > 0` always returns `new NullPii(config)`.
    expect(backendConstructCount).toBe(1);
  });

  it('sanitize(text, config) cache distinguishes by structural fingerprint', async () => {
    // Different backend values must NOT collide in the cache.
    await sanitize('Email a@acme.io', { backend: 'cpu' });
    await sanitize('Email b@acme.io', { backend: 'cpu' });
    await sanitize('Email c@acme.io', { backend: 'auto' });
    // One engine for 'cpu' + one for 'auto' = 2 total.
    expect(backendConstructCount).toBe(2);
  });

  it('sanitize(text, { recognizers: [...] }) does NOT cache and emits a one-shot warning', async () => {
    const customReco = {
      id: 'test',
      pattern: /\bACME-\d+\b/g,
      label: 'account_number' as const,
      confidence: 0.99,
    };
    const warn = vi.spyOn(process, 'emitWarning').mockImplementation(() => {});

    // Two calls with custom recognizers each spin a fresh engine — caller owns
    // lifecycle. A `NullPiiOneShotWarning` must be emitted on each call so the
    // caller can detect the leak path.
    await sanitize('ACME-123', { recognizers: [customReco] });
    await sanitize('ACME-456', { recognizers: [customReco] });

    expect(backendConstructCount).toBe(2);
    expect(warn).toHaveBeenCalled();
    const firstArgs = warn.mock.calls[0];
    expect(firstArgs?.[0]).toMatch(/nullpii/i);
    // Second arg is the warning name (Node convention).
    expect(firstArgs?.[1]).toBe('NullPiiOneShotWarning');
  });

  it('sanitize(text, { recognizers: "none" }) is cacheable (literal sentinel, not a function)', async () => {
    // `'none'` is a value-typed sentinel — structurally hashable — so the cache
    // should hit on the second call.
    await sanitize('Email a@acme.io', { recognizers: 'none' });
    await sanitize('Email b@acme.io', { recognizers: 'none' });
    expect(backendConstructCount).toBe(1);
  });
});
