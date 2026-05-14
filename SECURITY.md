# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new) or email the maintainer (`package.json` `author`). **48h triage; up to 10 business days for a fix decision.** Faster on actively-exploited or production-blocking issues.

## What nullpii protects

- Detection runs entirely local — no network calls.
- Vault is in-memory only; `destroySession()` purges it.
- Logs never contain PII values (counts and short ids only).
- Placeholders carry an 8-hex prefix of the minting session id. `restore()` surfaces foreign-prefix placeholders via `RestoreResult.foreignPlaceholders`; `{ strict: true }` throws `SessionMismatchError` instead.

## What it does NOT protect

- Detector misses (no model is 100% accurate).
- LLMs emitting PII they already knew independently.
- Logging / caching / telemetry running **before** `sanitize()`.
- Adversarial prompts asking the LLM to reveal mappings.

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` escapes literal `{{` in input to a Private Use Area codepoint pair (U+E000 U+E001) so user-typed Mustache braces don't collide with PII placeholders during the LLM round-trip. If your input legitimately contains that PUA pair, it will collapse to `{{` on the way out. PUA codepoints are unallocated to standard glyphs and effectively never appear in natural text or LLM output, but the trade-off is documented for completeness.
- **URL %XX decode depth cap.** The adversarial-input normalizer iterates URL `%XX` decoding at most twice per position. Two rounds collapses `%2540` → `%40` → `@` (the practical bypass); 3+ chained encodings (`%252540` etc.) defeat the normalizer and rely on the ML model alone for detection.

## CI-enforced rules

- Apache-2.0 / MIT / BSD / ISC / CC0 deps only.
- npm releases use `--provenance`.
- File paths sandboxed to a cache root (`InvalidPathError` on traversal).
