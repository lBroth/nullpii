// SPDX-License-Identifier: Apache-2.0

import { isPiiCategoryLabel, shortName } from './categories.ts';

export interface PreviewResult {
  readonly sanitized: string;
  readonly counts: string;
}

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

/** Validate a sanitize answer and format only its masked text and known
 * category counts. Unknown labels or counts reject the whole answer. */
export function formatPreview(answer: unknown): PreviewResult | undefined {
  if (typeof answer !== 'object' || answer === null) return undefined;
  const result = answer as { value?: unknown; captured?: unknown; capturedByLabel?: unknown };
  const labels = result.capturedByLabel;
  if (
    typeof result.value !== 'string' ||
    !count(result.captured) ||
    typeof labels !== 'object' ||
    labels === null ||
    Array.isArray(labels)
  ) {
    return undefined;
  }
  const entries = Object.entries(labels);
  if (entries.some(([label, n]) => !isPiiCategoryLabel(label) || !count(n))) return undefined;
  const total = entries.reduce((sum, [, n]) => sum + (n as number), 0);
  if (total !== result.captured) return undefined;
  const byType = entries
    .filter((entry): entry is [string, number] => count(entry[1]) && entry[1] > 0)
    .map(([label, n]) => `${shortName(label).toUpperCase()} ${n}`)
    .join(' · ');
  return {
    sanitized: result.value,
    counts: `Masked: ${total}${byType === '' ? '' : ` (${byType})`}`,
  };
}
