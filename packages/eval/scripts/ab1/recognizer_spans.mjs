// SPDX-License-Identifier: Apache-2.0
// AB-1 (SPEC.md, "Metrics"): the spans nullpii's default recognizer pack
// finds alone, no model, on each gold document's raw text. `secret_coverage.py`
// reads them to split the secrets' leak rate by whether the pack covers the
// item's format. Writes checkpoint rows `{"idx", "spans"}` with code-point
// offsets; prints counts only, never text.
//
//   node recognizer_spans.mjs --dist <abs dist> --gold <gold.jsonl> --out <spans.jsonl> [--split test]
import { createReadStream, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith('--')) throw new Error(`unexpected argument ${argv[i]}`);
    out[argv[i].slice(2)] = argv[i + 1];
  }
  for (const k of ['dist', 'gold', 'out']) if (!out[k]) throw new Error(`--${k} is required`);
  return out;
}

/** JSONL split on '\n' only (readline would also split on U+2028/U+2029). */
async function* jsonlLines(path) {
  let rest = '';
  for await (const chunk of createReadStream(path, { encoding: 'utf8' })) {
    const lines = (rest + chunk).split('\n');
    rest = lines.pop();
    yield* lines;
  }
  yield rest;
}

/** UTF-16 offset of `text` → code-point offset (the gold indexes code points). */
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
const { runRecognizers } = await import(pathToFileURL(join(args.dist, 'recognizers.js')).href);
const { DEFAULT_RECOGNIZERS } = await import(pathToFileURL(join(args.dist, 'defaults.js')).href);
const rows = [];
let spans = 0;
let lineNumber = 0;
for await (const line of jsonlLines(args.gold)) {
  lineNumber += 1;
  if (line.trim() === '') continue;
  const row = parseRow(line, lineNumber, 'the gold');
  // The rows `secret_coverage.py --split` scores, in the same order.
  if (args.split !== undefined && row.split !== args.split) continue;
  const { text } = row;
  const cp = codePointOffsets(text);
  const found = runRecognizers(text, DEFAULT_RECOGNIZERS, []).map((s) => [cp(s.start), cp(s.end), s.label]);
  spans += found.length;
  rows.push(JSON.stringify({ idx: rows.length, spans: found }));
}
writeFileSync(args.out, `${rows.join('\n')}\n`);
console.log(JSON.stringify({ docs: rows.length, spans }));
