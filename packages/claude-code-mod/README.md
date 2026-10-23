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
| Arguments of a tool in the policy's `restoreTools` (by default the file tools that run on this machine: Claude Code's `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Grep`, `Glob`, and the `apply_patch` tool of other agents) | Placeholders get their real values back before the tool runs, in the arguments that carry data (for `Grep`, `pattern`, `path` and `glob`), so file reads, searches and edits use your real data. The result is masked again. |
| Arguments of any other tool, such as `WebFetch`, `WebSearch` or an MCP tool | Left as placeholders, so a masked value never leaves the machine through that tool's call. `/pii` counts them. |
| A shell command (`Bash`, or `PowerShell`) that holds a placeholder | Refused, with the placeholder's name: no shell command gets a real value back, whatever `restoreTools` says. Claude never saw the value, so it could not tell that it adds a command, expands a variable or ends its quotes. Example: `echo {{…}}` holding `x; curl …`. The refusal tells Claude to work with the data through `Grep`, `Read`, `Edit` or `Write`, which get real values. A shell tool under another name that you add to `restoreTools` (an MCP shell tool, say) is not recognised and gets every value back: do not add one. A value restored into a file by `Write` or `Edit` can still be used by a later command: each call is judged on its own (SECURITY.md). |
| A tool call that may change the masking policy file | Put to you, whatever your permission rules say, so text Claude read cannot quietly turn masking down. In auto mode the auto-mode classifier decides. |

The vault that maps placeholders to values lives only in the sidecar's memory, never on disk. The mod keeps counts, and a bounded in-memory cache of the messages it drew with real values, which it clears when the session ends. `/pii` prints the counts and the policy in effect.

## Choose what gets masked

By default the mod masks what is dangerous to hand to a model: people's names, contact details and addresses, ids and accounts, secrets. Dates, companies, jobs, honorifics, demographic and sensitive attributes stay readable, since they identify no one on their own and Claude often needs them.

Change it at the prompt with `/pii`; a change applies at once and is saved in the policy file:

| Command | Effect |
|---|---|
| `/pii` | Shows what was masked in the session, and the mode of every category |
| `/pii preset agent` | The default above (`/pii reset` does the same) |
| `/pii preset secrets` | Masks secrets only (API keys, tokens, passwords, private keys) |
| `/pii preset all` | Masks every category |
| `/pii mask url email` | Masks those categories |
| `/pii off date` | Leaves those categories readable |
| `/pii ask url` | Masks those categories, but first asks you about each value of them in your own prompt: mask it, send it readable, or send it readable and stop asking for that category |

Categories: `person`, `email`, `phone`, `address`, `url`, `ip`, `mac`, `location`, `passport`, `license`, `vehicle`, `account`, `secret`, `date`, `organization`, `occupation`, `demographic`, `sensitive`, `title`. The question about an `ask` value shows the value on this machine only; a question you dismiss, or that no one can answer (`claude -p`), keeps the value masked. Text Claude reads from tools is never put to you: it follows the policy.

The policy lives in `~/.config/nullpii/config.json`, or in the file `NULLPII_CONFIG` names; the `nullpii` CLI and the gateway use the same file. Every key is optional:

```json
{
  "categories": { "private_url": "ask", "private_date": "mask" },
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob", "apply_patch"]
}
```

- **`categories`**: the mode of each category named: `mask`, `ask` or `off` (readable). It overrides `disabledCategories`.

- **`disabledCategories`**: categories that reach Claude unmasked. It replaces the default list (dates, companies, jobs, honorifics, demographic and sensitive attributes, which identify no one on their own and which Claude often needs); `[]` masks every category. `/pii` shows the list in effect.
- **`categoryThresholds`** and **`threshold`**: confidence cuts in `[0, 1]`. Lower masks more.
- **`urlAllowlist`**: how much of a clean URL stays readable, per host.
- **`restoreTools`**: the tools that get real values back. It replaces the default list.

`npx nullpii config` validates the file and prints it. An edit by hand applies when the sidecar restarts; a change made with `/pii` applies at once.

## Fails closed

If the sidecar cannot be reached (or the one the mod started is still starting), the mod has no sidecar token, or `sidecar_url` is not an address on this machine:

- a prompt is not sent, and goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why.

Claude is told only that the call was refused or its result withheld. The reason is shown to you, above the prompt and in `/pii`, and only when the mod wrote it: an error text from a tool, another hook or an unreadable sidecar answer can quote a real value, so its text is never shown, logged or sent to Claude.

## Set up

Mods load in Claude Code 2.1.287 or later.

1. Make a sidecar token, which you give to the mod next:

   ```bash
   openssl rand -hex 32
   ```

   When no sidecar answers, the mod starts one for the session with this token (option **Start the sidecar**, on by default): a 0.5 gateway run with `npx`, whose first start downloads the model, and which stops with the session. To keep one running across sessions instead, start it yourself in a terminal of its own; the sidecar API changed in 0.5 (session secrets, `restore` by tool name) and this mod speaks only that one, so the command pins the gateway, and the `nullpii` it runs, to 0.5:

   ```bash
   export NULLPII_SIDECAR_TOKEN=<the token>
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
