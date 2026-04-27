# Security model

See [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md)
in the repository root for the canonical version, including how to report
vulnerabilities.

## Quick summary

**What nullpii protects:**

- The original PII never leaves your process.
- The vault is in-memory only; never written to disk.
- `destroySession()` purges the mapping immediately.

**What nullpii does *not* protect:**

- Model recall errors (false negatives / false positives).
- LLM independently emitting information it already knew.
- Anything logged or cached by your application **before** `sanitize()`.
- Cross-process leakage (the vault is per-process).
- Adversarial prompts that talk the LLM into disclosing the placeholder
  mapping logically.

## Code-enforced rules

- No `console.log` in library code (Biome rule `noConsoleLog: error`).
- Debug logs never include PII; only counts and short id prefixes.
- File paths are sandboxed — `InvalidPathError` on traversal.
- Apache-2.0 / MIT / BSD / ISC / CC0 dependencies only — `npm run license-check`.
- `--provenance` on every npm publish.
