#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Update the persistent nullpii daemon config (variant / backend)
// then kill+respawn so the new model loads. Used by the /nullpii
// slash command.
//
// Usage: pass `--variant <v>` and/or `--backend <b>` as argv.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const VALID_VARIANTS = new Set(['fp32', 'fp16', 'int8', 'int4', 'int4f16', 'auto']);
const VALID_BACKENDS = new Set(['cpu', 'mps', 'cuda', 'rocm', 'auto']);

function configPath() {
  const dir = join(homedir(), '.cache', 'nullpii', 'plugin');
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  return join(dir, 'config.json');
}

function loadConfig() {
  const p = configPath();
  if (!existsSync(p)) return { variant: 'auto', backend: 'auto' };
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return { variant: 'auto', backend: 'auto' };
  }
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--variant' && typeof v === 'string') out.variant = v;
    else if (k === '--backend' && typeof v === 'string') out.backend = v;
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (args.variant !== undefined && !VALID_VARIANTS.has(args.variant)) {
  process.stderr.write(`[nullpii] invalid variant: ${args.variant}\n`);
  process.stderr.write(`valid: ${[...VALID_VARIANTS].join(', ')}\n`);
  process.exit(2);
}
if (args.backend !== undefined && !VALID_BACKENDS.has(args.backend)) {
  process.stderr.write(`[nullpii] invalid backend: ${args.backend}\n`);
  process.stderr.write(`valid: ${[...VALID_BACKENDS].join(', ')}\n`);
  process.exit(2);
}

const cfg = { ...loadConfig(), ...args };
writeFileSync(configPath(), JSON.stringify(cfg, null, 2));
process.stderr.write(
  `[nullpii] config saved variant=${cfg.variant} backend=${cfg.backend}\n[nullpii] now run: pkill -f "nullpii.*serve"; node "\${CLAUDE_PLUGIN_ROOT}/hooks/session-start.mjs" <<< "{}"\n`,
);
process.stdout.write(`${JSON.stringify(cfg)}\n`);
