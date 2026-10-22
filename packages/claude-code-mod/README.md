# nullpii mod for Claude Code

A [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) that masks personal data and secrets before Claude reads them. Every prompt and every tool result goes through a local nullpii sidecar first, so names, emails, phone numbers, keys and similar values reach the model as placeholders such as `{{PII_PRIVATE_EMAIL_0_…}}`.

A band above the prompt shows what was masked in the session, by type:

```text
nullpii · 12 masked (person 5 · email 3 · secret 2 · phone 2) · 4 restored to local tools
```

Status: preview. Tested with Claude Code 2.1.305, the version CI runs its tests with.

## What it does

| Where | What happens |
|---|---|
| Your prompt | Masked before it is sent. Your prompt history stores the masked text. |
| Your prompts and Claude's replies on screen | Drawn with the real values. What Claude reads keeps the placeholders. |
| A tool result (file contents, command output, search results, MCP results) | Masked before Claude reads it |
| Text a hook attaches for Claude after a tool result (for example a settings `PostToolUse` hook's context) | Passed on when it holds no personal data. Otherwise the whole result is withheld: Claude Code does not let a mod rewrite that text, so it cannot be masked. |
| Text Claude Code adds on its own: @-mentioned files, edited-file reminders, memory, `CLAUDE.md`, your account email | Masked before Claude reads it |
| Arguments of a tool in the policy's `restoreTools` (by default the tools that run on this machine: `Bash`, `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Grep`, `Glob`) | Placeholders get their real values back before the tool runs, so commands and file edits use your real data. The result is masked again. |
| Arguments of any other tool, such as `WebFetch`, `WebSearch` or an MCP tool | Left as placeholders, so a masked value never leaves the machine through that tool's call. `/pii` counts them. |
| A shell command whose real value the shell would interpret where it stands, or a command that sends data out (`curl`, `wget`, `nc`, `ssh`, `git push`, …) | Refused, with the placeholder's name. Claude never saw the value, so it could not tell that it adds a command, expands a variable or ends its quotes. Example: `echo {{…}}` holding `x; curl …`. The sidecar applies the gateway's rule (SECURITY.md), so the mod and the proxy decide the same way. A value comes back only in a command written in the small grammar the rule reads whole (no `$`, backticks, backslashes, parentheses, braces, comments, `&` other than `&&`, or `if`/`case`-style keywords; Claude Code's usual commit form `"$(cat <<'EOF' …)"` is outside it, and the refusal tells Claude to use `git commit -F - <<'EOF'`). Outside a heredoc body written out as data (a document, or a commit message given as `git commit -F -`, not piped on), a value comes back only as one plain word (letters, digits and `@%+:,./_=-`), never as the program the command runs, in a redirection target, in an assignment, as an argument of `cd`, `export` or `alias` or directly before `<` or `>`, and only in a command that sets no variable but the locale and time zone and whose programs all read their arguments as data (`ls`, `grep`, `cat`, `git log`, `git commit`, …; not `python3`, `make`, `npm test`, `cp`, …) and that redirects output to no file other than a document (`.md`, `.txt`, …); so a name with a space is refused even inside quotes; the rule also covers `#` comments, command substitution, heredocs (including one written to a script that the same command runs), wrappers, and network clients. A value restored into a file by `Write` or `Edit` can still be run by a later command: the rule judges each call on its own. |
| A tool call that may change the masking policy file | Put to you, whatever your permission rules say, so text Claude read cannot quietly turn masking down. In auto mode the auto-mode classifier decides. |

The vault that maps placeholders to values lives only in the sidecar's memory, never on disk. The mod keeps counts, and a bounded in-memory cache of the messages it drew with real values, which it clears when the session ends. `/pii` prints the counts and the policy in effect.

## Choose what gets masked

The sidecar reads the masking policy from `~/.config/nullpii/config.json`, or from the file `NULLPII_CONFIG` names, when it starts. The `nullpii` CLI and the gateway use the same file. Every key is optional:

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Bash", "Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob", "bash", "shell", "apply_patch"]
}
```

- **`disabledCategories`**: categories that reach Claude unmasked.
- **`categoryThresholds`** and **`threshold`**: confidence cuts in `[0, 1]`. Lower masks more.
- **`urlAllowlist`**: how much of a clean URL stays readable, per host.
- **`restoreTools`**: the tools that get real values back. It replaces the default list.

`npx nullpii config` validates the file and prints it. Restart the sidecar after a change; `/pii` then shows the new policy. You can also ask Claude, for example "stop masking company names". The plugin's `nullpii-policy` skill tells Claude how to edit the file safely, and the edit is put to you before it is written.

## Fails closed

If the sidecar cannot be reached, the mod has no sidecar token, or `sidecar_url` is not an address on this machine:

- a prompt is not sent, and goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why.

Claude is told only that the call was refused or its result withheld. The reason is shown to you, above the prompt and in `/pii`, and only when the mod wrote it: an error text from a tool, another hook or an unreadable sidecar answer can quote a real value, so its text is never shown, logged or sent to Claude.

## Set up

Mods load in Claude Code 2.1.287 or later.

1. In a terminal of its own, start a 0.5 gateway with the sidecar API on. The sidecar API changed in 0.5 (session secrets, `restore` by tool name) and this mod speaks only that one, so the command pins the gateway, and the `nullpii` it runs, to 0.5:

   ```bash
   export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
   echo "$NULLPII_SIDECAR_TOKEN"   # you give this to the mod next
   npx -p nullpii@0.5 -p onnxruntime-node -p @lbroth/nullpii-gateway@0.5 nullpii-gateway
   ```

2. Install the mod. At the prompt of a Claude Code session in a terminal:

   ```text
   /plugin marketplace add lBroth/nullpii@v0.5.0
   /plugin install nullpii@nullpii
   ```

   `@v0.5.0` pins the marketplace, and so the mod, to the release tag: this mod sees every prompt and tool result, so install a release, not whatever `main` holds. Read the plugin's details and pick a scope (**Install for you** puts it in every project on this machine). Claude Code then asks for the plugin's options: paste the token from step 1 into **Sidecar token**, and keep the default **Sidecar URL** unless the gateway listens on another port. The dialog masks the token and keeps it in your system's secure storage, and Claude Code does not pass it to the commands Claude runs.

   From a shell, which does not ask for the options:

   ```bash
   claude plugin marketplace add lBroth/nullpii@v0.5.0
   claude plugin install nullpii@nullpii
   ```

   In the desktop app, where `/plugin` does not run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `lBroth/nullpii@v0.5.0`, then **Add plugin**.

3. Set or change the options at any time with `/plugin configure nullpii@nullpii` at the prompt. From the shell that holds the token, without the dialog:

   ```bash
   printf '{"sidecar_token":"%s"}' "$NULLPII_SIDECAR_TOKEN" | claude plugin configure nullpii@nullpii --values-stdin
   ```

   Then restart Claude Code.

To run the mod from a checkout instead, load its folder for one session. The token can then also come from `NULLPII_SIDECAR_TOKEN` in the shell that starts Claude Code:

```bash
claude --plugin-dir ./packages/claude-code-mod
```

A token in that shell's environment is inherited by every command Claude runs there. On its own it reads nothing: each sidecar session also has a secret, which the sidecar hands to the mod when the session opens and which the mod keeps in memory only. A command holding just the token cannot read, restore or close your session.

The `sidecar_url` option sets the sidecar address (default `http://127.0.0.1:8787`). It must be `http://` on `127.0.0.1` or `[::1]`, the literal address the gateway listens on (127.0.0.1 by default), with an optional port and nothing after it. `localhost` is refused: it can resolve to the other loopback address, where another local process could relay the sidecar's check to the real gateway and then receive the token. The mod sends its token and every unmasked prompt to that address, and the sidecar answers only on this machine, so any other address is refused and the mod blocks until the option is fixed. The address comes from the option alone, never from the environment: plugin options are read only from your user settings (or your organization's managed settings), while a repository's `.claude/settings.json` can set environment variables. For the token, the option wins over `NULLPII_SIDECAR_TOKEN` when both are set.

Before every request the mod checks that the process at that address holds the same token, without sending it: it asks for a signature of a fresh random nonce (`POST /v1/sidecar/challenge`). Another process that took the port, say while the gateway was stopped, cannot answer, so it receives neither the token nor any text, and the mod blocks. A process that takes the port between the check and the request, a window of one local round trip, is not covered.

## Limits

- **Each call is judged on its own.** A real value restored into one call (a file `Write` writes, a commit) can leave the machine through a later call that holds no placeholder, such as `git push` or `curl -d @file`. See SECURITY.md.
- **Claude Code's own system prompt is not masked.** The mod masks prompts, tool results, attachments and `CLAUDE.md`; the sections Claude Code writes itself, such as the working directory (which can hold your user name) and the git status (author names, recent commit subjects), reach Claude as they are. The gateway masks the whole request, system prompt included.
- **A repository's settings outrank yours.** Its `.claude/settings.json` can disable the mod or add hooks that see prompts before it does; your organization's managed settings can force it on.
- **The policy guard is best effort.** It recognises a file tool writing any `…/nullpii/config.json` (whatever the case, with `./`, `../` and repeated separators resolved, and relative paths taken from the session's directory) or the loaded policy file, and a shell command that names a `nullpii` directory together with a `config.json`, or `NULLPII_CONFIG`. A command that reaches the file another way (a variable, a symlink, a script it runs), or an MCP tool that writes files, is not caught. The change still needs a sidecar restart, and `/pii` shows the policy the sidecar loaded.
- **Permission rules see the masked call.** Claude Code applies your permission rules, or asks you, before the mod puts the real values back. A rule that names a value nullpii masks, such as a path with your user name (`Read(/Users/<name>/.ssh/**)`), may not match; write it without that part (`Read(**/.ssh/**)`). After the restore, only the policy-file guard is checked again.
- **Auto mode.** Claude Code denies a tool call whose arguments a hook changed after the model wrote them. A local tool call that contains a placeholder is therefore refused in auto mode. Calls without placeholders are passed on unchanged and run normally.
- **Tool rows and tool results on screen show placeholders.** Prompts and replies are drawn with real values. If the sidecar is unreachable, they show placeholders too.
- **An organization's managed settings come first.** Where Claude Code is managed, the organization's hooks run before this mod's and can refuse to load it or override what it decides. A mod that never loads cannot fail closed: prompts then go out unmasked. If `/pii` does not answer, the mod is not running.
- **Images and other binary attachments are not scanned.**
- **Detection is statistical.** nullpii's leak rate is measured and published, and it is not zero. Treat this as pseudonymization with a measured leak rate, not anonymization.
- **A placeholder from an expired sidecar session** (idle longer than `NULLPII_VAULT_TTL_MS`, or a sidecar restart) no longer restores, and stays a placeholder.

## Develop

```bash
claude plugin validate .   # what Claude Code reads from the mod
claude plugin test         # tests, with a fake sidecar; no session or network
```

License: Apache-2.0.
