// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DecodedSpan } from '../src/gliner-decoder.js';
import { NullPii } from '../src/nullpii.js';
import { secretPassLabels, secretsSeenByFirstPass } from '../src/secret-pass.js';

// The model is stubbed: each pass proposes the candidates `model.propose`
// returns for its prompt, and the stub decoder keeps those that reach the
// cut the engine hands it, as the real decoder does.
const LONG_WORD_CHARS = vi.hoisted(() => 400);
const model = vi.hoisted(() => ({
  propose: (_labels: readonly string[]): DecodedSpan[] => [],
  prompts: [] as (readonly string[])[],
}));

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return { logits: new Float32Array(0), textLength: 0, maxWidth: 1, numClasses: 0 };
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
      model.prompts.push(labels);
      const words = actual.splitWords(text);
      // A word of `LONG_WORD_CHARS` or more fits no window under a prompt
      // of more than one label, as a long token under the default's: the
      // encoder keeps the words before it.
      const long = words.findIndex((w) => w.charEnd - w.charStart >= LONG_WORD_CHARS);
      if (labels.length > 1 && long >= 0) {
        return {
          inputIds: BigInt64Array.from([0n]),
          attentionMask: BigInt64Array.from([1n]),
          wordsMask: BigInt64Array.from([0n]),
          numWords: long,
          words: words.slice(0, long),
          seqLen: 1,
          truncated: true,
        };
      }
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
  return { ...actual, GlinerTokenizer };
});

vi.mock('../src/gliner-decoder.js', () => ({
  decodeGlinerLogits: (...args: unknown[]): DecodedSpan[] => {
    const labels = args[5] as readonly string[];
    const cut = args[6] as (label: string) => number;
    return model.propose(labels).filter((s) => labels.includes(s.label) && s.score >= cut(s.label));
  },
}));

/** Every category but `secret`: the secrets-only preset. */
const SECRETS_ONLY = [
  'private_person',
  'private_email',
  'private_phone',
  'private_address',
  'private_url',
  'private_ip',
  'private_mac',
  'private_geolocation',
  'private_passport',
  'private_driver_license',
  'private_vehicle_id',
  'account_number',
  'private_date',
  'private_organization',
  'private_occupation',
  'private_demographic',
  'private_sensitive',
  'private_title',
] as const;

const at = (text: string, value: string, label: string, score: number): DecodedSpan => {
  const start = text.indexOf(value);
  if (start < 0) throw new Error(`${value} not in ${text}`);
  return { label, start, end: start + value.length, score };
};
/** Whether a pass's prompt is the secret pass's: `secret` is in it, and
 * `account_number` (which the default prompts) is not. */
const isSecretPass = (labels: readonly string[]) =>
  labels.includes('secret') && !labels.includes('account_number');

describe('secretPassLabels', () => {
  const ALL = ['private_person', 'private_email', 'account_number', 'secret', 'private_date'];
  const DEFAULT_PROMPT = ['private_person', 'private_email', 'account_number', 'secret'];

  it('runs no secret pass when the policy prompts what the first pass prompts', () => {
    expect(secretPassLabels(ALL, DEFAULT_PROMPT, new Set(['private_date']))).toBeNull();
    expect(secretPassLabels(ALL, ALL, new Set())).toBeNull();
  });

  it('runs no secret pass when the policy leaves secrets readable', () => {
    expect(secretPassLabels(ALL, DEFAULT_PROMPT, new Set(['secret', 'private_date']))).toBeNull();
  });

  it('prompts the labels the policy masks, and no other, in prompt order', () => {
    const disabled = new Set(['private_email', 'account_number', 'private_date']);
    expect(secretPassLabels(ALL, DEFAULT_PROMPT, disabled)).toEqual(['private_person', 'secret']);
  });
});

describe('secretsSeenByFirstPass', () => {
  const secret = { label: 'secret', start: 10, end: 20 };

  it('keeps a secret that overlaps a range the first pass saw', () => {
    expect(secretsSeenByFirstPass([secret], [{ start: 15, end: 30 }])).toEqual([secret]);
    expect(secretsSeenByFirstPass([secret], [{ start: 0, end: 11 }])).toEqual([secret]);
  });

  it('drops a secret the first pass saw nothing in, a range that only touches it included', () => {
    expect(secretsSeenByFirstPass([secret], [])).toEqual([]);
    expect(secretsSeenByFirstPass([secret], [{ start: 20, end: 30 }])).toEqual([]);
    expect(secretsSeenByFirstPass([secret], [{ start: 0, end: 10 }])).toEqual([]);
  });

  it('takes only secrets', () => {
    const person = { label: 'private_person', start: 10, end: 20 };
    expect(secretsSeenByFirstPass([person], [{ start: 10, end: 20 }])).toEqual([]);
  });
});

describe('the secret pass in the engine', () => {
  afterEach(() => {
    model.propose = () => [];
    model.prompts = [];
  });

  it('masks under secrets-only a credential the default prompt files as an account number', async () => {
    const text = 'auth: 7f6e5d4c3b2a41908f7e';
    const value = '7f6e5d4c3b2a41908f7e';
    model.propose = (labels) =>
      isSecretPass(labels)
        ? [at(text, value, 'secret', 0.4)]
        : [at(text, value, 'account_number', 0.9)];
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      disabledCategories: [...SECRETS_ONLY],
    });
    const out = await n.sanitize(text);
    expect(out.spans.map((s) => [s.label, s.text])).toEqual([['secret', value]]);
    expect(model.prompts.filter(isSecretPass)).toHaveLength(1);
    await n.dispose();
  });

  it('leaves readable a word only the secret pass flags', async () => {
    // #92: with `secret` prompted alone the model flags `code`; the
    // default's prompt finds nothing there.
    const text = 'code';
    model.propose = (labels) => (isSecretPass(labels) ? [at(text, 'code', 'secret', 0.106)] : []);
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      disabledCategories: [...SECRETS_ONLY],
    });
    const out = await n.sanitize(text);
    expect(out.spans).toEqual([]);
    expect(out.sanitized).toBe(text);
    await n.dispose();
  });

  it('takes only secrets from the secret pass, so a readable category is not masked as another', async () => {
    // With the email label out of its prompt, the secret pass files the
    // address under a person; the policy leaves emails readable.
    const text = 'Send to john.smith@acme.io now';
    const email = 'john.smith@acme.io';
    model.propose = (labels) =>
      isSecretPass(labels)
        ? [at(text, email, 'private_person', 0.8)]
        : [at(text, email, 'private_email', 0.9)];
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: 'none',
      disabledCategories: ['private_email', 'account_number', 'private_date'],
    });
    const out = await n.sanitize(text);
    expect(out.sanitized).toBe(text);
    await n.dispose();
  });

  it('a readable label the first pass finds does not suppress a secret it masks', async () => {
    const text = 'key sk-test-123';
    model.propose = () => [
      at(text, 'sk-test-123', 'account_number', 0.9),
      at(text, 'sk-test-123', 'secret', 0.3),
    ];
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: 'none',
      disabledCategories: ['account_number'],
    });
    const out = await n.sanitize(text);
    expect(out.spans.map((s) => [s.label, s.text])).toEqual([['secret', 'sk-test-123']]);
    await n.dispose();
  });

  it('masks a secret where only the recognizer pack saw something', async () => {
    // `core:url` finds the URL, which the policy leaves readable; the model's
    // first pass finds nothing.
    const token = 'o7ZFVxtM76doa3W5a9HoLDZPOH5DnL0s';
    const text = `https://api.acme.io/v1/data?slack_bot_token=${token}&page=2`;
    // The secret pass is the prompt without the readable `private_url`.
    model.propose = (labels) =>
      labels.includes('private_url') ? [] : [at(text, token, 'secret', 0.3)];
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      disabledCategories: ['private_url', 'private_date'],
    });
    const out = await n.sanitize(text);
    expect(out.sanitized).not.toContain(token);
    expect(out.spans.map((s) => s.label)).toEqual(['secret']);
    await n.dispose();
  });

  it('masks a secret in a word the first pass could not read', async () => {
    const token = 'Qm7Xv2Lp9Rk4'.repeat(40);
    const text = `token=${token}`;
    model.propose = (labels) => (isSecretPass(labels) ? [at(text, text, 'secret', 0.6)] : []);
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: 'none',
      disabledCategories: [...SECRETS_ONLY],
    });
    const out = await n.sanitize(text);
    expect(out.modelUnscannedWords).toBe(1);
    expect(out.sanitized).not.toContain(token);
    await n.dispose();
  });

  it('runs one pass under the default and the everything policies', async () => {
    for (const disabledCategories of [undefined, []]) {
      model.prompts = [];
      const n = new NullPii({
        modelDir: '/fake',
        backend: 'cpu',
        ...(disabledCategories !== undefined && { disabledCategories }),
      });
      await n.sanitize('hello there');
      expect(model.prompts).toHaveLength(1);
      await n.dispose();
    }
  });

  it('runs no secret pass when the policy leaves secrets readable', async () => {
    const n = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      disabledCategories: ['secret', 'private_email', 'private_date'],
    });
    await n.sanitize('hello there');
    expect(model.prompts).toHaveLength(1);
    await n.dispose();
  });
});
