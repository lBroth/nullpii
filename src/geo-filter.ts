// SPDX-License-Identifier: Apache-2.0

import { latLonPairInRange } from './validators.js';

/** Shape gate for model-emitted `private_geolocation` spans.
 *
 * This schema defines `private_geolocation` as a coordinate — the three
 * recognizers that own the label (`core:geo-latlon-decimal`,
 * `core:geo-dms`, `core:geo-context` in `defaults.ts`) all match
 * lat/lon literals, and `core:geo-latlon-decimal` additionally
 * range-validates. The GLiNER head, which is prompted with
 * `private_geolocation` zero-shot and never trained on it, does not
 * share that definition: it labels place names, regions and postcodes
 * as geolocation.
 *
 * Measured on `isotonic-en-heldout`: of 101 model-emitted
 * `private_geolocation` spans, 70 were wrong — 42 sat on gold
 * `private_address` (`Nidwalden`, `Emilia-Romagna`, `Rohnert Park`,
 * `98025`), 11 on gold `private_ip` (`210.193.85.111`), 10 on no gold
 * at all (`Southeast`, `143cm`). All 78 gold spans of the class, and
 * all 31 correct predictions, are lat/lon pairs. The cost is therefore
 * asymmetric: the gate removes false positives and cannot remove a true
 * positive that matches the schema's own definition of the label.
 *
 * The damage is doubled, which is why dropping is not enough on its
 * own: a place name tagged `private_geolocation` is both a false
 * positive on that label AND leaves the `private_address` gold
 * unmatched. Applying this filter BEFORE cross-label dedupe lets the
 * model's competing `private_address` candidate for the same region
 * survive instead of losing the overlap to a label it should never
 * have won.
 *
 * Recognizer spans are not passed through this gate — they match a
 * coordinate pattern by construction.
 */

/** A decimal `lat,lon` pair, tolerant of the brackets and stray leading
 * punctuation the model's span boundaries sometimes include
 * (`- [-64.6681,-23.7374`). At least one component must carry a decimal
 * point so bare integer pairs (`12, 34` — a date, a score, a range)
 * do not qualify. */
const DECIMAL_PAIR =
  /(-?\d{1,3}\.\d+)\s*[,;]\s*(-?\d{1,3}(?:\.\d+)?)|(-?\d{1,3}(?:\.\d+)?)\s*[,;]\s*(-?\d{1,3}\.\d+)/;

/** Degrees/minutes/seconds with a hemisphere letter — distinctive
 * enough to stand alone, mirroring `core:geo-dms`. */
const DMS = /\d{1,3}\s*°\s*\d{1,2}\s*['′]/;

/**
 * True when `text` carries a coordinate under this schema's definition
 * of `private_geolocation`.
 *
 * @param text - the span's surface text
 */
export function isCoordinateShaped(text: string): boolean {
  if (DMS.test(text)) return true;
  const m = DECIMAL_PAIR.exec(text);
  if (m === null) return false;
  const lat = m[1] ?? m[3];
  const lon = m[2] ?? m[4];
  if (lat === undefined || lon === undefined) return false;
  return latLonPairInRange(`${lat},${lon}`);
}

/** A dotted quad, with the stray punctuation span boundaries carry. The
 * `core:ipv4` recognizer owns this shape and labels it `private_ip`. */
const IPV4_SHAPE = /^\W*\d{1,3}(?:\.\d{1,3}){3}\W*$/;

const ADDRESS_LABEL = 'private_address';

/**
 * Resolve model-emitted `private_geolocation` spans that carry no
 * coordinate. Spans of every other label pass through untouched.
 *
 * - Coordinate-shaped: kept as `private_geolocation`.
 * - IPv4-shaped: dropped, so the `core:ipv4` recognizer (which defers to
 *   overlapping model spans) labels it `private_ip`.
 * - Anything else: relabelled `private_address`. These are the place
 *   names, streets and postcodes the zero-shot head mislabels, and they
 *   are PII: dropping them, as an earlier build did, left every one unmasked
 *   whenever no competing address candidate survived.
 *
 * Call this on raw decoder output, before cross-label dedupe — see the
 * module doc for why the ordering matters.
 *
 * @param spans - decoded model spans
 * @param text - the text the span offsets index into
 */
export function resolveNonCoordinateGeolocation<
  T extends { label: string; start: number; end: number },
>(spans: T[], text: string): T[] {
  const out: T[] = [];
  for (const s of spans) {
    const surface = text.slice(s.start, s.end);
    if (s.label !== 'private_geolocation' || isCoordinateShaped(surface)) {
      out.push(s);
    } else if (!IPV4_SHAPE.test(surface)) {
      out.push({ ...s, label: ADDRESS_LABEL });
    }
  }
  return out;
}
