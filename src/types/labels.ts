// SPDX-License-Identifier: Apache-2.0

/** Ordered tuple of nullpii's PII categories (plus `'O'` for legacy
 * compatibility — never emitted).
 *
 * The GLiNER model is trained on the 8 ML categories
 * (`account_number`, `private_address`, `private_date`, `private_email`,
 * `private_person`, `private_phone`, `private_url`, `secret`). The
 * recognizer pack additionally emits two post-pass-only labels:
 *
 *  - `private_ip` for IPv4 / IPv6 addresses;
 *  - `private_mac` for MAC addresses (hardware identifiers; previously
 *    misrouted under `private_ip` since both come from the regex pack,
 *    but consumers that group spans by label benefit from the split).
 *
 * The model is not prompted with `private_ip` / `private_mac`, so
 * neither appears in raw model output — only the regex post-pass
 * produces them. */
export const PII_LABELS = [
  'O',
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_ip',
  'private_mac',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
] as const;

/** Union of every label, including `'O'`. */
export type PiiLabel = (typeof PII_LABELS)[number];

/** Union of PII labels excluding `'O'` — the user-visible categories. */
export type PiiCategory = Exclude<PiiLabel, 'O'>;

/** Subset of {@link PiiCategory} that the GLiNER model is
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
