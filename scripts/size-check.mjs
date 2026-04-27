#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Simple file-size budget. Fails CI if any file under `dist/` (excluding
// declarations and source maps) exceeds its budget. Adjust BUDGETS_KB as
// the public surface evolves.

import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const BUDGETS_KB = {
  'dist/index.js': 30,
  'dist/middleware/anthropic.js': 15,
  'dist/backend/cpu-backend.js': 5,
  'dist/backend/ort-backend.js': 10,
  'dist/nullpii.js': 20,
};

let failed = false;
for (const [path, kb] of Object.entries(BUDGETS_KB)) {
  try {
    const sizeKb = Math.round(statSync(path).size / 1024);
    const ok = sizeKb <= kb;
    process.stdout.write(`${ok ? 'OK   ' : 'FAIL '}${path.padEnd(40)} ${sizeKb} kB / ${kb} kB\n`);
    if (!ok) failed = true;
  } catch {
    process.stdout.write(`SKIP ${path.padEnd(40)} (not built)\n`);
  }
}

// Total dist size hint
let total = 0;
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const s = statSync(full);
    if (s.isDirectory()) walk(full);
    else if (entry.endsWith('.js')) total += s.size;
  }
}
try {
  walk('dist');
  process.stdout.write(`---\nTOTAL .js  ${(total / 1024).toFixed(1)} kB\n`);
} catch {}

if (failed) process.exit(1);
