// SPDX-License-Identifier: Apache-2.0

import type { PiiSpan } from './types/index.js';

/**
 * Scan `text` for common templating syntax ranges. Spans falling inside
 * one of these ranges are dropped before vault substitution so the model
 * never gets to flag a template variable name as PII.
 *
 * Supported syntaxes (deliberately conservative):
 *  - `{{ ... }}` — Mustache / Handlebars / Vue / Jinja2 expression
 *  - `${ ... }` — JS / TS template literal
 *  - `<% ... %>` — ERB / EJS
 *  - `{% ... %}` — Jinja2 / Twig statement
 *
 * Each match covers the FULL syntactic span including the delimiters,
 * so a recognizer span partially overlapping the opener / closer is
 * also dropped (the alternative leaves bracket count off after vault
 * substitution).
 *
 * Non-greedy match — nested `{{...}}` resolves on the inner pair, which
 * is the desired outcome (the outer braces become bare braces, which
 * GLiNER no longer mistakes for sentinels).
 */
const TEMPLATE_PATTERNS: readonly RegExp[] = [
  /\{\{[\s\S]*?\}\}/g,
  /\$\{[^{}]*\}/g,
  /<%[\s\S]*?%>/g,
  /\{%[\s\S]*?%\}/g,
];

export interface TemplateRange {
  readonly start: number;
  readonly end: number;
}

export function findTemplateRanges(text: string): TemplateRange[] {
  const ranges: TemplateRange[] = [];
  for (const re of TEMPLATE_PATTERNS) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null = re.exec(text);
    while (m !== null) {
      ranges.push({ start: m.index, end: m.index + m[0].length });
      m = re.exec(text);
    }
  }
  return mergeRanges(ranges);
}

/** Drop spans that overlap ANY template range. Partial overlap is enough —
 * a span that crosses a `{{` / `}}` boundary corrupts bracket count after
 * vault substitution, so it must go too. */
export function dropSpansInsideTemplates(
  spans: readonly PiiSpan[],
  ranges: readonly TemplateRange[],
): PiiSpan[] {
  if (ranges.length === 0) return [...spans];
  return spans.filter((s) => !ranges.some((r) => overlaps(s.start, s.end, r.start, r.end)));
}

function overlaps(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aStart < bEnd && bStart < aEnd;
}

function mergeRanges(ranges: readonly TemplateRange[]): TemplateRange[] {
  if (ranges.length <= 1) return [...ranges];
  const sorted = [...ranges].sort((a, b) => a.start - b.start || a.end - b.end);
  const out: TemplateRange[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last !== undefined && r.start < last.end) {
      out[out.length - 1] = { start: last.start, end: Math.max(last.end, r.end) };
    } else {
      out.push(r);
    }
  }
  return out;
}
