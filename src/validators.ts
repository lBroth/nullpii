import { createHash } from 'node:crypto';

/**
 * Per-recognizer post-match validators that drop false positives the
 * regex shape cannot reject by itself. Mirrors the Python
 * `_label_validator` in `packages/eval/src/nullpii_eval/adapters.py`.
 *
 * Currently provides:
 *   - `base58CheckValid` — BTC Legacy/P2SH addresses (start with `1`
 *     or `3`, base58 charset, 26-34 chars). Drops prose tokens that
 *     share the shape but fail the cryptographic checksum.
 *
 * Wire a validator into a recognizer via the `validate` field on
 * `Recognizer`. The `runRecognizers` pipeline calls it once per
 * candidate match and discards the span if it returns `false`.
 */

const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const BASE58_INDEX = new Map<string, bigint>();
for (let i = 0; i < BASE58_ALPHABET.length; i++) {
  const ch = BASE58_ALPHABET[i];
  if (ch !== undefined) BASE58_INDEX.set(ch, BigInt(i));
}

/**
 * Validate a base58check-encoded string (BIP-0013).
 *
 * Decodes base58 → bytes; payload + 4-byte checksum;
 * SHA256(SHA256(payload))[:4] must equal checksum.
 *
 * AUDIT F07: drops false-positive matches on prose tokens that share
 * the base58 charset shape (e.g. `Order ID: 1A2B3C4D5E6F7G8H9J1K2L3M4N`)
 * but fail the cryptographic checksum.
 */
export function base58CheckValid(addr: string): boolean {
  if (addr.length < 25 || addr.length > 35) return false;
  let n = 0n;
  for (const ch of addr) {
    const idx = BASE58_INDEX.get(ch);
    if (idx === undefined) return false;
    n = n * 58n + idx;
  }
  // Convert bigint to bytes (big-endian).
  const body: number[] = [];
  let v = n;
  while (v > 0n) {
    body.unshift(Number(v & 0xffn));
    v >>= 8n;
  }
  // Re-attach leading-zero bytes encoded as leading `1`s in base58.
  let leadingOnes = 0;
  for (const ch of addr) {
    if (ch === '1') leadingOnes++;
    else break;
  }
  const decoded = Buffer.from([...new Array(leadingOnes).fill(0), ...body]);
  if (decoded.length < 5) return false;
  const payload = decoded.subarray(0, decoded.length - 4);
  const checksum = decoded.subarray(decoded.length - 4);
  const expected = createHash('sha256')
    .update(createHash('sha256').update(payload).digest())
    .digest()
    .subarray(0, 4);
  return checksum.equals(expected);
}
