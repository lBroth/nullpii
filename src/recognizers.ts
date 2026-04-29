import type { PiiSpan, Recognizer } from './types/index.js';

/**
 * Run every recognizer against `text`, return non-overlapping spans.
 * Used as a regex post-pass after the ML detector. ML spans take priority
 * on overlap; recognizer spans only fill gaps.
 */
export function runRecognizers(
  text: string,
  recognizers: readonly Recognizer[],
  existing: readonly PiiSpan[],
): PiiSpan[] {
  const out: PiiSpan[] = [];
  for (const r of recognizers) {
    out.push(...matchOne(text, r, existing));
  }
  return out;
}

function matchOne(text: string, recognizer: Recognizer, existing: readonly PiiSpan[]): PiiSpan[] {
  const re = ensureGlobal(recognizer.pattern);
  const out: PiiSpan[] = [];
  let m: RegExpExecArray | null = re.exec(text);
  while (m !== null) {
    const start = m.index;
    const end = start + m[0].length;
    if (!overlaps(start, end, existing) && passesValidate(m[0], recognizer)) {
      out.push({
        label: recognizer.label,
        start,
        end,
        score: recognizer.confidence,
        text: m[0],
      });
    }
    m = re.exec(text);
  }
  return out;
}

function ensureGlobal(re: RegExp): RegExp {
  return re.flags.includes('g')
    ? new RegExp(re.source, re.flags)
    : new RegExp(re.source, `${re.flags}g`);
}

function overlaps(start: number, end: number, spans: readonly PiiSpan[]): boolean {
  for (const s of spans) {
    if (start < s.end && end > s.start) return true;
  }
  return false;
}

function passesValidate(match: string, recognizer: Recognizer): boolean {
  return recognizer.validate === undefined || recognizer.validate(match);
}
