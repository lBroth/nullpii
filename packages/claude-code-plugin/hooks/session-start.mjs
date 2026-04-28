#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// SessionStart hook: spawn `nullpii serve --socket <path>` as a
// background daemon so the model loads ONCE per session. The next
// UserPromptSubmit hook talks to the daemon via the Unix socket.
//
// Lifecycle:
//   SessionStart → spawn daemon, write {pid, socket} to state file
//   UserPromptSubmit → read state, connect to socket, sanitize
//   Stop → SIGTERM the daemon, unlink socket + state

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function readStdin() {
  return new Promise((resolve) => {
    let data = '';
    process.stdin.on('data', (c) => {
      data += c;
    });
    process.stdin.on('end', () => resolve(data));
  });
}

function locateBinary() {
  const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT;
  const candidates = [];
  if (pluginRoot !== undefined) {
    candidates.push(join(pluginRoot, '..', '..', 'bin', 'nullpii.mjs'));
  }
  candidates.push(join(__dirname, '..', '..', '..', 'bin', 'nullpii.mjs'));
  for (const p of candidates) {
    if (existsSync(p)) return { kind: 'mjs', path: p };
  }
  return { kind: 'path', path: 'nullpii' };
}

function statePath(sessionId) {
  const dir = join(homedir(), '.cache', 'nullpii', 'plugin');
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  return join(dir, `daemon-${sessionId}.json`);
}

function socketPathFor(sessionId) {
  return join(tmpdir(), `nullpii-${sessionId}.sock`);
}

async function main() {
  const raw = await readStdin();
  let payload = {};
  try {
    payload = JSON.parse(raw);
  } catch {
    // SessionStart may receive empty stdin; that's fine.
  }
  const sessionId = payload.session_id ?? payload.sessionId ?? `default-${process.pid}`;
  const socket = socketPathFor(sessionId);
  const state = statePath(sessionId);

  // If a daemon is already alive for this session, do nothing.
  if (existsSync(state)) {
    process.stderr.write(`[nullpii] daemon already registered for ${sessionId}\n`);
    process.stdout.write('\n');
    return;
  }

  const bin = locateBinary();
  const argv =
    bin.kind === 'mjs'
      ? ['node', bin.path, 'serve', '--socket', socket]
      : ['nullpii', 'serve', '--socket', socket];

  const child = spawn(argv[0], argv.slice(1), {
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore'],
    env: { ...process.env },
  });
  child.unref();

  writeFileSync(state, JSON.stringify({ pid: child.pid, socket, sessionId }));
  process.stderr.write(`[nullpii] daemon spawned pid=${child.pid} socket=${socket}\n`);
  // Empty stdout — Claude Code does not require output for SessionStart.
  process.stdout.write('\n');
}

main().catch((err) => {
  process.stderr.write(`[nullpii] session-start crashed: ${err.message ?? err}\n`);
  process.stdout.write('\n');
});
