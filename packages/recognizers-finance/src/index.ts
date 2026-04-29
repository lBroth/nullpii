import type { Recognizer } from 'nullpii';

/** Luhn check digit validation for credit-card numbers. */
export function luhn(num: string): boolean {
  const digits = num.replace(/\D/g, '');
  if (digits.length < 12 || digits.length > 19) return false;
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = Number(digits[i]);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

/** Mod-97 IBAN check. */
export function iban97(raw: string): boolean {
  const stripped = raw.replace(/\s/g, '').toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]+$/.test(stripped)) return false;
  if (stripped.length < 15 || stripped.length > 34) return false;
  const rearranged = stripped.slice(4) + stripped.slice(0, 4);
  let remainder = 0;
  for (const ch of rearranged) {
    const v = ch.charCodeAt(0) >= 65 ? ch.charCodeAt(0) - 55 : Number(ch);
    remainder = (remainder * (v >= 10 ? 100 : 10) + v) % 97;
  }
  return remainder === 1;
}

/** Credit-card-shaped strings, Luhn-validated. */
export const CREDIT_CARD: Recognizer = {
  id: 'finance:credit-card',
  pattern: /\b(?:\d[ -]?){12,18}\d\b/g,
  label: 'account_number',
  confidence: 0.95,
  validate: luhn,
};

/** IBAN with mod-97 check. */
export const IBAN: Recognizer = {
  id: 'finance:iban',
  pattern: /\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4}\b/g,
  label: 'account_number',
  confidence: 0.97,
  validate: iban97,
};

/** SWIFT / BIC. 8 or 11 chars, ISO 9362. */
export const SWIFT_BIC: Recognizer = {
  id: 'finance:swift-bic',
  pattern: /\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b/g,
  label: 'account_number',
  confidence: 0.85,
};

export const FINANCE: readonly Recognizer[] = [CREDIT_CARD, IBAN, SWIFT_BIC];
