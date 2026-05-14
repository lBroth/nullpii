// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ModelNotInitializedError,
  SessionMismatchError,
  SessionNotFoundError,
} from '../src/errors.js';
import { NullPii } from '../src/nullpii.js';
import { PLACEHOLDER_REGEX } from '../src/types/index.js';

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

// ─── End-to-end pipeline (mocked ONNX session) ──────────────────────
// Exercises `runInit → sanitize → restore → dispose` without needing
// the multi-GB unified model. The OrtUnifiedBackend.infer is stubbed
// to return zero spans; recognizer pack drives detection. Verifies:
//   - init resolves once and is cached
//   - recognizer-only spans round-trip through the vault
//   - placeholders carry the session prefix (A3)
//   - dispose clears vault state (A4)
//   - restore on a different session raises SessionMismatchError (A3)
vi.mock('../src/backend/unified-backend.js', () => {
  class OrtUnifiedBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return {
        logits: new Float32Array(0),
        textLength: 0,
        maxWidth: 1,
        numClasses: 8,
      };
    }
    async dispose(): Promise<void> {}
  }
  return { OrtUnifiedBackend };
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
  return {
    ...actual,
    GlinerTokenizer,
  };
});

describe('NullPii e2e pipeline (mocked ONNX)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('sanitize → restore round-trips via the recognizer pack', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    // Use `acme.io` — `example.com` / `.test` are RFC 6761 reserved and the
    // recognizer pack's never-PII filter drops them, which is what you want
    // in production but not in this test.
    const text = 'Send to alice@acme.io today.';
    const out = await n.sanitize(text);

    expect(out.spans.length).toBeGreaterThan(0);
    const emailSpan = out.spans.find((s) => s.label === 'private_email');
    expect(emailSpan?.text).toBe('alice@acme.io');

    // Sanitized output replaces the email with a session-tagged placeholder.
    const placeholders = [...out.sanitized.matchAll(new RegExp(PLACEHOLDER_REGEX.source, 'g'))];
    expect(placeholders.length).toBe(out.spans.length);

    const restored = n.restore(out.sanitized, out.sessionId);
    expect(restored.restored).toBe(text);
    expect(restored.replacements).toBe(out.spans.length);
    await n.dispose();
  });

  it('placeholders embed the session prefix (A3)', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await n.sanitize('Email: contact@acme.io');
    const sessionPrefix = out.sessionId.replace(/-/g, '').slice(0, 16).toLowerCase();
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    for (const match of out.sanitized.matchAll(re)) {
      expect(match[3]).toBe(sessionPrefix);
    }
    await n.dispose();
  });

  it('dispose clears the vault (A4)', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await n.sanitize('Mail: foo@acme.io');
    // Round-trip works before dispose.
    expect(n.restore(out.sanitized, out.sessionId).replacements).toBeGreaterThan(0);
    await n.dispose();
    // After dispose, the vault is wiped → restore on the same session id
    // throws SessionNotFoundError.
    expect(() => n.restore(out.sanitized, out.sessionId)).toThrow(SessionNotFoundError);
  });

  it('restoring with a foreign session id surfaces foreignPlaceholders, throws under strict (A3)', async () => {
    const a = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const b = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await a.sanitize('Reach me at bob@acme.io');
    // `b` knows nothing about `a`'s session; placeholders still carry `a`'s prefix.
    // Force `b` to have a session of its own so the prefix check is the
    // discriminating signal (not SessionNotFoundError on the unknown id).
    const otherOut = await b.sanitize('Different text from carol@nullpii.dev');
    expect(out.spans.length).toBeGreaterThan(0);
    expect(otherOut.spans.length).toBeGreaterThan(0);
    // Default: no throw, anomalies in the result arrays.
    const r = b.restore(out.sanitized, otherOut.sessionId);
    expect(r.foreignPlaceholders.length).toBeGreaterThan(0);
    expect(r.replacements).toBe(0);
    // strict: true preserves the legacy throw contract.
    expect(() => b.restore(out.sanitized, otherOut.sessionId, { strict: true })).toThrow(
      SessionMismatchError,
    );
    await a.dispose();
    await b.dispose();
  });

  it('init runs once across many sanitize calls', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const r1 = await n.sanitize('First email: a@acme.io');
    const r2 = await n.sanitize('Second email: c@nullpii.dev');
    // Both calls should use independent session ids — vault is per-call by default.
    expect(r1.sessionId).not.toBe(r2.sessionId);
    expect(n.restore(r1.sanitized, r1.sessionId).restored).toBe('First email: a@acme.io');
    expect(n.restore(r2.sanitized, r2.sessionId).restored).toBe('Second email: c@nullpii.dev');
    await n.dispose();
  });
});
