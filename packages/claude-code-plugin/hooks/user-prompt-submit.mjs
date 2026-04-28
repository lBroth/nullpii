#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Claude Code UserPromptSubmit hook for @nullpii/claude-code.
//
// Contract:
//  - stdin: JSON `{ prompt: string, session_id?: string, ... }`
//  - stdout: JSON `{ continue: true, prompt: <sanitized>, ... }`
//
// We spawn the `nullpii` CLI as a subprocess instead of importing the
// `nullpii` module. Reason: when Claude Code copies the plugin into
// its cache (e.g. `~/.claude/plugins/cache/<plugin>/`), no
// `node_modules/` is shipped along. The CLI binary, however, lives in
// the user-installed `nullpii` package on PATH (or beside the plugin
// during local-marketplace installs) and carries its own resolved
// deps.
//
// Resolution order for the binary:
//   1. `nullpii` on PATH (post-publish, after `npm i -g @nullpii/claude-code`)
//   2. `${CLAUDE_PLUGIN_ROOT}/../../bin/nullpii.mjs` (local marketplace)
//   3. fallthrough → passthrough with stderr warning, never block.
//
// On any error: forward the original prompt unchanged. PII leaking
// is bad; blocking the user is worse.

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
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

function locateBinary() {
  const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT;
  // 1. Local-marketplace install: plugin copied alongside the source repo
  //    (or hooks/ sits two levels under the repo root).
  const candidates = [];
  if (pluginRoot !== undefined) {
    candidates.push(join(pluginRoot, '..', '..', 'bin', 'nullpii.mjs'));
  }
  // 2. Same-repo dev: hooks/../../../../bin/nullpii.mjs (this file path)
  candidates.push(join(__dirname, '..', '..', '..', 'bin', 'nullpii.mjs'));
  for (const p of candidates) {
    if (existsSync(p)) return { kind: 'mjs', path: p };
  }
  // 3. PATH lookup will be tried by spawn('nullpii', ...) directly.
  return { kind: 'path', path: 'nullpii' };
}

function runSanitize(prompt) {
  return new Promise((resolve) => {
    const bin = locateBinary();
    const argv = bin.kind === 'mjs'
      ? ['node', bin.path, 'sanitize', '--stdin', '--format', 'json']
      : ['nullpii', 'sanitize', '--stdin', '--format', 'json'];
    const child = spawn(argv[0], argv.slice(1), { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (c) => {
      stdout += c;
    });
    child.stderr.on('data', (c) => {
      stderr += c;
    });
    child.on('error', (err) => {
      resolve({ ok: false, reason: `spawn failed: ${err.message}`, stderr });
    });
    child.on('exit', (code) => {
      if (code !== 0) {
        resolve({ ok: false, reason: `nullpii exit ${code}`, stderr });
        return;
      }
      try {
        const parsed = JSON.parse(stdout);
        resolve({ ok: true, sanitized: parsed.sanitized, spans: parsed.spans, sessionId: parsed.sessionId, stderr });
      } catch (err) {
        resolve({ ok: false, reason: `parse stdout failed: ${err.message}`, stderr });
      }
    });
    child.stdin.end(prompt);
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

  const result = await runSanitize(prompt);
  if (!result.ok) {
    if (result.stderr !== undefined && result.stderr !== '') {
      process.stderr.write(`[nullpii] subprocess stderr: ${result.stderr}\n`);
    }
    passthrough(prompt, result.reason);
    return;
  }

  const spanCount = Array.isArray(result.spans) ? result.spans.length : 0;
  if (spanCount === 0 || typeof result.sanitized !== 'string') {
    writeOutput({ continue: true });
    return;
  }
  writeOutput({
    continue: true,
    prompt: result.sanitized,
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: `[nullpii] redacted ${spanCount} PII span(s) before send.`,
    },
  });
}

main().catch((err) => {
  process.stderr.write(`[nullpii] hook crashed: ${err.message ?? err}\n`);
  writeOutput({ continue: true });
});
