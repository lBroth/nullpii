#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Claude Code UserPromptSubmit hook for @nullpii/claude-code.
//
// Contract:
//  - stdin: JSON `{ prompt: string, session_id?: string, ... }`
//  - stdout: JSON `{ continue: true, prompt: <sanitized>, ... }`
//
// Loads `nullpii` in-process. First call cold-loads the ONNX model
// (3 GB fp16 default) — slow. Subsequent calls re-cold-load because
// Claude Code spawns a fresh process per hook. A daemon mode that
// keeps the model resident across calls is on the roadmap.
//
// On any error, the hook MUST forward the original prompt unchanged
// rather than blocking the user. PII leakage is a privacy regression;
// blocking the user is a UX regression. We log to stderr (visible
// in Claude Code debug output) and let the prompt through.

import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const claudeDir = process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude');
const sessionVaultPath = join(claudeDir, '.nullpii-session-vault.json');

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

  let nullpii;
  try {
    nullpii = await import('nullpii');
  } catch (err) {
    passthrough(prompt, `nullpii not installed: ${err.message}`);
    return;
  }

  let pluginConfig = {};
  try {
    const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT;
    if (pluginRoot !== undefined) {
      const mod = await import(`file://${pluginRoot}/dist/config.js`);
      pluginConfig = mod.toNullPiiConfig({});
    }
  } catch (err) {
    process.stderr.write(`[nullpii] config import failed (using defaults): ${err.message}\n`);
  }

  try {
    const np = new nullpii.NullPii(pluginConfig);
    const result = await np.sanitize(prompt);
    if (result.spans.length === 0) {
      writeOutput({ continue: true });
      return;
    }
    // Persist session id keyed by session_id so a future PostMessage
    // hook can restore. Best-effort write — restore is not yet wired.
    try {
      const sessionId = payload.session_id ?? '_default';
      const vault = JSON.parse(readFileSync(sessionVaultPath, 'utf8'));
      vault[sessionId] = result.sessionId;
      // No write helper here — restore wiring lands with PostResponse hook.
      void vault;
    } catch {
      // file missing or unreadable — fine, restore not wired yet
    }
    writeOutput({
      continue: true,
      prompt: result.sanitized,
      hookSpecificOutput: {
        hookEventName: 'UserPromptSubmit',
        additionalContext: `[nullpii] redacted ${result.spans.length} PII span(s) before send.`,
      },
    });
  } catch (err) {
    passthrough(prompt, `sanitize failed: ${err.message ?? err}`);
  }
}

main().catch((err) => {
  process.stderr.write(`[nullpii] hook crashed: ${err.message ?? err}\n`);
  // Last resort — emit empty continue so we don't block the user
  writeOutput({ continue: true });
});
