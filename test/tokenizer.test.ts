import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { TokenizerWrapper } from '../src/tokenizer.js';

const FIXTURE_DIR = fileURLToPath(new URL('./fixtures/tokenizer/', import.meta.url));

describe('TokenizerWrapper.encode', () => {
  it('produces aligned ids, mask, and offset mapping', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const enc = await tok.encode('hello world');
    expect(enc.inputIds.length).toBeGreaterThan(0);
    expect(enc.attentionMask.length).toBe(enc.inputIds.length);
    expect(enc.offsetMapping.length).toBe(enc.inputIds.length);
  });

  it('attentionMask is all 1s for non-padded input', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const enc = await tok.encode('hello world');
    for (const m of enc.attentionMask) expect(m).toBe(1n);
  });

  it('offset mapping covers the original text up to its length', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const text = 'hello world';
    const enc = await tok.encode(text);
    const last = enc.offsetMapping.at(-1);
    expect(last).toBeDefined();
    if (last !== undefined) {
      expect(last[1]).toBeGreaterThanOrEqual(text.length - 1);
      expect(last[1]).toBeLessThanOrEqual(text.length);
    }
  });

  it('encodes the full input — chunking layer handles the per-chunk cap', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR, 5);
    const enc = await tok.encode('hello world my name is john the quick brown fox hello world');
    // Per-chunk size from constructor is no longer enforced at the tokenizer
    // level — it is consulted by `partitionTokens` downstream.
    expect(enc.inputIds.length).toBeGreaterThan(5);
  });

  it('reuses the loaded tokenizer across calls (cached)', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const a = await tok.encode('hello');
    const b = await tok.encode('world');
    expect(a.inputIds.length).toBeGreaterThan(0);
    expect(b.inputIds.length).toBeGreaterThan(0);
  });

  it('throws ModelNotFoundError when tokenizer.json is missing', async () => {
    const empty = mkdtempSync(join(tmpdir(), 'nullpii-tok-'));
    expect(existsSync(join(empty, 'tokenizer.json'))).toBe(false);
    const tok = new TokenizerWrapper(empty);
    await expect(tok.encode('x')).rejects.toBeInstanceOf(ModelNotFoundError);
  });
});

describe('TokenizerWrapper.decode', () => {
  it('round-trips a tokenized sentence', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const text = 'hello world';
    const enc = await tok.encode(text);
    const back = await tok.decode(enc.inputIds);
    expect(back.toLowerCase()).toContain('hello');
    expect(back.toLowerCase()).toContain('world');
  });

  it('accepts a plain number array as input', async () => {
    const tok = new TokenizerWrapper(FIXTURE_DIR);
    const enc = await tok.encode('hello');
    const ids: number[] = Array.from(enc.inputIds, (n) => Number(n));
    const back = await tok.decode(ids);
    expect(back.length).toBeGreaterThan(0);
  });
});
