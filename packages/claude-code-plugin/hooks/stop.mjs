#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Stop hook: SIGTERM the per-session nullpii daemon, unlink its
// state + socket. Idempotent — safe if no daemon was started.

import { existsSync, readFileSync, unlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.on('data', (c) => {
      data += c;
    });
    process.stdin.on('end', () => resolve(data));
  });
}

function statePath(sessionId) {
  return join(homedir(), '.cache', 'nullpii', 'plugin', `daemon-${sessionId}.json`);
}

async function main() {
  const raw = await readStdin();
  let payload = {};
  try {
    payload = JSON.parse(raw);
  } catch {}
  const sessionId = payload.session_id ?? payload.sessionId ?? `default-${process.pid}`;
  const state = statePath(sessionId);

  if (!existsSync(state)) {
    process.stdout.write('\n');
    return;
  }

  let info;
  try {
    info = JSON.parse(readFileSync(state, 'utf8'));
  } catch (err) {
    process.stderr.write(`[nullpii] stop: bad state file: ${err.message}\n`);
    process.stdout.write('\n');
    return;
  }

  if (typeof info.pid === 'number') {
    try {
      process.kill(info.pid, 'SIGTERM');
      process.stderr.write(`[nullpii] daemon pid=${info.pid} terminated\n`);
    } catch (err) {
      process.stderr.write(`[nullpii] could not signal pid=${info.pid}: ${err.message}\n`);
    }
  }

  for (const path of [info.socket, state]) {
    if (typeof path === 'string') {
      try {
        unlinkSync(path);
      } catch {
        // already gone
      }
    }
  }
  process.stdout.write('\n');
}

main().catch((err) => {
  process.stderr.write(`[nullpii] stop crashed: ${err.message ?? err}\n`);
  process.stdout.write('\n');
});
