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
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
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

  // If a state file exists, only short-circuit when the recorded
  // pid is *actually* still alive. Otherwise the previous session
  // crashed without firing Stop and a stale file would block every
  // future SessionStart from spawning a fresh daemon.
  if (existsSync(state)) {
    let staleReason = 'unreadable';
    try {
      const info = JSON.parse(readFileSync(state, 'utf8'));
      const pid = typeof info.pid === 'number' ? info.pid : -1;
      const sock = typeof info.socket === 'string' ? info.socket : '';
      if (pid > 0) {
        try {
          process.kill(pid, 0);
          if (sock !== '' && existsSync(sock)) {
            process.stderr.write(`[nullpii] daemon already alive (pid=${pid})\n`);
            process.stdout.write('\n');
            return;
          }
          staleReason = `socket missing for pid=${pid}`;
        } catch {
          staleReason = `pid=${pid} dead`;
        }
      } else {
        staleReason = 'no pid in state';
      }
    } catch (err) {
      staleReason = `parse error: ${err.message}`;
    }
    process.stderr.write(`[nullpii] removing stale state file (${staleReason})\n`);
    try {
      unlinkSync(state);
    } catch {}
  }

  // Claude Code passes its own pid as PPID to the hook. Forward it so
  // the daemon can self-terminate if Claude Code crashes without
  // running the Stop hook (no workaround for direct exit).
  const parentPid = String(process.ppid);
  const idleMs = '1800000'; // 30 min idle = self-shutdown safety net
  const httpProxyPort = process.env.NULLPII_PROXY_PORT ?? '7330';

  const bin = locateBinary();
  const baseArgs = [
    'serve',
    '--socket',
    socket,
    '--parent-pid',
    parentPid,
    '--idle-timeout-ms',
    idleMs,
    '--http-proxy',
    httpProxyPort,
  ];
  const argv = bin.kind === 'mjs' ? ['node', bin.path, ...baseArgs] : ['nullpii', ...baseArgs];

  const child = spawn(argv[0], argv.slice(1), {
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore'],
    env: { ...process.env },
  });
  child.unref();

  writeFileSync(
    state,
    JSON.stringify({ pid: child.pid, socket, sessionId, parentPid, httpProxyPort }),
  );
  process.stderr.write(
    `[nullpii] daemon spawned pid=${child.pid} parent=${parentPid} socket=${socket} proxy=:${httpProxyPort}\n`,
  );

  // Surface a heads-up so the user knows what to do to actually wire
  // the proxy into Claude Code's outgoing API calls.
  const expected = `http://localhost:${httpProxyPort}`;
  if (process.env.ANTHROPIC_BASE_URL !== expected) {
    process.stderr.write(
      `[nullpii] note: ANTHROPIC_BASE_URL is "${process.env.ANTHROPIC_BASE_URL ?? '<unset>'}". ` +
        `Set it to "${expected}" before launching Claude Code to route prompts through the sanitizing proxy.\n`,
    );
  }
  // Empty stdout — Claude Code does not require output for SessionStart.
  process.stdout.write('\n');
}

main().catch((err) => {
  process.stderr.write(`[nullpii] session-start crashed: ${err.message ?? err}\n`);
  process.stdout.write('\n');
});
