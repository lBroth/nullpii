import { writeFileSync } from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { InvalidPathError } from '../src/errors.js';
import { fileExists, resolveSafePath } from '../src/paths.js';

describe('fileExists', () => {
  it('returns true for an existing readable file', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'nullpii-paths-'));
    const f = join(dir, 'present.txt');
    writeFileSync(f, 'x');
    expect(await fileExists(f)).toBe(true);
  });

  it('returns false for a missing path', async () => {
    expect(await fileExists('/this/does/not/exist/at/all')).toBe(false);
  });
});

describe('resolveSafePath', () => {
  it('resolves a relative path inside cwd', () => {
    const cwd = mkdtempSync(join(tmpdir(), 'nullpii-cwd-'));
    const out = resolveSafePath('subdir/file.txt', cwd);
    expect(out.startsWith(cwd)).toBe(true);
  });

  it('rejects a relative path that escapes cwd', () => {
    const cwd = mkdtempSync(join(tmpdir(), 'nullpii-cwd-'));
    expect(() => resolveSafePath('../../../etc/passwd', cwd)).toThrow(InvalidPathError);
  });

  it('rejects an absolute path outside cwd', () => {
    const cwd = mkdtempSync(join(tmpdir(), 'nullpii-cwd-'));
    expect(() => resolveSafePath('/etc/passwd', cwd)).toThrow(InvalidPathError);
  });

  it('accepts an absolute path inside cwd', () => {
    const cwd = mkdtempSync(join(tmpdir(), 'nullpii-cwd-'));
    const inside = join(cwd, 'a', 'b.txt');
    expect(resolveSafePath(inside, cwd)).toBe(inside);
  });
});
