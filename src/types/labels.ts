// SPDX-License-Identifier: Apache-2.0

/** Ordered tuple of every PII category. Includes `'O'` (non-PII) at
 * index 0 as a structural placeholder — never emitted by the pipeline.
 * Source of truth for label provenance: {@link GLINER_MODEL_CATEGORIES}
 * (trained) + {@link GLINER_ZERO_SHOT_EXTRA} (prompted, zero-shot) +
 * recognizer-only (`private_ip`, `private_mac`). */
export const PII_LABELS = [
  'O',
  'account_number',
  'private_address',
  'private_date',
  'private_driver_license',
  'private_email',
  'private_geolocation',
  'private_ip',
  'private_mac',
  'private_passport',
  'private_person',
  'private_phone',
  'private_url',
  'private_vehicle_id',
  'secret',
] as const;

/** Union of every label, including `'O'`. */
export type PiiLabel = (typeof PII_LABELS)[number];

/** Union of PII labels excluding `'O'` — the user-visible categories. */
export type PiiCategory = Exclude<PiiLabel, 'O'>;

/** Subset of {@link PiiCategory} the GLiNER base model was trained on.
 * Inference also prompts {@link GLINER_ZERO_SHOT_EXTRA}; pure recognizer-
 * pack labels (`private_ip`, `private_mac`) are never model-emitted. */
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

/** Labels prompted to GLiNER at inference but NOT in the trained set —
 * the base model generalises to them zero-shot. The recognizer pack
 * still emits structured matches; the model adds free-form prose. */
export const GLINER_ZERO_SHOT_EXTRA = [
  'private_passport',
  'private_driver_license',
  'private_vehicle_id',
  'private_geolocation',
] as const satisfies readonly PiiCategory[];
