// SPDX-License-Identifier: Apache-2.0
//
// SidecarSessions on its own: what a supersede does to the key it names,
// and the cap on remembered keys, with a counting stand-in for the vault.

import type { NullPii } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { SidecarSessions, canSupersede } from '../src/sidecar-sessions.js';

const TTL_MS = 1_000;
/** As `UNCLOSED_KEYS_MAX` in the table: the keys it remembers one by one. */
const REMEMBERED_MAX = 1024;

function table(maxSessions = 8) {
  let vaults = 0;
  const destroyed: string[] = [];
  const np = {
    createSession: () => `vault-${vaults++}`,
    destroySession: (id: string) => {
      destroyed.push(id);
    },
  } as unknown as NullPii;
  const clock = { t: 0 };
  const sessions = new SidecarSessions(np, { ttlMs: TTL_MS, maxSessions, now: () => clock.t });
  return { sessions, clock, destroyed };
}

/** The secret `open` handed out for a created session. */
function secretOf(result: ReturnType<SidecarSessions['open']>): string {
  if (result.kind !== 'created') throw new Error(`expected created, got ${result.kind}`);
  return result.secret;
}

describe('SidecarSessions · supersedes', () => {
  it('names another key under the same base, and nothing else', () => {
    expect(canSupersede('w1.r1', 'w1')).toBe(true);
    expect(canSupersede('w1', 'w1.r1')).toBe(true);
    expect(canSupersede('w1.r2', 'w1.r1')).toBe(true);
    expect(canSupersede('w1', 'w1')).toBe(false);
    expect(canSupersede('w10', 'w1')).toBe(false);
    expect(canSupersede('w2.r1', 'w1')).toBe(false);
  });

  it("leaves a live key open with its vault, and its owner's next use undoes the supersede", () => {
    const { sessions, clock, destroyed } = table();
    const first = secretOf(sessions.open('w1', undefined));
    secretOf(sessions.open('w1.r1', undefined, 'w1'));
    expect(sessions.size).toBe(2);
    expect(destroyed).toEqual([]);
    expect(sessions.use('w1', first)).not.toBe('not_found');
    clock.t += TTL_MS + 1;
    sessions.sweep();
    expect(sessions.unclosed).toBe(true);
  });

  it('a left key that is never used again is not remembered once it expires', () => {
    const { sessions, clock } = table();
    sessions.open('w1', undefined);
    const moved = secretOf(sessions.open('w1.r1', undefined, 'w1'));
    expect(sessions.close('w1.r1', moved)).toBe('closed');
    clock.t += TTL_MS + 1;
    sessions.sweep();
    expect(sessions.size).toBe(0);
    expect(sessions.unclosed).toBe(false);
  });

  it('counts only when the session is created: a refused open supersedes nothing', () => {
    const { sessions, clock } = table();
    sessions.open('w1', undefined);
    clock.t += TTL_MS / 2;
    sessions.open('w1.r1', undefined);
    // Without its secret: refused, so w1 is not left.
    expect(sessions.open('w1.r1', undefined, 'w1').kind).toBe('conflict');
    // w1 expires first, w1.r1 is still open.
    clock.t += TTL_MS / 2 + 1;
    sessions.sweep();
    expect(sessions.size).toBe(1);
    expect(sessions.unclosed).toBe(true);
  });

  it('a full table supersedes nothing', () => {
    const { sessions, clock } = table(2);
    sessions.open('w1', undefined);
    sessions.open('w1.r1', undefined);
    expect(sessions.open('w1.r2', undefined, 'w1').kind).toBe('full');
    clock.t += TTL_MS + 1;
    sessions.sweep();
    expect(sessions.unclosed).toBe(true);
  });

  it('throws on a key it cannot supersede, and opens nothing', () => {
    const { sessions } = table();
    expect(() => sessions.open('w2.r1', undefined, 'w1')).toThrow(/no other key/);
    expect(() => sessions.open('w1', undefined, 'w1')).toThrow(/no other key/);
    expect(sessions.size).toBe(0);
    expect(sessions.everOpened).toBe(false);
  });
});

describe('SidecarSessions · remembered keys', () => {
  it('past the cap, the table stays unclosed after every remembered key is closed', () => {
    const { sessions, clock } = table(REMEMBERED_MAX + 1);
    const keys = Array.from({ length: REMEMBERED_MAX + 1 }, (_, i) => `k${i}`);
    for (const key of keys) sessions.open(key, undefined);
    clock.t += TTL_MS + 1;
    sessions.sweep();
    // Each caller closes the key its TTL already ended (404 on the route).
    for (const key of keys) expect(sessions.close(key, undefined)).toBe('not_found');
    expect(sessions.unclosed).toBe(true);
  });

  it('under the cap, closing every remembered key releases the table', () => {
    const { sessions, clock } = table(REMEMBERED_MAX);
    const keys = Array.from({ length: REMEMBERED_MAX }, (_, i) => `k${i}`);
    for (const key of keys) sessions.open(key, undefined);
    clock.t += TTL_MS + 1;
    sessions.sweep();
    for (const key of keys) sessions.close(key, undefined);
    expect(sessions.unclosed).toBe(false);
  });
});
