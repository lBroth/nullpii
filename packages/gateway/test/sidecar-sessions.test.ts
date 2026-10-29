// SPDX-License-Identifier: Apache-2.0
//
// SidecarSessions on its own: what a supersede does to the other keys
// under a base, with a counting stand-in for the engine's vault.

import type { NullPii } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { SidecarSessions, isUnderBase } from '../src/sidecar-sessions.js';

const TTL_MS = 1_000;

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
  it('names a key and the keys under it, and nothing else', () => {
    expect(isUnderBase('w1', 'w1')).toBe(true);
    expect(isUnderBase('w1.r1', 'w1')).toBe(true);
    expect(isUnderBase('w1.r1.r2', 'w1')).toBe(true);
    expect(isUnderBase('w10', 'w1')).toBe(false);
    expect(isUnderBase('w2.r1', 'w1')).toBe(false);
    expect(isUnderBase('w1', 'w1.r1')).toBe(false);
  });

  it("leaves a live key open with its vault, and its owner's next use undoes the supersede", () => {
    const { sessions, clock, destroyed } = table();
    const first = secretOf(sessions.open('w1', undefined));
    secretOf(sessions.open('w1.r1', undefined, 'w1'));
    expect(sessions.size).toBe(2);
    expect(destroyed).toEqual([]);
    expect(sessions.use('w1', first)).not.toBe('not_found');
    // That use proved the owner of w1 is here: the supersede no longer holds.
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

  it('throws on a base the key is not under, and opens nothing', () => {
    const { sessions } = table();
    expect(() => sessions.open('w2.r1', undefined, 'w1')).toThrow(/not under/);
    expect(sessions.size).toBe(0);
    expect(sessions.everOpened).toBe(false);
  });
});
