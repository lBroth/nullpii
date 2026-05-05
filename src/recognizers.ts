import type { PiiSpan, Recognizer } from './types/index.js';

/**
 * refuse to scan inputs > 1 MB. Unbounded `{N,}`
 * quantifiers in upstream secret patterns are quadratic on
 * adversarial padding. 1 MB is well above any realistic LLM prompt.
 */
const RECOGNIZER_INPUT_MAX_BYTES = 1_000_000;

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
  if (text.length > RECOGNIZER_INPUT_MAX_BYTES) {
    return [];
  }
  const out: PiiSpan[] = [];
  for (const r of recognizers) {
    out.push(...matchOne(text, r, existing));
  }
  return filterNeverPii(out, text);
}

/**
 * partial port: drop spans that match well-known never-PII
 * patterns. Reserved IP ranges, fictional NANP 555-01XX phones, RFC
 * 6761 reserved domains. Mirrors `_is_never_pii` in
 * `packages/eval/src/nullpii_eval/adapters.py`. Full preprocessor port
 * (`_normalize_for_detection`) is tracked as a separate roadmap item.
 */
function filterNeverPii(spans: readonly PiiSpan[], text: string): PiiSpan[] {
  const out: PiiSpan[] = [];
  for (const s of spans) {
    const value = text.slice(s.start, s.end);
    if (isNeverPii(value, s.label)) continue;
    out.push(s);
  }
  return out;
}

const NANP_FICTIONAL_555 = /^\+?1?[\s\-.()]*[2-9]\d{2}[\s\-.()]*555[\s\-.]*0[01]\d{2}$/;
const RFC1918_PRIVATE = /^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/;
const RFC6761_RESERVED = /(?:^|[@.])(?:example\.(?:com|net|org)|test|invalid|localhost|local)$/i;
const NULL_UUID = /^0{8}-0{4}-0{4}-0{4}-0{12}$/;
const ZERO_MAC = /^(?:[0:]{17}|(?:00[:-]){5}00)$/;

function isNeverPii(value: string, label: string): boolean {
  if (label === 'private_phone' && NANP_FICTIONAL_555.test(value)) return true;
  if (label === 'account_number') {
    if (RFC1918_PRIVATE.test(value)) return true;
    if (NULL_UUID.test(value)) return true;
    if (ZERO_MAC.test(value)) return true;
  }
  if ((label === 'private_url' || label === 'private_email') && RFC6761_RESERVED.test(value)) {
    return true;
  }
  return false;
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
