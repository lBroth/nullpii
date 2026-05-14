import { type Recognizer, codiceFiscaleValid } from 'nullpii';

/**
 * Codice fiscale validator — re-exported from `nullpii` so this pack and
 * the core runtime cannot drift apart. The canonical implementation
 * lives in `src/validators.ts` and enforces both the 16-char format
 * (`[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]`) and the
 * weighted-position checksum.
 *
 * Kept under its descriptive name for ergonomic imports from this pack.
 */
export const validateCodiceFiscale = codiceFiscaleValid;

/** Partita IVA (Italian VAT) — 11-digit Luhn-style mod-10 (Italian variant). */
export function validatePartitaIva(raw: string): boolean {
  const s = raw.replace(/\D/g, '');
  if (s.length !== 11) return false;
  let sum = 0;
  for (let i = 0; i < 11; i++) {
    let n = Number(s[i]);
    if (i % 2 === 1) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
  }
  return sum % 10 === 0;
}

export const CODICE_FISCALE: Recognizer = {
  id: 'id-it:codice-fiscale',
  pattern: /\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b/gi,
  label: 'account_number',
  confidence: 0.97,
  validate: validateCodiceFiscale,
};

export const PARTITA_IVA: Recognizer = {
  id: 'id-it:partita-iva',
  pattern: /\b\d{11}\b/g,
  label: 'account_number',
  confidence: 0.9,
  validate: validatePartitaIva,
};

export const ITALIAN_IDS: readonly Recognizer[] = [CODICE_FISCALE, PARTITA_IVA];
