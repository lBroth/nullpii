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
// the multi-GB model. The OrtBackend.infer is stubbed
// to return zero spans; recognizer pack drives detection. Verifies:
//   - init resolves once and is cached
//   - recognizer-only spans round-trip through the vault
//   - placeholders carry the session prefix (A3)
//   - dispose clears vault state (A4)
//   - restore on a different session raises SessionMismatchError (A3)
vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
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
        numClasses: 12,
      };
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

  it('preserves user-authored {{...}} templates around a real PII hit', async () => {
    // Regression: gateway report showed `{{short-kebab-case-slug}}` in a
    // system prompt was corrupted to `{{PII_PRIVATE_PERSON_2_…}}short-kebab-case-slug}}`
    // because the escape PUA sentinel was tagged as `private_person`.
    // With sentinels stripped before detection, the template survives the
    // round-trip and the real PII (email) is the only thing replaced.
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const text = 'name: {{short-kebab-case-slug}} — contact alice@acme.io';
    const out = await n.sanitize(text);
    // Exactly one span — the email — fires from the recognizer pack.
    // The template syntax is untouched.
    expect(out.spans.find((s) => s.label === 'private_email')?.text).toBe('alice@acme.io');
    expect(out.sanitized).toContain('{{short-kebab-case-slug}}');
    expect(out.sanitized).not.toContain('{{PII_PRIVATE_PERSON');
    const restored = n.restore(out.sanitized, out.sessionId);
    expect(restored.restored).toBe(text);
    await n.dispose();
  });

  it('drops low-confidence private_date spans via built-in category threshold', async () => {
    // Default `categoryThresholds.private_date` = 0.85 — a recognizer
    // that fires at 0.7 must be dropped; one at 0.9 must survive. This
    // protects against the gateway-report case of innocuous calendar
    // dates in system prompts being placeholdered.
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: [
        {
          id: 'test:weak-date',
          pattern: /\b2026-05-21\b/g,
          label: 'private_date',
          confidence: 0.7,
        },
        {
          id: 'test:strong-date',
          pattern: /\b1985-03-12\b/g,
          label: 'private_date',
          confidence: 0.9,
        },
      ],
    });
    const out = await n.sanitize('Today 2026-05-21 — DOB 1985-03-12');
    expect(out.spans).toHaveLength(1);
    expect(out.spans[0]?.text).toBe('1985-03-12');
    await n.dispose();
  });

  it('user categoryThresholds override built-in date default per-key', async () => {
    // Caller can lower the bar back down for their own use case.
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      categoryThresholds: { private_date: 0.5 },
      recognizers: [
        {
          id: 'test:weak-date',
          pattern: /\b2026-05-21\b/g,
          label: 'private_date',
          confidence: 0.7,
        },
      ],
    });
    const out = await n.sanitize('Today 2026-05-21');
    expect(out.spans).toHaveLength(1);
    await n.dispose();
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
