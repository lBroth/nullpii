# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new) or email the maintainer (`package.json` `author`). Initial response within ~10 business days.

## What nullpii protects

- Detection runs entirely local — no network calls.
- Vault is in-memory only; `destroySession()` purges it.
- Logs never contain PII values (counts and short ids only).

## What it does NOT protect

- Detector misses (no model is 100% accurate).
- LLMs emitting PII they already knew independently.
- Logging / caching / telemetry running **before** `sanitize()`.
- Adversarial prompts asking the LLM to reveal mappings.

## CI-enforced rules

- Apache-2.0 / MIT / BSD / ISC / CC0 deps only.
- npm releases use `--provenance`.
- File paths sandboxed to a cache root (`InvalidPathError` on traversal).
