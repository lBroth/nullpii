// SPDX-License-Identifier: Apache-2.0

import type { Interval } from './iou.js';

/**
 * The secret pass: how a policy that leaves a category readable still
 * masks every secret the policy's own prompt finds.
 *
 * The model is prompted with the default's labels whatever the policy
 * (#92): the label set moves the model's scores, and with `secret`
 * prompted alone the model flags words such as `code` or `OK`. That
 * prompt, though, also decides which label a credential gets, and with
 * the default's labels the model files many under an identifier or a URL
 * (`account_number`, `private_driver_license`, `private_url`, …). The
 * default masks those categories too, so it masks the credential. A policy
 * that leaves them readable (the secrets-only preset, `/pii allow url`,
 * `/pii allow account`) would leave it in clear.
 *
 * So under such a policy the engine runs a second pass, prompted with the
 * labels the policy masks and no other (what 0.5.4 prompted), and keeps
 * its `secret` spans that the first pass also found as personal data of
 * some category, that a recognizer of the pack matches (under any label),
 * or that the first pass could not read at all (a word too long for a
 * window under the longer prompt). The first pass decides that a value is
 * personal data, the second that it is a secret; a word the first pass
 * reads and finds nothing in (`code`, `OK`) stays readable. Only `secret`
 * is taken from the second pass: with a category out of its prompt, the
 * model files that category's values under the nearest label it still
 * has (an email under `private_person`), and taking those would mask a
 * category the policy leaves readable under another name. The first pass
 * already decides every other category with the default's labels.
 *
 * What stays as in 0.5.4: a value the policy's own prompt calls a secret
 * is masked as one, even where the default's prompt calls it a category
 * the policy leaves readable (an IBAN, a plain URL under the secrets-only
 * preset). The model gives no signal that tells those apart from a
 * credential it files under the same category.
 */

const SECRET = 'secret';

/**
 * The labels the secret pass is prompted with, or `null` when no secret
 * pass runs: the policy leaves `secret` readable, or the policy's own
 * labels are the ones already prompted (the default, everything).
 *
 * @param labels - every label the model can be prompted with, in order
 * @param prompted - the labels the first pass is prompted with
 * @param disabled - the categories the policy leaves readable
 */
export function secretPassLabels(
  labels: readonly string[],
  prompted: readonly string[],
  disabled: ReadonlySet<string>,
): readonly string[] | null {
  if (disabled.has(SECRET)) return null;
  const masked = labels.filter((l) => !disabled.has(l));
  const same = masked.length === prompted.length && masked.every((l, i) => prompted[i] === l);
  return same ? null : masked;
}

/**
 * The secret pass's `secret` spans that overlap a range the first pass
 * saw: a span it found, under any label, or a word it could not read.
 *
 * @param spans - the secret pass's spans
 * @param seen - the first pass's spans under every label, its unread
 *   words, and the recognizer pack's matches
 */
export function secretsSeenByFirstPass<T extends Interval & { readonly label: string }>(
  spans: readonly T[],
  seen: readonly Interval[],
): T[] {
  return spans.filter(
    (s) => s.label === SECRET && seen.some((r) => r.start < s.end && s.start < r.end),
  );
}
