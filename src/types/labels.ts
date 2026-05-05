/** Ordered tuple of nullpii's 8 PII categories (plus `'O'` for legacy
 * compatibility — never emitted). Matches the GLiNER prompt vocabulary
 * and the per-domain LoRA training labels. */
export const PII_LABELS = [
  'O',
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
] as const;

/** Union of every label, including `'O'`. */
export type PiiLabel = (typeof PII_LABELS)[number];

/** Union of PII labels excluding `'O'` — the user-visible categories. */
export type PiiCategory = Exclude<PiiLabel, 'O'>;
