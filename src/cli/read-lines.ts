// SPDX-License-Identifier: Apache-2.0

/** Lines of a text stream, split on '\n' only (a trailing '\r' is
 * dropped). `node:readline` also ends a line at U+2028 and U+2029, which
 * JSON leaves unescaped inside strings, and would cut an NDJSON row
 * holding one in two. */
export async function* readLines(input: AsyncIterable<Buffer | string>): AsyncGenerator<string> {
  const decoder = new TextDecoder();
  let rest = '';
  for await (const chunk of input) {
    const text = typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true });
    const lines = (rest + text).split('\n');
    rest = lines.pop() ?? '';
    for (const line of lines) yield line.endsWith('\r') ? line.slice(0, -1) : line;
  }
  rest += decoder.decode();
  if (rest !== '') yield rest.endsWith('\r') ? rest.slice(0, -1) : rest;
}
