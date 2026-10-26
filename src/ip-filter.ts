// SPDX-License-Identifier: Apache-2.0

/**
 * Model spans on an IPv4 address.
 *
 * The model labels a dotted quad with whatever label its head lands on:
 * `private_phone` (`server 93.184.216.34`), `account_number` (`docs IP
 * 203.0.113.7`), even `secret` (`ping 172.16.4.20`). The `core:ipv4`
 * recognizer owns that shape: it checks every octet, labels the address
 * `private_ip`, and leaves documentation, loopback, private, link-local,
 * multicast and unspecified addresses readable. But a recognizer defers
 * to a model span it overlaps, so the model's guess won, under the wrong
 * label, and those addresses were masked.
 *
 * So a model span whose text is an IPv4 address and nothing else is
 * dropped, whatever its label, before the recognizers run.
 */

/** A dotted quad, with the stray punctuation span boundaries carry. */
const IPV4_SHAPE = /^\W*\d{1,3}(?:\.\d{1,3}){3}\W*$/;

/**
 * Drop model spans whose text is an IPv4 address, so the `core:ipv4`
 * recognizer labels it, or leaves it readable.
 *
 * @param spans - decoded model spans
 * @param text - the text the span offsets index into
 */
export function dropModelIpv4Spans<T extends { start: number; end: number }>(
  spans: T[],
  text: string,
): T[] {
  return spans.filter((s) => !IPV4_SHAPE.test(text.slice(s.start, s.end)));
}
