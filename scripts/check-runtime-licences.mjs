#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Licence check of everything that ships at runtime: the core's
// dependencies, plus the gateway's fastify and the onnxruntime-node peer
// (the gateway image installs both). `npm run license-check` sees only the
// core's production tree, where fastify and onnxruntime-node are dev and
// peer dependencies, so this walks package-lock.json from those roots
// instead. Every package must carry an allowed licence (CLAUDE.md); an SPDX
// `OR` expression passes when one of its terms is allowed.
//
// The gateway image also ships onnxruntime's licence and third-party
// notices, which onnxruntime-node's npm package lacks, from
// packages/gateway/third_party/onnxruntime/ (copied from the onnxruntime
// release tag of ORT_NOTICES_VERSION). The check fails when the locked
// onnxruntime-node moves to another version, so the notices move with it.

import { existsSync, readFileSync } from 'node:fs';

const ALLOWED = new Set(['MIT', 'ISC', 'BSD-2-Clause', 'BSD-3-Clause', 'Apache-2.0', 'CC0-1.0']);
const EXTRA_ROOTS = ['fastify', 'onnxruntime-node'];
const ORT_NOTICES_DIR = 'packages/gateway/third_party/onnxruntime';
const ORT_NOTICES_FILES = ['LICENSE', 'ThirdPartyNotices.txt'];
const ORT_NOTICES_VERSION = '1.30.0';

const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const pkgs = lock.packages;
const rootDeps = Object.keys(pkgs[''].dependencies ?? {});

/** What is wrong with the onnxruntime notices the gateway image ships. */
function ortNoticeProblems() {
  const problems = ORT_NOTICES_FILES.filter((f) => !existsSync(`${ORT_NOTICES_DIR}/${f}`)).map(
    (f) => `${ORT_NOTICES_DIR}/${f} is missing`,
  );
  const locked = pkgs['node_modules/onnxruntime-node']?.version;
  if (locked !== ORT_NOTICES_VERSION) {
    problems.push(
      [
        `onnxruntime-node is locked at ${locked}, but ${ORT_NOTICES_DIR}`,
        `holds the notices of ${ORT_NOTICES_VERSION}: copy LICENSE and ThirdPartyNotices.txt`,
        `from https://github.com/microsoft/onnxruntime at tag v${locked}, then update`,
        'ORT_NOTICES_VERSION here and the tag named in packages/gateway/Dockerfile',
      ].join(' '),
    );
  }
  return problems;
}

const noticeProblems = ortNoticeProblems();
if (noticeProblems.length > 0) {
  process.stderr.write(`runtime licences: ${noticeProblems.join('\n  ')}\n`);
  process.exit(1);
}

/** The lockfile path a dependency named `name` resolves to from the
 * package at `from`, the way Node resolves it: nearest `node_modules`
 * first, then each enclosing one up to the top level. */
function resolve(from, name) {
  for (let base = from; ; ) {
    const candidate = `${base}/node_modules/${name}`;
    if (pkgs[candidate] !== undefined) return candidate;
    const up = base.lastIndexOf('/node_modules/');
    if (up < 0) break;
    base = base.slice(0, up);
  }
  const top = `node_modules/${name}`;
  return pkgs[top] !== undefined ? top : undefined;
}

function allowed(licence) {
  if (typeof licence !== 'string') return false;
  return licence
    .replace(/[()]/g, '')
    .split(/\s+OR\s+/)
    .some((term) => ALLOWED.has(term.trim()));
}

const seen = new Set();
const queue = [...rootDeps, ...EXTRA_ROOTS].map((n) => `node_modules/${n}`);
const bad = [];
while (queue.length > 0) {
  const path = queue.shift();
  if (seen.has(path)) continue;
  seen.add(path);
  const pkg = pkgs[path];
  if (pkg === undefined) throw new Error(`package-lock.json has no entry for ${path}`);
  if (!allowed(pkg.license))
    bad.push(`${path.replace(/^.*node_modules\//, '')}@${pkg.version}: ${pkg.license ?? 'none'}`);
  for (const dep of Object.keys({ ...pkg.dependencies, ...pkg.optionalDependencies })) {
    const next = resolve(path, dep);
    if (next !== undefined) queue.push(next);
    else if (!(pkg.optionalDependencies && dep in pkg.optionalDependencies)) {
      throw new Error(`cannot resolve ${dep} required by ${path}`);
    }
  }
}
if (bad.length > 0) {
  process.stderr.write(`runtime licences: ${bad.length} not allowed\n  ${bad.join('\n  ')}\n`);
  process.exit(1);
}
process.stdout.write(`runtime licences: ${seen.size} packages, all allowed\n`);
