// SPDX-License-Identifier: Apache-2.0

/** Ordered tuple of nullpii's PII categories (plus `'O'` for legacy
 * compatibility — never emitted).
 *
 * The unified GLiNER model is trained on the 8 ML categories
 * (`account_number`, `private_address`, `private_date`, `private_email`,
 * `private_person`, `private_phone`, `private_url`, `secret`). The
 * recognizer pack additionally emits `private_ip` for IPv4 / IPv6 /
 * MAC matches — IPs do not fit any of the original 8 cleanly and were
 * previously mis-labelled as `account_number`. The model is not
 * prompted with `private_ip`, so it never appears in raw model output;
 * only the regex post-pass produces it. */
export const PII_LABELS = [
  'O',
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_ip',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
] as const;

/** Union of every label, including `'O'`. */
export type PiiLabel = (typeof PII_LABELS)[number];

/** Union of PII labels excluding `'O'` — the user-visible categories. */
export type PiiCategory = Exclude<PiiLabel, 'O'>;

/** Subset of {@link PiiCategory} that the unified GLiNER model is
 * trained to emit. The recognizer pack can produce additional labels
 * (e.g. `private_ip`) that the model itself never outputs. */
export const GLINER_MODEL_CATEGORIES = [
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
] as const satisfies readonly PiiCategory[];
