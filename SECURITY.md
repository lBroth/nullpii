# Security

## Report a vulnerability

Privately, please:

- Open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new), or
- Email the maintainer (`package.json` `author`).

Initial response within ~10 business days.

## What nullpii protects

- PII never leaves the machine: detection is fully local.
- Vault is in-memory only; `destroySession()` purges it.

## What it does NOT protect against

- Detector misses (no model is 100% accurate).
- LLM emitting PII it already knew independently.
- Logging / caching / telemetry that runs **before** `sanitize()`.
- Adversarial prompts that ask the LLM to reveal mappings.

## Code rules enforced in CI

- No `console.log` of PII; `debug` namespaced loggers only, with counts not values.
- Vault never serialized to disk.
- File paths sandboxed to a cache root (`InvalidPathError` on traversal).
- Apache-2.0 / MIT / BSD / ISC / CC0 dependencies only — `npm run license-check`.
- npm releases use `--provenance`.
- Model artifacts pinned to an upstream commit SHA + SHA256 sidecars.
