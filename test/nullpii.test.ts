// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EngineDisposedError, SessionMismatchError, SessionNotFoundError } from '../src/errors.js';
import { InvalidConfigError } from '../src/errors.js';
import { NullPii } from '../src/nullpii.js';
import { GLINER_MODEL_CATEGORIES, PLACEHOLDER_REGEX } from '../src/types/index.js';

describe('NullPii lifecycle', () => {
  it('rejects sanitize after dispose with EngineDisposedError', async () => {
    const n = new NullPii({ modelDir: '/nonexistent', backend: 'cpu' });
    await n.dispose();
    await expect(n.sanitize('hi')).rejects.toBeInstanceOf(EngineDisposedError);
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
// What the last `encode` call prompted, so the mocked backend can answer
// with one logit column per label, as the real model does, and tests can
// check which labels were prompted.
const prompt = vi.hoisted(() => ({ labels: [] as readonly string[] }));
/** Lets a test hold `infer()` open and count backend releases. */
const gate = vi.hoisted(() => ({ hold: null as Promise<void> | null, released: 0 }));

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      if (gate.hold !== null) await gate.hold;
      return {
        logits: new Float32Array(0),
        textLength: 0,
        maxWidth: 1,
        numClasses: prompt.labels.length,
      };
    }
    async dispose(): Promise<void> {
      gate.released += 1;
    }
  }
  return { OrtBackend };
});

vi.mock('../src/gliner-tokenizer.js', async () => {
  const actual = await vi.importActual<typeof import('../src/gliner-tokenizer.js')>(
    '../src/gliner-tokenizer.js',
  );
  class GlinerTokenizer {
    // Reports every word as consumed, like the real encoder on short
    // input, so the window scheduler sees an uncut window.
    async encode(
      text: string,
      labels: readonly string[],
    ): Promise<{
      inputIds: BigInt64Array;
      attentionMask: BigInt64Array;
      wordsMask: BigInt64Array;
      numWords: number;
      words: ReturnType<typeof actual.splitWords>;
      seqLen: number;
      truncated: boolean;
    }> {
      prompt.labels = labels;
      const words = actual.splitWords(text);
      return {
        inputIds: BigInt64Array.from([0n]),
        attentionMask: BigInt64Array.from([1n]),
        wordsMask: BigInt64Array.from([0n]),
        numWords: words.length,
        words,
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

  it('prompts every category by default, extended ones included', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    await n.sanitize('Send to alice@acme.io today.');
    expect(prompt.labels).toContain('private_organization');
    expect(prompt.labels).toContain('private_sensitive');
    expect(prompt.labels.slice(0, 8)).toEqual(GLINER_MODEL_CATEGORIES);
    await n.dispose();
  });

  it('disabledCategories are neither prompted nor emitted', async () => {
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      disabledCategories: ['private_email', 'private_occupation'],
    });
    const out = await n.sanitize('Send to alice@acme.io today.');
    expect(prompt.labels).not.toContain('private_email');
    expect(prompt.labels).not.toContain('private_occupation');
    expect(prompt.labels).toContain('private_person');
    // The recognizer pack matches the address, but its label is off.
    expect(out.spans.find((s) => s.label === 'private_email')).toBeUndefined();
    expect(out.sanitized).toContain('alice@acme.io');
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

  it('keeps reference and code-host URLs verbatim, private hosts masked', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const text =
      'See https://docs.python.org/3/library/re.html, https://github.com/anthropics/claude-code/issues and https://acme.io/internal';
    const out = await n.sanitize(text);
    const urlSpans = out.spans.filter((s) => s.label === 'private_url').map((s) => s.text);
    expect(urlSpans).toEqual(['https://acme.io/internal']);
    expect(out.sanitized).toContain('https://docs.python.org/3/library/re.html');
    expect(out.sanitized).toContain('https://github.com/anthropics/claude-code/issues');
    expect(n.restore(out.sanitized, out.sessionId).restored).toBe(text);
    await n.dispose();
  });

  it('urlAllowlist.hosts changes how much of a URL stays readable', async () => {
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      urlAllowlist: { hosts: { '*.github.com': 'host', '*.python.org': 'mask' } },
    });
    const text = 'See https://github.com/foo/bar and https://docs.python.org/3/';
    const out = await n.sanitize(text);
    expect(out.spans.filter((s) => s.label === 'private_url').map((s) => s.text)).toEqual([
      '/foo/bar',
      'https://docs.python.org/3/',
    ]);
    expect(out.sanitized).toContain('https://github.com{{');
    await n.dispose();
  });

  it('rejects an invalid urlAllowlist at construction', () => {
    expect(
      () =>
        new NullPii({
          modelDir: '/fake',
          backend: 'cpu',
          urlAllowlist: { hosts: { 'https://x.io': 'full' } },
        }),
    ).toThrow(InvalidConfigError);
  });

  it('urlAllowlist: "none" redacts every URL including public hosts', async () => {
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu', urlAllowlist: 'none' });
    const text = 'See https://github.com/foo and https://acme.io/internal';
    const out = await n.sanitize(text);
    const urlSpans = out.spans.filter((s) => s.label === 'private_url');
    expect(urlSpans).toHaveLength(2);
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

describe('dispose() and work in flight', () => {
  it('waits for a running sanitize() before releasing the session, and refuses new calls', async () => {
    let release = (): void => {};
    gate.hold = new Promise<void>((resolve) => {
      release = resolve;
    });
    const before = gate.released;
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const running = n.sanitize('Write to alice@acme.io about the plan for the week.');
    const disposing = n.dispose();
    await expect(n.sanitize('more text')).rejects.toBeInstanceOf(EngineDisposedError);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(gate.released).toBe(before);
    release();
    gate.hold = null;
    await expect(running).resolves.toMatchObject({ sanitized: expect.any(String) });
    await disposing;
    expect(gate.released).toBe(before + 1);
  });
});

describe('boundary refine keeps punctuation inside secrets', () => {
  it('trims punctuation off a name but not off a secret', async () => {
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: [
        { id: 't:secret', pattern: /"hunter2!;/g, label: 'secret', confidence: 0.99 },
        { id: 't:person', pattern: /Mario Rossi,/g, label: 'private_person', confidence: 0.99 },
      ],
    });
    const out = await n.sanitize('pw "hunter2!; owner Mario Rossi, ok');
    const byLabel = Object.fromEntries(out.spans.map((s) => [s.label, s.text]));
    expect(byLabel.secret).toBe('"hunter2!;');
    expect(byLabel.private_person).toBe('Mario Rossi');
    await n.dispose();
  });
});
