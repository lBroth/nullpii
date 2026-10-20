// SPDX-License-Identifier: Apache-2.0

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** What the mocked engine and model manager saw. */
const seen = vi.hoisted(() => ({
  configs: [] as unknown[],
  texts: [] as string[],
  destroyed: [] as string[],
  disposed: 0,
  ensured: [] as unknown[],
}));

/** Lines `scan --ndjson` writes with `fs.writeSync(1, …)`. */
const ndjsonOut = vi.hoisted(() => [] as string[]);
vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  return {
    ...actual,
    writeSync: (fd: number, data: string, ...rest: unknown[]) => {
      if (fd === 1) {
        ndjsonOut.push(String(data));
        return String(data).length;
      }
      return (actual.writeSync as (...a: unknown[]) => number)(fd, data, ...rest);
    },
  };
});

vi.mock('../src/nullpii.js', () => {
  let n = 0;
  class NullPii {
    constructor(config: unknown) {
      seen.configs.push(config);
    }
    async sanitize(text: string) {
      seen.texts.push(text);
      const at = text.indexOf('alice@acme.io');
      const spans =
        at < 0
          ? []
          : [
              {
                label: 'private_email',
                start: at,
                end: at + 13,
                text: 'alice@acme.io',
                score: 0.99,
              },
            ];
      return {
        sessionId: `s${n++}`,
        sanitized: text.replace('alice@acme.io', '{{PII_PRIVATE_EMAIL_0_x}}'),
        spans,
      };
    }
    destroySession(id: string) {
      seen.destroyed.push(id);
    }
    async dispose() {
      seen.disposed += 1;
    }
  }
  return { NullPii };
});

vi.mock('../src/model-manager.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/model-manager.js')>();
  class ModelManager {
    get modelDir(): string {
      return join(
        process.env.XDG_CACHE_HOME ?? '/nonexistent',
        'nullpii',
        'models',
        'lBroth',
        'nullpii',
        'main',
      );
    }
    async ensure(options: { onProgress?: (p: number) => void }) {
      seen.ensured.push(options);
      options.onProgress?.(1);
      return { modelDir: '/cache/model', onnxFile: 'model.onnx' };
    }
  }
  return { ...actual, ModelManager };
});

const { run } = await import('../src/cli/index.js');

let out = '';
let err = '';
let dir = '';
beforeEach(() => {
  out = '';
  err = '';
  Object.assign(seen, { configs: [], texts: [], destroyed: [], disposed: 0, ensured: [] });
  dir = mkdtempSync(join(tmpdir(), 'nullpii-cli-'));
  vi.stubEnv('XDG_CONFIG_HOME', dir);
  vi.stubEnv('XDG_CACHE_HOME', dir);
  vi.spyOn(process.stdout, 'write').mockImplementation((c: string | Uint8Array) => {
    out += String(c);
    return true;
  });
  vi.spyOn(process.stderr, 'write').mockImplementation((c: string | Uint8Array) => {
    err += String(c);
    return true;
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  rmSync(dir, { recursive: true, force: true });
});

const cli = (...args: string[]) => run(['node', 'nullpii', ...args]);

describe('nullpii scan', () => {
  it('prints the spans as JSON and disposes the engine', async () => {
    expect(await cli('scan', 'mail alice@acme.io', '--format', 'json', '--backend', 'cpu')).toBe(0);
    expect(JSON.parse(out).spans[0].label).toBe('private_email');
    expect(seen.configs[0]).toEqual({ backend: 'cpu' });
    expect(seen.disposed).toBe(1);
  });

  it('prints a pretty report, or says nothing was found', async () => {
    await cli('scan', 'mail alice@acme.io');
    expect(out).toContain('private_email');
    out = '';
    await cli('scan', 'nothing here');
    expect(out).toContain('no PII detected');
  });

  it('reads NDJSON lines, one result and one freed session per line', async () => {
    vi.spyOn(process, 'stdin', 'get').mockReturnValue(
      Readable.from([
        '{"text":"mail alice@acme.io"}\n',
        'not json\n',
        '{"nope":1}\n',
        '{"text":"x y"}\n',
      ]) as never,
    );
    ndjsonOut.length = 0;
    expect(await cli('scan', '--ndjson')).toBe(0);
    expect(ndjsonOut.map((l) => Object.keys(JSON.parse(l))[0])).toEqual([
      'spans',
      'error',
      'error',
      'spans',
    ]);
    expect(seen.texts).toEqual(['mail alice@acme.io', 'x y']);
    // Every sanitized line frees its own session (ids depend on test order).
    expect(seen.destroyed).toHaveLength(2);
    expect(new Set(seen.destroyed).size).toBe(2);
  });

  it('fails without text', async () => {
    expect(await cli('scan')).toBe(1);
    expect(err).toContain('scan: pass <text>');
  });

  it('applies the config file under its flags', async () => {
    const file = join(dir, 'policy.json');
    writeFileSync(file, JSON.stringify({ threshold: 0.3, disabledCategories: ['private_title'] }));
    await cli('scan', 'x', '--config', file, '--threshold', '0.2');
    expect(seen.configs[0]).toEqual({ threshold: 0.2, disabledCategories: ['private_title'] });
  });
});

describe('nullpii sanitize', () => {
  it('prints the sanitized text without a session id, and disposes the engine', async () => {
    expect(await cli('sanitize', 'mail alice@acme.io')).toBe(0);
    expect(out).toBe('mail {{PII_PRIVATE_EMAIL_0_x}}\n');
    expect(seen.disposed).toBe(1);
  });

  it('reads stdin and prints JSON', async () => {
    vi.spyOn(process, 'stdin', 'get').mockReturnValue(
      Readable.from([Buffer.from('mail alice@acme.io')]) as never,
    );
    await cli('sanitize', '--stdin', '--format', 'json');
    expect(JSON.parse(out)).toMatchObject({ sanitized: 'mail {{PII_PRIVATE_EMAIL_0_x}}' });
    expect(JSON.parse(out).sessionId).toBeUndefined();
  });

  it('rejects an unknown backend', async () => {
    expect(await cli('sanitize', 'x', '--backend', 'gpu')).toBe(1);
  });
});

describe('nullpii prefetch and models', () => {
  it('prefetches for a backend and precision', async () => {
    expect(await cli('prefetch', '--backend', 'cuda', '--variant', 'fp16')).toBe(0);
    expect(seen.ensured[0]).toMatchObject({ backend: 'cuda', variant: 'fp16' });
    expect(out).toContain('cached at: /cache/model (model.onnx)');
  });

  it('lists cached files, or says none are cached', async () => {
    await cli('models', 'list');
    expect(out).toContain('no models cached');
    out = '';
    const cacheDir = join(dir, 'nullpii', 'models');
    mkdirSync(join(cacheDir, 'org'), { recursive: true });
    writeFileSync(join(cacheDir, 'org', 'tokenizer.json'), '{}');
    await cli('models', 'list');
    expect(out).toContain('org/tokenizer.json');
  });
});

describe('nullpii doctor', () => {
  it('reports each check and exits 0 when healthy', async () => {
    const exit = vi.spyOn(process, 'exit').mockImplementation((() => undefined) as never);
    await cli('doctor');
    expect(out).toContain('node version');
    expect(out).toContain('model artifacts');
    expect(out).toContain('onnxruntime-node');
    expect(exit).toHaveBeenCalled();
  });
});

describe('nullpii config', () => {
  it('prints no file and the default restore tools when there is no config', async () => {
    expect(await cli('config')).toBe(0);
    const shown = JSON.parse(out);
    expect(shown).toMatchObject({ file: null, policy: {} });
    expect(shown.restoreTools).toContain('Bash');
  });

  it('prints the validated file and its restore-tool list', async () => {
    mkdirSync(join(dir, 'nullpii'));
    const file = join(dir, 'nullpii', 'config.json');
    writeFileSync(
      file,
      JSON.stringify({ disabledCategories: ['private_title'], restoreTools: ['Read'] }),
    );
    expect(await cli('config')).toBe(0);
    expect(JSON.parse(out)).toEqual({
      file,
      policy: { disabledCategories: ['private_title'], restoreTools: ['Read'] },
      restoreTools: ['Read'],
    });
  });

  it('fails on an invalid file, naming the problem', async () => {
    const file = join(dir, 'bad.json');
    writeFileSync(file, '{"disabledCategory": []}');
    expect(await cli('config', '--config', file)).toBe(1);
    expect(err).toContain('unknown key "disabledCategory"');
  });
});
