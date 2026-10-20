#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Runs a built dist/ over exported texts and records every final span.
//
// Two uses:
//   - Threshold screening: pass --threshold to run below the default and
//     keep span scores (--out spans.jsonl). A simulated cut is an
//     approximation, because a lower threshold also changes what dedupe
//     keeps; decisions come from a confirmation run (METHOD.md).
//   - Candidate evaluation without bench_full: --checkpoints <dir> --tool
//     <name> writes bench_full-format checkpoints (<tool>-<dataset>.jsonl)
//     for char_metrics.py, from any dist directory. A candidate can then
//     be measured while another run holds the worktree's dist/.
//
//   node score_capture.mjs --dist <abs dist> --texts <texts.jsonl> [--threshold 0.2] --out <spans.jsonl>
//   node score_capture.mjs --dist <abs dist> --texts <texts.jsonl> --checkpoints <dir> --tool <name>
//   add --model-dir <dir> to load a model other than the cached default (e.g. a quantized variant)
//   add --config '<json>' to merge engine options, e.g. '{"disabledCategories":[...]}'
//   add --resume 1 to continue an interrupted run: rows already written are
//   skipped and new ones appended (a torn last line is cut off first)
//
// Offsets are written as code points, the way Python indexes strings, so
// they line up with the gold spans. Captures made before 2026-10-18 09:30
// wrote UTF-16 offsets; `utf16_offsets.py` converts them.

import {
  createReadStream,
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  truncateSync,
} from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, '')] = argv[i + 1];
  for (const k of ['dist', 'texts']) {
    if (!args[k]) throw new Error(`--${k} is required`);
  }
  if (!args.out && !(args.checkpoints && args.tool)) {
    throw new Error('pass --out <file>, or --checkpoints <dir> with --tool <name>');
  }
  return args;
}

/** Keys an interrupted run already wrote to `path`. A torn last line (the
 * process died mid-write) is truncated away so appends stay valid JSONL. */
function completedKeys(path, dataset) {
  const keys = new Set();
  if (!existsSync(path)) return keys;
  const text = readFileSync(path, 'utf8');
  const kept = text.slice(0, text.lastIndexOf('\n') + 1);
  if (kept.length < text.length) truncateSync(path, Buffer.byteLength(kept));
  for (const line of kept.split('\n')) {
    if (line === '') continue;
    const row = JSON.parse(line);
    keys.add(`${row.dataset ?? dataset}:${row.idx}`);
  }
  return keys;
}

/** Lines of a JSONL file, split on '\n' only. readline also ends a line at
 * U+2028 and U+2029, which JSON leaves unescaped inside strings, and would
 * cut a row holding one in two. */
async function* jsonlLines(path) {
  let rest = '';
  for await (const chunk of createReadStream(path, { encoding: 'utf8' })) {
    const lines = (rest + chunk).split('\n');
    rest = lines.pop();
    yield* lines;
  }
  yield rest;
}

/** Maps a UTF-16 offset of `text` to its code-point offset. Span offsets
 * from the runtime index UTF-16 code units, as JavaScript strings do, but
 * the scorers and the gold spans are Python, which indexes code points:
 * without this, every span after an emoji or other astral character lands
 * one position early per such character. */
function codePointOffsets(text) {
  const map = new Uint32Array(text.length + 1);
  let cp = 0;
  for (let i = 0; i < text.length; i++) {
    map[i] = cp;
    const unit = text.charCodeAt(i);
    const next = text.charCodeAt(i + 1);
    if (unit >= 0xd800 && unit <= 0xdbff && next >= 0xdc00 && next <= 0xdfff) {
      i += 1;
      map[i] = cp;
    }
    cp += 1;
  }
  map[text.length] = cp;
  return (offset) => map[offset];
}

function checkpointSink(dir, tool, resume) {
  mkdirSync(dir, { recursive: true });
  const streams = new Map();
  const done = new Map();
  const pathOf = (dataset) => join(dir, `${tool}-${dataset}.jsonl`);
  return {
    isDone(row) {
      if (!resume) return false;
      if (!done.has(row.dataset)) done.set(row.dataset, completedKeys(pathOf(row.dataset), row.dataset));
      return done.get(row.dataset).has(`${row.dataset}:${row.idx}`);
    },
    write(row, spans) {
      if (!streams.has(row.dataset)) {
        streams.set(row.dataset, createWriteStream(pathOf(row.dataset), { flags: resume ? 'a' : 'w' }));
      }
      const triples = spans.map(([s, e, label]) => [s, e, label]);
      streams.get(row.dataset).write(`${JSON.stringify({ idx: row.idx, spans: triples })}\n`);
    },
    end() {
      for (const s of streams.values()) s.end();
    },
  };
}

function spanSink(path, resume) {
  const done = resume ? completedKeys(path, undefined) : new Set();
  const out = createWriteStream(path, { flags: resume ? 'a' : 'w' });
  return {
    isDone(row) {
      return done.has(`${row.dataset}:${row.idx}`);
    },
    write(row, spans) {
      out.write(`${JSON.stringify({ dataset: row.dataset, idx: row.idx, spans })}\n`);
    },
    end() {
      out.end();
    },
  };
}

const args = parseArgs(process.argv.slice(2));
const { NullPii } = await import(pathToFileURL(join(args.dist, 'index.js')).href);
const config = {
  backend: 'cpu',
  ...(args.threshold !== undefined && { threshold: Number(args.threshold) }),
  ...(args['model-dir'] !== undefined && { modelDir: args['model-dir'] }),
  ...(args.config !== undefined && JSON.parse(args.config)),
};
const np = new NullPii(config);
const resume = args.resume === '1';
const sink = args.out ? spanSink(args.out, resume) : checkpointSink(args.checkpoints, args.tool, resume);
let n = 0;
let skipped = 0;
for await (const line of jsonlLines(args.texts)) {
  if (line.trim() === '') continue;
  const row = JSON.parse(line);
  if (sink.isDone(row)) {
    skipped += 1;
    continue;
  }
  const r = await np.sanitize(row.text);
  np.destroySession(r.sessionId);
  const cp = codePointOffsets(row.text);
  sink.write(row, r.spans.map((s) => [cp(s.start), cp(s.end), s.label, s.score]));
  n += 1;
}
sink.end();
await np.dispose();
process.stdout.write(`${JSON.stringify({ docs: n, skipped, ...config })}\n`);
