#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Refuses changes that would publish something this open-source repo must
// never carry: private research notes, benchmark outputs, model weights,
// key material, env files, oversized blobs, a developer's home path, or a
// private package registry. Secrets themselves are gitleaks' job
// (`.gitleaks.toml`); this covers what a secret scanner does not see.
//
//   node scripts/check-repo-hygiene.mjs            # staged files (pre-commit)
//   node scripts/check-repo-hygiene.mjs <base>     # files changed since <base> (CI)
//   node scripts/check-repo-hygiene.mjs --all      # every tracked file
//
// Prints the file and the rule broken, never the offending text.

import { execFileSync } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';

const MAX_FILE_BYTES = 5 * 1024 * 1024;

/** Tracked on purpose despite their size; extend only in review. */
const LARGE_FILE_ALLOWLIST = new Set(['assets/claude-code-demo.m4v']);

const FORBIDDEN_PATHS = [
  { rule: 'private research notes', re: /^packages\/eval\/private\// },
  { rule: 'benchmark or training outputs', re: /^packages\/eval\/results\// },
  { rule: 'model weights', re: /\.(onnx|onnx_data|safetensors|pt|pth|ckpt|gguf|bin)$/i },
  { rule: 'key material', re: /(\.(pem|p12|pfx|key)$)|(^|\/)id_(rsa|ecdsa|ed25519)(\.pub)?$/i },
  { rule: 'env file', re: /(^|\/)\.env(\.(?!example$)[^/]+)?$/ },
];

const FORBIDDEN_CONTENT = [
  {
    rule: 'absolute home path',
    re: /\/Users\/[A-Za-z0-9._-]+\/|\/home\/[A-Za-z0-9._-]+\/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\/,
  },
  {
    rule: 'private package registry',
    re: /\.codeartifact\.[a-z0-9-]+\.amazonaws\.com|\.jfrog\.io\/|pkgs\.dev\.azure\.com/,
  },
  { rule: 'registry auth token', re: /^\s*(\/\/\S+:)?_auth(Token)?\s*=/m },
];

/** Home paths that name no developer: placeholders that docs and tests may
 * show, and `/home/runner/`, the fixed home of GitHub-hosted CI runners. */
const HOME_PATH_EXAMPLES =
  /\/(Users|home)\/(you|user|username|me|name|example|alice|bob)\/|\/home\/runner\//;

function changedFiles(base) {
  if (base === '--all') {
    return execFileSync('git', ['ls-files'], { encoding: 'utf8' }).split('\n').filter(Boolean);
  }
  const args = base
    ? ['diff', '--name-only', '--diff-filter=ACMR', `${base}...HEAD`]
    : ['diff', '--cached', '--name-only', '--diff-filter=ACMR'];
  return execFileSync('git', args, { encoding: 'utf8' }).split('\n').filter(Boolean);
}

function isBinary(buf) {
  return buf.subarray(0, 8000).includes(0);
}

function checkFile(file) {
  const problems = FORBIDDEN_PATHS.filter((p) => p.re.test(file)).map((p) => p.rule);
  const size = statSync(file).size;
  if (size > MAX_FILE_BYTES && !LARGE_FILE_ALLOWLIST.has(file)) {
    problems.push(`file over ${MAX_FILE_BYTES / 1024 / 1024} MB`);
  }
  const buf = readFileSync(file);
  if (isBinary(buf)) return problems;
  const text = buf.toString('utf8').replace(new RegExp(HOME_PATH_EXAMPLES.source, 'g'), '');
  for (const c of FORBIDDEN_CONTENT) {
    if (c.re.test(text)) problems.push(c.rule);
  }
  return problems;
}

function main() {
  const base = process.argv[2];
  const failures = [];
  for (const file of changedFiles(base)) {
    for (const rule of checkFile(file)) failures.push(`${file}: ${rule}`);
  }
  if (failures.length > 0) {
    process.stderr.write(
      `repo hygiene: ${failures.length} problem(s)\n${failures.map((f) => `  ${f}`).join('\n')}\n`,
    );
    process.stderr.write('See CONTRIBUTING.md, "What never goes in the repo".\n');
    process.exit(1);
  }
}

main();
