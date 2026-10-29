# nullpii mod for Claude Code

A [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) that masks personal data and secrets before Claude reads them. Every prompt and every tool result goes through a local nullpii sidecar first. Names, emails, phone numbers, keys and similar values reach the model as placeholders, such as `{{PII_PRIVATE_EMAIL_0_…}}`.

One small place, and only the room the state needs. A line under the prompt always shows the state in a few characters, with a padlock glyph so it reads without colour (`🔒 8`, a padlock and how many values it has masked so far, rising as it works; `🔓 paused`, `⏳ starting · downloading the model 54%`, `⚠ not protected yet`, `⚠ blocking`; Claude Code writes `nullpii:` in front, so the name is never repeated there). While nullpii is on and nothing needs saying, that line is the only thing the mod draws. A band above the prompt appears only when you have something to know or do:

```text
12 masked (person 5 · email 3 · secret 2 · phone 2) · 4 restored to local tools
```

The band is drawn while nullpii starts, while a prompt of that start goes out unprotected, while masking is paused, while a policy change is waiting for your word, and while the mod blocks (there it says why, in red). Its button turns masking off and on at once. It has no hotkey of its own, so a bare key in an empty prompt never pauses masking. While the band is not drawn, `/pii pause` and the `/pii` menu pause and resume: the pause still asks you first, and still only comes from your own run.

Status: preview. Tested with Claude Code 2.1.305, the version CI tests with.

## What it does

| Where | What happens |
|---|---|
| Your prompt | Masked before it is sent. Your prompt history stores the masked text. |
| Your prompts and Claude's replies on screen | Drawn with the real values. What Claude reads keeps the placeholders, except a value you send in clear (*Ask before a value leaves*). In `claude -p` output, replies keep the placeholders. |
| A tool result (file contents, command output, search results, MCP results) | Masked before Claude reads it |
| An object key of a tool result that itself holds personal data (a field name like `John Smith`, or a key like `john@example.io`) | Masked like a value. A key Claude reads in its masked form can make Claude Code reject the result against the tool's schema, so for the result of any tool outside `restoreTools` the mod asks you before the result reaches Claude: send the keys in clear (the values under them stay masked), or the whole result is withheld. The result of a tool in `restoreTools`, and of Claude's own `AskUserQuestion` (keyed by the question Claude wrote, with its placeholders), goes to Claude with its keys masked, with no question. See *Ask before a value leaves*. |
| Text a hook adds for Claude after a tool result (for example the context of a `PostToolUse` hook in your settings) | Passed on when it holds no personal data. Otherwise the whole result is withheld, because Claude Code does not let a mod rewrite that text. |
| Text Claude Code adds on its own: @-mentioned files, edited-file reminders, memory, `CLAUDE.md`, your account email | Masked before Claude reads it |
| Arguments of a tool in the policy's `restoreTools` (by default the file tools that run on this machine: Claude Code's `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Grep`, `Glob`, and the `apply_patch` tool of other agents) | Placeholders get their real values back before the tool runs, in the arguments that carry data (for `Grep`: `pattern`, `path` and `glob`). So file reads, searches and edits use your real data. The result is masked again. |
| Arguments of any other tool: `WebFetch`, `WebSearch`, an MCP tool, Claude Code's own tools (`TodoWrite`, `Agent`, `AskUserQuestion`, `ExitPlanMode`, …), any tool the mod does not know | When they hold placeholders for values this session masked, the mod asks you before the call runs: the tool gets a real value through its placeholder only on your word, otherwise the call is not run. Once sent, a value is plain text where it went: a subagent (`Agent`, `Task`) can pass it to any tool, a shell command included, with no further question, since the mod checks placeholders only. **With no one to answer (`claude -p`, or a dismissed dialog), every such call is refused unless you chose Allow all earlier in the session**, so a `claude -p` run whose todo list or subagent prompt holds a placeholder stops there. A placeholder nothing stands behind (an earlier session's, or one typed by hand) is left as written, with no question. `/pii` counts the placeholders left in calls that ran. |
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
| `/pii` | Opens the menu: each entry is one of the commands below, and picking it runs what typing it runs |
| `/pii status` | Shows what was masked in the session, and the mode of every category |
| `/pii doctor` | Checks the sidecar and token proof, pinned releases and model, actual backend, token, policy and mod state; every failure includes its fix |
| `/pii try <text>` | Previews masking under the current policy, locally in a random throwaway sidecar session; shows the sanitized text and counts by type, then closes that session |
| `/pii preset agent` | The default above (`/pii reset` does the same) |
| `/pii preset secrets` | Masks secrets only (API keys, tokens, passwords, private keys) |
| `/pii preset all` | Masks every category |
| `/pii mask url email` | Masks those categories |
| `/pii allow date` | Leaves those categories readable |
| `/pii ask url` | Masks those categories, but first asks you about each value of them in your own prompt: mask it, send it readable, or send it readable and stop asking for that category |
| `/pii reset` | Back to the default preset |
| `/pii pause` | Pauses masking for this session, after asking you first |
| `/pii resume` | Turns masking back on (the band's on/off button does the same, while the band is drawn) |
| `/pii help` | Lists every command and what it does |

`/pii try` sends the sample only to the verified local sidecar, never to the conversation's sidecar session. Before Claude Code stores the command, the mod rewrites its arguments to the sanitized sample; on any failure it stores a fixed redaction instead. The menu's `try` entry only explains this typed form and never collects a sample in a dialog. If the policy masks nothing in a sample, its sanitized form is the same text.

Categories: `person`, `email`, `phone`, `address`, `url`, `ip`, `mac`, `location`, `passport`, `license`, `vehicle`, `account`, `secret`, `date`, `organization`, `occupation`, `demographic`, `sensitive`, `title`. When the mod asks about an `ask` value, it shows the value on this machine only. If you dismiss the question, or no one can answer it (`claude -p`), the value stays masked. The mod never asks about text Claude reads from tools: that text follows the policy, except where *Ask before a value leaves* says.

`/pii` with no arguments shows the menu instead of the status: the state, the presets, `mask`/`ask`/`allow` for a category (one page of categories at a time, `More categories…` for the next), and pause, reset and help. Every entry carries the line `/pii help` prints for it, and every entry runs the command it names, guards included: only your own `/pii pause` can pause masking, and a change that masks less is still put to you with its values. Where the menu cannot be answered (a `claude -p` run, a dismissed dialog), `/pii` prints the status and the help instead, as it printed the status before the menu.

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

## Ask before a value leaves

For every tool outside `restoreTools` — `WebFetch`, `WebSearch`, MCP tools, Claude Code's own tools such as `TodoWrite`, `Agent` or `AskUserQuestion`, and any tool the mod does not know — the mod asks you before a value it masked goes out in clear, in one dialog with three answers:

- **Block**: the result is withheld from Claude, or the call is not run. Claude is told that nullpii withheld or refused it. A dismissed dialog, or a run no one can answer (`claude -p`), is this answer.
- **Send once**: the keys or values the question lists go out in clear, this one time, and nothing else: a placeholder the question did not list stays as written.
- **Allow all**: Send once, and every later question of the session is answered the same way, with no dialog. It ends with the session.

**In `claude -p`, no one can answer**: every call to a tool outside `restoreTools` that holds a placeholder for a value the session masked is refused, Claude Code's own tools included (a todo list, a subagent prompt, a plan), and so is every result of such a tool whose object keys were masked. A shell command is refused there as everywhere. Only a tool in `restoreTools` gets its values.

The question says where the values go, as far as the mod knows:

- `WebFetch` and `WebSearch` run through a Claude model (`WebSearch` searches server-side; `WebFetch` hands the page and your prompt to a model), so a value sent to them reaches that model, and `WebFetch` also sends its URL to the site it names.
- An MCP tool (`mcp__…`): the values go to the MCP server that runs it, and can leave this machine through that server.
- `AskUserQuestion`, Claude's own question to you: the values are shown to you in the question, on this machine. Your answer goes back to Claude masked, with no second question about the result's keys, so the answer is never lost: the questions the result echoes and the keys of your answers are put back, whole, to the text Claude wrote, without relying on the sidecar finding the value again (a short value, or one joined to a word, it may miss). A result that still holds a sent value in a text Claude did not write, outside your own answers, is withheld.
- Claude Code's other own tools (`TodoWrite`, `Agent`, `Task`, `ExitPlanMode`, `SendMessage`, `Skill`): the tool gets the values. The mod masks what the tool returns, but it has no hook on what the tool hands on inside Claude Code — a subagent's prompt for `Agent` or `Task`, a message for `SendMessage` — so the values can reach a Claude model unmasked. A subagent then holds them as plain text, not placeholders, and can pass them to any tool, a shell command included, with no further question.
- Any other tool: the mod does not know where it sends them; it masks what the tool returns, nothing else.

The mod asks in two places:

- **A result whose object keys were masked**, from a tool outside `restoreTools` other than `AskUserQuestion`. A key can itself hold personal data — a field name like `John Smith`, or a key like `john@example.io`. The question names the tool, and each value the keys hold once, by its own category and short form (the whole value when it has 10 characters or fewer, else its first 3 and last 4): a key like `John <john@example.io>` lists a person and an email, and a key that comes back in many entries is listed once. Send once or Allow all puts the original keys back, and Claude reads them as plain text: it can copy them into any later call, a shell command included, with no further question. The values under them stay masked. Block withholds the whole result. A result whose values alone were masked goes to Claude as before, with no question.
- **A call to a tool outside `restoreTools` that holds placeholders for values this session masked.** The question names the tool, where the values would go, and per value its category and a short form. Send once or Allow all puts back exactly the values the question listed and runs the call, through the policy-file guard as any call the restore path rewrites. Block refuses the call. A placeholder nothing stands behind — an earlier session's, or one typed by hand — is left as it is, and the call runs as written.

A shell command is never asked: its refusal stands. A tool in `restoreTools` gets its values back with no question. The mod's own dialogs are never asked about.

The short forms appear only on this machine: in the dialog, as the `ask` mode shows a value, and in the toasts. Each value sent in clear, in a call or in a key, gets a toast — the tool, the category, and the short form — so an Allow-all send is still seen; it is shown once the call has been handed on, not when a refusal comes back to the mod after your answer (the policy-file guard, a hook below it, or Claude Code denying the rewritten call). `/pii` counts them by tool and category, one line each (`Sent in clear on your word: WebFetch · email 1`), and never shows a value or a short form: its text may reach the model. In auto mode, a Send-once call is refused like any rewritten call (see Limits).

## While nullpii starts

The first start of a sidecar the mod starts takes a while: it installs packages and downloads the model (1.2 GB). The band and the line under the prompt say which phase it is in, with the download's progress, and the band's padlock is amber and open. A prompt you send meanwhile asks you first:

- **Wait for nullpii**: the prompt is held, and sent masked as soon as the band says nullpii is on. If it is not on within 5 minutes, or the start fails, the prompt goes back into the prompt box with the reason;
- **Send it now, unprotected**: this prompt reaches Claude as you typed it;
- **Send now, and do not ask again until nullpii is ready**: every prompt of this start-up does, with the band saying `not protected yet`.

The option **While nullpii starts** (`while_starting`) sets this: `ask` (the default), `block` (always wait, as above) or `pass` (always send unprotected). Text the engine adds, such as file contents Claude reads, goes out unprotected too while you chose to send unprotected. What was sent before nullpii was ready stays in the conversation as it was, so do not send personal data that way. Dismissing the dialog, or a run no one can answer (`claude -p`), waits.

## Fails closed

The mod blocks when the sidecar cannot be reached (or the one it started is still starting), when it has no sidecar token, or when `sidecar_url` is not an address on this machine:

- a prompt is not sent. It goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why, and the line under the prompt reads `⚠ blocking`.

Claude is told only that the call was refused or its result withheld. You see the reason, above the prompt and in `/pii`, but only when the mod wrote it. An error text from a tool, another hook or an unreadable sidecar answer can quote a real value, so the mod never shows, logs or sends that text to Claude.

## Set up

Mods load in Claude Code 2.1.287 or later.

1. Make a sidecar token, which you give to the mod next:

   ```bash
   openssl rand -hex 32
   ```

   When no sidecar answers, the mod starts one for the session with this token (option **Start the sidecar**, on by default). It runs the 0.5.4 gateway, `nullpii` and the ONNX runtime at exact versions, with `npx`, from the file system root, so a repository's `.npmrc` does not choose the registry they come from. Its first start downloads the model, and it stops with the session. To keep one sidecar running across sessions instead, start it yourself in its own terminal. The sidecar API changed in 0.5 (session secrets, `restore` by tool name, policy versions), and this mod speaks only that version, so the command pins the gateway, the `nullpii` it runs, and the runtime:

   ```bash
   export NULLPII_SIDECAR_TOKEN=<the token>
   npx -p nullpii@0.5.4 -p onnxruntime-node@1.30.0 -p @lbroth/nullpii-gateway@0.5.4 nullpii-gateway
   ```

2. Install the mod. At the prompt of a Claude Code session in a terminal:

   ```text
   /plugin marketplace add lBroth/nullpii@v0.5.4
   /plugin install nullpii@nullpii
   ```

   `@v0.5.4` pins the marketplace, and so the mod, to the release tag. This mod sees every prompt and tool result, so install a release, not whatever `main` holds. Read the plugin's details and pick a scope (**Install for you** puts it in every project on this machine). Claude Code then asks for the plugin's options. Paste the token from step 1 into **Sidecar token**. Keep the default **Sidecar URL** unless the gateway listens on another port. The dialog hides the token and keeps it in your system's secure storage, and Claude Code does not pass it to the commands Claude runs.

   From a shell, which does not ask for the options:

   ```bash
   claude plugin marketplace add lBroth/nullpii@v0.5.4
   claude plugin install nullpii@nullpii
   ```

   In the desktop app, where `/plugin` does not run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `lBroth/nullpii@v0.5.4`, then **Add plugin**.

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
- **Auto mode.** Claude Code denies a tool call whose arguments a hook changed after the model wrote them. So in auto mode, a local tool call that contains a placeholder is refused, whatever you answer: a Send-once answer puts the values back, and the rewritten call is denied the same way. Calls without placeholders pass unchanged and run normally.
- **Tool rows and tool results on screen show placeholders.** Prompts and replies are drawn with real values. If the sidecar is unreachable, they show placeholders too.
- **An organization's managed settings come first.** Where Claude Code is managed, the organization's hooks run before this mod's, and can stop it from loading or override what it decides. A mod that never loads cannot block anything: prompts then go out unmasked. If `/pii` does not answer, the mod is not running.
- **Images and other binary attachments are not scanned.**
- **Claude Code's session files keep @-mentioned files as they are.** Claude Code writes an @-mentioned file to the session file under `~/.claude/projects` before the mod masks it, so that copy holds the real values, on this machine. What Claude reads is masked. Your prompts and tool results are stored masked.
- **`claude -p` needs a running sidecar.** A sidecar the mod starts cannot answer before the prompt goes, so the prompt is not sent. Start nullpii-gateway yourself first (step 1 of Set up).
- **Very long text can time out.** Masking a text over 1,000,000 characters takes minutes on CPU (about 25 seconds per 100,000 characters). If it takes longer than Claude Code waits, the mod withholds the text, so nothing is sent unmasked, and says the sidecar took too long.
- **Detection is statistical.** nullpii's leak rate is measured and published, and it is not zero. This is pseudonymisation with a measured leak rate, not anonymisation.
- **A placeholder from an expired sidecar session** (idle longer than `NULLPII_VAULT_TTL_MS`, or a sidecar restart) no longer restores. It stays a placeholder.
- **A resumed session does not restore its old placeholders.** The vault ends with the session and is never saved to disk, so after `--resume` or `-c` the placeholders already in the history stay placeholders; a file Claude writes with one holds the placeholder. Files written before are fine, and new data is masked as usual.

## Develop

```bash
claude plugin validate .   # what Claude Code reads from the mod
claude plugin test         # tests, with a fake sidecar; no session or network
```

License: Apache-2.0.
