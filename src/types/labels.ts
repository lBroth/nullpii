/**
 * Ordered tuple of every PII label produced by `openai/privacy-filter`.
 * The 8 categories are exactly those documented in the upstream model card,
 * plus `'O'` (outside any span). See `packages/convert/artifacts/manifest.json`
 * for the pinned upstream revision.
 */
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
