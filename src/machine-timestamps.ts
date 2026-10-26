// SPDX-License-Identifier: Apache-2.0

/**
 * Log-record timestamps — the time a logger stamped at the head of each
 * line (`2026-10-16T09:41:07Z INFO …`, `[2026-10-16 09:41:07,123] …`).
 * They date the record, not a person, and an agent debugging a log needs
 * them: masking every line's head hides the ordering and gaps it is
 * looking for. The model labels them `private_date`.
 *
 * Deliberately narrow. A timestamp quoted inside prose ("the meeting is
 * at 2023-05-12T14:30") can be personal data, and benchmark gold treats
 * it so. Only a full timestamp that opens a line (optionally after
 * whitespace or `[`) AND is followed within a few characters by a log
 * level (`INFO`, `WARN`, `ERROR`, …) qualifies — the shape of a logger's
 * record prefix in Python logging, Logback, log4j and most app logs. A
 * bare date never matches.
 */
const LOG_LINE_TIMESTAMP =
  /^[ \t]*\[?(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?| \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)(?:Z|[+-]\d{2}:?\d{2})?)\]?(?=[^\n]{0,24}?\b(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL)\b)/gm;

const DATE_LABEL = 'private_date';

/**
 * Drop `private_date` spans that lie entirely inside a log-line
 * timestamp. Spans of other labels, and date spans reaching past the
 * timestamp, are kept.
 *
 * @param spans - candidate spans, ML and recognizer, pre-dedupe
 * @param text - the text the span offsets index into
 */
export function dropDatesInsideMachineTimestamps<
  T extends { label: string; start: number; end: number },
>(spans: T[], text: string): T[] {
  const stamps = [...text.matchAll(LOG_LINE_TIMESTAMP)].map((m) => {
    const stamp = m[1] ?? '';
    const start = m.index + m[0].length - stamp.length;
    return [start, start + stamp.length];
  });
  if (stamps.length === 0) return spans;
  return spans.filter(
    (s) =>
      s.label !== DATE_LABEL ||
      !stamps.some(([a, b]) => a !== undefined && b !== undefined && s.start >= a && s.end <= b),
  );
}
