// SPDX-License-Identifier: Apache-2.0

interface Interval {
  readonly start: number;
  readonly end: number;
}

/** Intersection-over-union for char-offset intervals. Returns 0 when
 * the intervals don't overlap. Used by chunking's overlap dedupe and
 * by the GLiNER decoder's non-max suppression. */
export function iou(a: Interval, b: Interval): number {
  const interStart = Math.max(a.start, b.start);
  const interEnd = Math.min(a.end, b.end);
  const inter = Math.max(0, interEnd - interStart);
  if (inter === 0) return 0;
  const union = a.end - a.start + (b.end - b.start) - inter;
  return union > 0 ? inter / union : 0;
}
