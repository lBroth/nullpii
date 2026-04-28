#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// UserPromptSubmit hook: talk to the per-session `nullpii serve`
// daemon over a Unix socket. The daemon was spawned by the
// SessionStart hook so the model is already loaded.
//
// On any error: forward the original prompt unchanged. PII leakage
// is bad; blocking the user is worse.

import { existsSync, readFileSync } from 'node:fs';
import { connect } from 'node:net';
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

function writeOutput(obj) {
  process.stdout.write(JSON.stringify(obj));
  process.stdout.write('\n');
}

function passthrough(prompt, reason) {
  if (reason !== undefined) {
    process.stderr.write(`[nullpii] passthrough: ${reason}\n`);
  }
  writeOutput({ continue: true, prompt });
}

function statePath(sessionId) {
  return join(homedir(), '.cache', 'nullpii', 'plugin', `daemon-${sessionId}.json`);
}

function readDaemonState(sessionId) {
  const state = statePath(sessionId);
  if (!existsSync(state)) return null;
  try {
    const info = JSON.parse(readFileSync(state, 'utf8'));
    if (typeof info.socket === 'string' && existsSync(info.socket)) {
      return info;
    }
  } catch {}
  return null;
}

function sanitizeViaDaemon(socketPath, prompt, sessionId) {
  return new Promise((resolve) => {
    const client = connect(socketPath);
    let buffer = '';
    let settled = false;
    const settle = (value) => {
      if (settled) return;
      settled = true;
      try {
        client.end();
      } catch {}
      resolve(value);
    };
    const timer = setTimeout(() => {
      settle({ ok: false, reason: 'daemon timeout (30s)' });
    }, 30_000);
    client.setEncoding('utf8');
    client.on('connect', () => {
      const req = JSON.stringify({ id: 1, text: prompt, sessionId });
      client.write(`${req}\n`);
    });
    client.on('data', (chunk) => {
      buffer += chunk;
      const nl = buffer.indexOf('\n');
      if (nl < 0) return;
      const line = buffer.slice(0, nl).trim();
      try {
        const resp = JSON.parse(line);
        clearTimeout(timer);
        if (resp.error !== undefined && resp.error !== null) {
          settle({ ok: false, reason: `daemon error: ${resp.error}` });
        } else {
          settle({
            ok: true,
            sanitized: resp.sanitized,
            sessionId: resp.sessionId,
            spans: resp.spans ?? [],
          });
        }
      } catch (err) {
        clearTimeout(timer);
        settle({ ok: false, reason: `parse failed: ${err.message}` });
      }
    });
    client.on('error', (err) => {
      clearTimeout(timer);
      settle({ ok: false, reason: `socket error: ${err.message}` });
    });
  });
}

async function main() {
  const raw = await readStdin();
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (err) {
    writeOutput({ continue: true });
    process.stderr.write(`[nullpii] bad stdin JSON: ${err.message}\n`);
    return;
  }

  const prompt = typeof payload.prompt === 'string' ? payload.prompt : '';
  if (prompt === '') {
    writeOutput({ continue: true });
    return;
  }

  const sessionId = payload.session_id ?? payload.sessionId ?? `default-${process.pid}`;
  const daemon = readDaemonState(sessionId);
  if (daemon === null) {
    passthrough(
      prompt,
      `no daemon registered for session ${sessionId} — SessionStart hook may have failed`,
    );
    return;
  }

  const result = await sanitizeViaDaemon(daemon.socket, prompt, sessionId);
  if (!result.ok) {
    passthrough(prompt, result.reason);
    return;
  }

  const spanCount = Array.isArray(result.spans) ? result.spans.length : 0;
  if (spanCount === 0 || typeof result.sanitized !== 'string') {
    writeOutput({ continue: true });
    return;
  }

  // Claude Code's UserPromptSubmit hook cannot rewrite the outgoing
  // prompt — it can only add context (additionalContext) or block
  // (decision: 'block'). The 'prompt' field is silently ignored.
  // To actually prevent PII leakage we must BLOCK the original prompt
  // and surface the sanitized version in the rejection reason. The
  // user copies it and resends. Better UX (network proxy / MCP server)
  // tracked on the roadmap.
  writeOutput({
    decision: 'block',
    reason: [
      `[nullpii] blocked: ${spanCount} PII span(s) detected in your prompt.`,
      '',
      'Your prompt has not been sent to Claude. Sanitized version below — copy + resend if intended:',
      '',
      result.sanitized,
    ].join('\n'),
  });
}

main().catch((err) => {
  process.stderr.write(`[nullpii] hook crashed: ${err.message ?? err}\n`);
  writeOutput({ continue: true });
});
