# nullpii mod for Claude Code

A [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) that masks personal data and secrets before Claude reads them. Every prompt and every tool result goes through a local nullpii sidecar first. Names, emails, phone numbers, keys and similar values reach the model as placeholders, such as `{{PII_PRIVATE_EMAIL_0_…}}`.

A band above the prompt shows what was masked in the session, by type:

```text
nullpii · 12 masked (person 5 · email 3 · secret 2 · phone 2) · 4 restored to local tools
```

Status: preview. Tested with Claude Code 2.1.305, the version CI tests with.

## What it does

| Where | What happens |
|---|---|
| Your prompt | Masked before it is sent. Your prompt history stores the masked text. |
| Your prompts and Claude's replies on screen | Drawn with the real values. What Claude reads keeps the placeholders. In `claude -p` output, replies keep the placeholders. |
| A tool result (file contents, command output, search results, MCP results) | Masked before Claude reads it |
| Text a hook adds for Claude after a tool result (for example the context of a `PostToolUse` hook in your settings) | Passed on when it holds no personal data. Otherwise the whole result is withheld, because Claude Code does not let a mod rewrite that text. |
| Text Claude Code adds on its own: @-mentioned files, edited-file reminders, memory, `CLAUDE.md`, your account email | Masked before Claude reads it |
| Arguments of a tool in the policy's `restoreTools` (by default the file tools that run on this machine: Claude Code's `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Grep`, `Glob`, and the `apply_patch` tool of other agents) | Placeholders get their real values back before the tool runs, in the arguments that carry data (for `Grep`: `pattern`, `path` and `glob`). So file reads, searches and edits use your real data. The result is masked again. |
| Arguments of any other tool, such as `WebFetch`, `WebSearch` or an MCP tool | Left as placeholders, so a masked value never leaves the machine through that tool's call. `/pii` counts them. |
| A shell command (`Bash` or `PowerShell`) that holds a placeholder | Refused, with the placeholder's name. No shell command gets a real value back, whatever `restoreTools` says. Claude never saw the value, so it cannot tell if the value adds a command, expands a variable or ends its quotes (for example `echo {{…}}` holding `x; curl …`). The refusal tells Claude to work with the data through `Grep`, `Read`, `Edit` or `Write`, which get real values. If you add a shell tool under another name to `restoreTools` (an MCP shell tool, say), the mod does not recognise it and gives it every value, so do not add one. A value restored into a file by `Write` or `Edit` can still be used by a later command, because each call is judged on its own (SECURITY.md). |
| A tool call that may change the masking policy (a write to its file, or a command naming the sidecar's policy route) | Put to you for approval, whatever your permission rules say. In auto mode, the auto-mode classifier decides. |
| A policy change this session did not make: another session's `/pii`, a command holding the sidecar token, a hand edit the sidecar loaded at a restart, a change made between sessions | Caught before anything is masked or restored under it. The sidecar refuses the session's calls until the mod has asked you (a call that was running when the policy changed is refused too). You keep the change, or the previous policy is put back. The previous policy is also put back when no one can answer (`claude -p`). So text Claude read cannot quietly turn masking down. |

The mod adds a short section to Claude's system prompt. It says what the placeholders are, that Claude should use them as they are, and which tools get real values. Without it, Claude asks you for the values it cannot see.

The vault that maps placeholders to values lives only in the sidecar's memory, never on disk. The mod keeps counts, and a limited in-memory cache of the messages it drew with real values. It clears that cache when the session ends. `/pii` prints the counts and the policy in effect.

## Choose what gets masked

By default the mod masks what is risky to give to a model: people's names, contact details and addresses, ids and accounts, secrets. Dates, companies, jobs, honorifics, and demographic and sensitive attributes stay readable: they rarely identify someone on their own, and Claude often needs them. Health, religion or sexual orientation written in your prompt therefore reaches the model; `/pii mask sensitive` changes that.

Change it at the prompt with `/pii`. A change applies at once and is saved in the policy file:

| Command | Effect |
|---|---|
| `/pii` | Shows what was masked in the session, and the mode of every category |
| `/pii preset agent` | The default above (`/pii reset` does the same) |
| `/pii preset secrets` | Masks secrets only (API keys, tokens, passwords, private keys) |
| `/pii preset all` | Masks every category |
| `/pii mask url email` | Masks those categories |
| `/pii off date` | Leaves those categories readable |
| `/pii ask url` | Masks those categories, but first asks you about each value of them in your own prompt: mask it, send it readable, or send it readable and stop asking for that category |

Categories: `person`, `email`, `phone`, `address`, `url`, `ip`, `mac`, `location`, `passport`, `license`, `vehicle`, `account`, `secret`, `date`, `organization`, `occupation`, `demographic`, `sensitive`, `title`. When the mod asks about an `ask` value, it shows the value on this machine only. If you dismiss the question, or no one can answer it (`claude -p`), the value stays masked. The mod never asks about text Claude reads from tools: that text follows the policy.

The policy lives in `~/.config/nullpii/config.json`, or in the file that `NULLPII_CONFIG` names. The `nullpii` CLI and the gateway use the same file. Every key is optional:

```json
{
  "categories": { "private_url": "ask", "private_date": "mask" },
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob", "apply_patch"]
}
```

- **`categories`**: a mode for each category you name: `mask`, `ask` or `off` (readable). It wins over `disabledCategories`.

- **`disabledCategories`**: the categories that reach Claude unmasked. It replaces the default list (dates, companies, jobs, honorifics, and demographic and sensitive attributes). `[]` masks every category. `/pii` shows the list in effect.
- **`categoryThresholds`** and **`threshold`**: confidence cuts between 0 and 1. Lower masks more.
- **`urlAllowlist`**: how much of a clean URL stays readable, per host.
- **`restoreTools`**: the tools that get real values back. It replaces the default list.

`npx nullpii config` checks the file and prints it. An edit by hand applies when the sidecar restarts. A change made with `/pii` applies at once.

## While nullpii starts

The first start of a sidecar the mod starts takes a while: it installs packages and downloads the model (1.2 GB). The band says which phase it is in, with the download's progress, and its padlock is amber and open. A prompt you send meanwhile asks you first:

- **Wait for nullpii**: the prompt is held, and sent masked as soon as the band says nullpii is on. If it is not on within 5 minutes, or the start fails, the prompt goes back into the prompt box with the reason;
- **Send it now, unprotected**: this prompt reaches Claude as you typed it;
- **Send now, and do not ask again until nullpii is ready**: every prompt of this start-up does, with the band saying `not protected yet`.

The option **While nullpii starts** (`while_starting`) sets this: `ask` (the default), `block` (always wait, as above) or `pass` (always send unprotected). Text the engine adds, such as file contents Claude reads, goes out unprotected too while you chose to send unprotected. What was sent before nullpii was ready stays in the conversation as it was, so do not send personal data that way. Dismissing the dialog, or a run no one can answer (`claude -p`), waits.

## Fails closed

The mod blocks when the sidecar cannot be reached (or the one it started is still starting), when it has no sidecar token, or when `sidecar_url` is not an address on this machine:

- a prompt is not sent. It goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why.

Claude is told only that the call was refused or its result withheld. You see the reason, above the prompt and in `/pii`, but only when the mod wrote it. An error text from a tool, another hook or an unreadable sidecar answer can quote a real value, so the mod never shows, logs or sends that text to Claude.

## Set up

Mods load in Claude Code 2.1.287 or later.

1. Make a sidecar token, which you give to the mod next:

   ```bash
   openssl rand -hex 32
   ```

   When no sidecar answers, the mod starts one for the session with this token (option **Start the sidecar**, on by default). It runs the 0.5.0 gateway, `nullpii` and the ONNX runtime at exact versions, with `npx`, from the file system root, so a repository's `.npmrc` does not choose the registry they come from. Its first start downloads the model, and it stops with the session. To keep one sidecar running across sessions instead, start it yourself in its own terminal. The sidecar API changed in 0.5 (session secrets, `restore` by tool name, policy versions), and this mod speaks only that version, so the command pins the gateway, the `nullpii` it runs, and the runtime:

   ```bash
   export NULLPII_SIDECAR_TOKEN=<the token>
   npx -p nullpii@0.5.0 -p onnxruntime-node@1.30.0 -p @lbroth/nullpii-gateway@0.5.0 nullpii-gateway
   ```

2. Install the mod. At the prompt of a Claude Code session in a terminal:

   ```text
   /plugin marketplace add lBroth/nullpii@v0.5.0
   /plugin install nullpii@nullpii
   ```

   `@v0.5.0` pins the marketplace, and so the mod, to the release tag. This mod sees every prompt and tool result, so install a release, not whatever `main` holds. Read the plugin's details and pick a scope (**Install for you** puts it in every project on this machine). Claude Code then asks for the plugin's options. Paste the token from step 1 into **Sidecar token**. Keep the default **Sidecar URL** unless the gateway listens on another port. The dialog hides the token and keeps it in your system's secure storage, and Claude Code does not pass it to the commands Claude runs.

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

Every command Claude runs in that shell inherits the token. The token alone reads nothing: each sidecar session also has a secret, which the sidecar gives to the mod when the session opens and which the mod keeps in memory only. A command with just the token cannot read, restore or close your session. It can replace the policy (`PUT /v1/sidecar/policy`), and the mod then asks you about the change before anything runs under it (see the table above).

The `sidecar_url` option sets the sidecar address (default `http://127.0.0.1:8787`). It must be `http://` on `127.0.0.1` or `[::1]`, the literal address the gateway listens on (127.0.0.1 by default), with an optional port and nothing after it. `localhost` is refused: it can resolve to the other loopback address, where another local process could relay the sidecar's check to the real gateway and then receive the token. The mod sends its token and every unmasked prompt to that address, and the sidecar answers only on this machine. So any other address is refused, and the mod blocks until the option is fixed. The address comes only from the option, never from the environment: plugin options are read only from your user settings (or your organization's managed settings), while a repository's `.claude/settings.json` can set environment variables. If both are set, the option wins over `NULLPII_SIDECAR_TOKEN` for the token.

Before every request, the mod checks that the process at that address holds the same token, without sending it: it asks for a signature of a fresh random nonce (`POST /v1/sidecar/challenge`). Another process that took the port, for example while the gateway was stopped, cannot answer. It receives neither the token nor any text, and the mod blocks. A process that takes the port between the check and the request (one local round trip) is not covered.

## Limits

- **Each call is judged on its own.** A real value restored into one call (a file that `Write` writes, a commit) can leave the machine through a later call that holds no placeholder, such as `git push` or `curl -d @file`. See SECURITY.md.
- **Claude Code's own system prompt is not masked.** The mod masks prompts, tool results, attachments and `CLAUDE.md`. The sections Claude Code writes itself reach Claude as they are, such as the working directory (which can hold your user name) and the git status (author names, recent commit subjects). The gateway masks the whole request, system prompt included.
- **A repository's settings outrank yours.** Its `.claude/settings.json` can turn the mod off, add hooks that see prompts before it does, or set environment variables for the sidecar the mod starts (npm's registry among them). Your organization's managed settings can force the mod on.
- **The policy guard is best effort.** It catches a file tool that writes any `…/nullpii/config.json` (in any case, with `./`, `../` and repeated separators resolved, and relative paths taken from the session's directory) or the loaded policy file. It also catches a shell command that names a `nullpii` directory together with a `config.json`, `NULLPII_CONFIG`, or the sidecar's policy route. It does not catch a command that reaches the policy another way (a variable, a symlink, a script it runs), or an MCP tool that writes files. A change sent to the sidecar applies at once, and the mod asks you about it before its next call. A file edit applies at the next sidecar start, and the mod asks you about it if a session is open then. Between sessions, the mod compares the policy with the one it last made or accepted, which it keeps in its plugin store (a file owned by your user, so this check is also best effort against your own processes). It asks you about a change when the next session opens, and puts the old policy back when no one can answer. So change the policy in an interactive session: with `/pii`, or by hand followed by one. `/pii` reads the policy again before it shows it.
- **Permission rules see the masked call.** Claude Code applies your permission rules, or asks you, before the mod puts the real values back. A rule that names a value nullpii masks, such as a path with your user name (`Read(/Users/<name>/.ssh/**)`), may not match. Write it without that part (`Read(**/.ssh/**)`). After the restore, only the policy-file guard is checked again.
- **Auto mode.** Claude Code denies a tool call whose arguments a hook changed after the model wrote them. So in auto mode, a local tool call that contains a placeholder is refused. Calls without placeholders pass unchanged and run normally.
- **Tool rows and tool results on screen show placeholders.** Prompts and replies are drawn with real values. If the sidecar is unreachable, they show placeholders too.
- **An organization's managed settings come first.** Where Claude Code is managed, the organization's hooks run before this mod's, and can stop it from loading or override what it decides. A mod that never loads cannot block anything: prompts then go out unmasked. If `/pii` does not answer, the mod is not running.
- **Images and other binary attachments are not scanned.**
- **Claude Code's session files keep @-mentioned files as they are.** Claude Code writes an @-mentioned file to the session file under `~/.claude/projects` before the mod masks it, so that copy holds the real values, on this machine. What Claude reads is masked. Your prompts and tool results are stored masked.
- **`claude -p` needs a running sidecar.** A sidecar the mod starts cannot answer before the prompt goes, so the prompt is not sent. Start nullpii-gateway yourself first (step 1 of Set up).
- **Very long text can time out.** Masking a text over 1,000,000 characters takes minutes on CPU (about 25 seconds per 100,000 characters). If it takes longer than Claude Code waits, the mod withholds the text, so nothing is sent unmasked, and says the sidecar took too long.
- **Detection is statistical.** nullpii's leak rate is measured and published, and it is not zero. This is pseudonymisation with a measured leak rate, not anonymisation.
- **A placeholder from an expired sidecar session** (idle longer than `NULLPII_VAULT_TTL_MS`, or a sidecar restart) no longer restores. It stays a placeholder.

## Develop

```bash
claude plugin validate .   # what Claude Code reads from the mod
claude plugin test         # tests, with a fake sidecar; no session or network
```

License: Apache-2.0.
