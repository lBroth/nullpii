// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { Command } from 'commander';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type EngineOptions, addEngineOptions, engineConfig } from '../src/cli/engine-options.js';
import { readLines } from '../src/cli/read-lines.js';

function parse(args: string[]): EngineOptions {
  const cmd = addEngineOptions(
    new Command().exitOverride().configureOutput({ writeErr: () => {} }),
  );
  cmd.parse(args, { from: 'user' });
  return cmd.opts<EngineOptions>();
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('CLI engine options', () => {
  it('parses every shared flag', () => {
    const opts = parse([
      '--backend',
      'cuda',
      '--threshold',
      '0.2',
      '--threads',
      '4',
      '--model-dir',
      '/m',
    ]);
    expect(opts).toMatchObject({ backend: 'cuda', threshold: 0.2, threads: 4, modelDir: '/m' });
  });

  it.each([
    ['an unknown backend', ['--backend', 'gpu']],
    ['a threshold out of range', ['--threshold', '2']],
    ['a threshold that is not a number', ['--threshold', 'high']],
    ['a negative thread count', ['--threads', '-1']],
  ])('rejects %s', (_case, args) => {
    expect(() => parse(args)).toThrow();
  });

  it('layers the flags over the config file', () => {
    const dir = mkdtempSync(join(tmpdir(), 'nullpii-cli-'));
    try {
      vi.stubEnv('XDG_CONFIG_HOME', dir);
      const file = join(dir, 'policy.json');
      writeFileSync(
        file,
        JSON.stringify({ threshold: 0.3, disabledCategories: ['private_title'] }),
      );
      expect(engineConfig({ config: file, threshold: 0.1 })).toEqual({
        threshold: 0.1,
        disabledCategories: ['private_title'],
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('readLines', () => {
  it('splits on newlines only, keeping U+2028 and U+2029 inside a line', async () => {
    const rows = ['{"text":"a b"}', '{"text":"c d"}', '{"text":"e"}'];
    const input = Readable.from([
      Buffer.from(`${rows[0]}\r\n${rows[1]}\n`),
      Buffer.from(rows[2] ?? ''),
    ]);
    const out: string[] = [];
    for await (const line of readLines(input)) out.push(line);
    expect(out).toEqual(rows);
  });

  it('keeps a multi-byte character split across chunks whole', async () => {
    const bytes = Buffer.from('{"text":"é"}\n');
    const input = Readable.from([bytes.subarray(0, 10), bytes.subarray(10)]);
    const out: string[] = [];
    for await (const line of readLines(input)) out.push(line);
    expect(out).toEqual(['{"text":"é"}']);
  });
});
