// SPDX-License-Identifier: Apache-2.0

import type { PiiLabel } from './labels.js';

/**
 * One vault entry: a placeholder paired with the original PII value it replaced.
 * Vault contents are kept in memory only (never serialized to disk per
 * the project's security invariants).
 */
export interface VaultToken {
  /** The exact placeholder string that appears in sanitized text. */
  readonly placeholder: string;
  /** Label of the original span. Never `'O'`. */
  readonly label: Exclude<PiiLabel, 'O'>;
  /** Original PII string. Treat as sensitive — never log. */
  readonly original: string;
}
