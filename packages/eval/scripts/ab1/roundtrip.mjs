// SPDX-License-Identifier: Apache-2.0
// AB-1 (SPEC.md, "Metrics"): nullpii only, restore(mask(x)) == x on every document.
// Prints counts and failing document indices only, never text.
//
//   node roundtrip.mjs --dist <abs dist> --texts <texts.jsonl> [--model-dir D] [--config '<json>']
import { createReadStream } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith('--')) throw new Error(`unexpected argument ${argv[i]}`);
    out[argv[i].slice(2)] = argv[i + 1];
  }
  for (const k of ['dist', 'texts']) if (!out[k]) throw new Error(`--${k} is required`);
  return out;
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

/** A JSONL row, parsed; a line that is not JSON is reported by its number
 * alone, never with its text (the frozen inputs hold real secrets, and
 * JSON.parse's own message quotes the input). */
function parseRow(line, number, file) {
  try {
    return JSON.parse(line);
  } catch {
    throw new Error(`${file}:${number}: not a JSON row`);
  }
}

const args = parseArgs(process.argv.slice(2));
const { NullPii } = await import(pathToFileURL(join(args.dist, 'index.js')).href);
const config = {
  backend: 'cpu',
  ...(args['model-dir'] !== undefined && { modelDir: args['model-dir'] }),
  ...(args.config !== undefined && JSON.parse(args.config)),
};
const np = new NullPii(config);
const fails = {};
let n = 0;
let masked = 0;
let lineNumber = 0;
for await (const line of jsonlLines(args.texts)) {
  lineNumber += 1;
  if (line.trim() === '') continue;
  const row = parseRow(line, lineNumber, 'the texts');
  const r = await np.sanitize(row.text);
  if (r.sanitized !== row.text) masked += 1;
  const back = np.restore(r.sanitized, r.sessionId);
  np.destroySession(r.sessionId);
  if (back.restored !== row.text) (fails[row.dataset] ??= []).push(row.idx);
  n += 1;
}
await np.dispose();
const failed = Object.values(fails).reduce((a, f) => a + f.length, 0);
process.stdout.write(`${JSON.stringify({ docs: n, masked, roundtrip_failures: failed, failing_idx: fails })}\n`);
