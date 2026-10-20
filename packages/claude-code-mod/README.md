# nullpii mod for Claude Code

A [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) that masks personal data and secrets before Claude reads them. Every prompt and every tool result goes through a local nullpii sidecar first, so names, emails, phone numbers, keys and similar values reach the model as placeholders such as `{{PII_PRIVATE_EMAIL_0_…}}`.

A band above the prompt shows what was masked in the session, by type:

```text
nullpii · 12 masked (person 5 · email 3 · secret 2 · phone 2) · 4 restored to local tools
```

Status: preview. Tested with Claude Code 2.1.303.

## What it does

| Where | What happens |
|---|---|
| Your prompt | Masked before it is sent. Your prompt history stores the masked text. |
| Your prompts and Claude's replies on screen | Drawn with the real values. What Claude reads keeps the placeholders. |
| A tool result (file contents, command output, search results, MCP results) | Masked before Claude reads it |
| Text a hook attaches for Claude after a tool result (for example a settings `PostToolUse` hook's context) | Passed on when it holds no personal data. Otherwise the whole result is withheld: Claude Code does not let a mod rewrite that text, so it cannot be masked. |
| Text Claude Code adds on its own: @-mentioned files, edited-file reminders, memory, `CLAUDE.md`, your account email | Masked before Claude reads it |
| Arguments of a tool in the policy's `restoreTools` (by default the tools that run on this machine: `Bash`, `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`, `Grep`, `Glob`) | Placeholders get their real values back before the tool runs, so commands and file edits use your real data. The result is masked again. |
| Arguments of any other tool, such as `WebFetch`, `WebSearch` or an MCP tool | Left as placeholders, so a masked value never leaves the machine through a tool call. `/pii` counts them. |
| A shell command whose real value the shell would interpret where it stands, or a command that sends data out (`curl`, `wget`, `nc`, `ssh`, `git push`, …) | Refused, with the placeholder's name. Claude never saw the value, so it could not tell that it adds a command, expands a variable or ends its quotes. Example: `echo {{…}}` holding `x; curl …`. The sidecar applies the gateway's rule (SECURITY.md), so the mod and the proxy decide the same way. It covers quotes, `#` comments, command substitution, heredocs (including one written to a script that the same command runs), commands that hand code to another interpreter, and network clients. A value restored into a file by `Write` or `Edit` can still be run by a later command: the rule judges each call on its own. |
| A tool call that may change the masking policy file | Put to you, whatever your permission rules say, so text Claude read cannot quietly turn masking down. In auto mode the auto-mode classifier decides. |

The vault that maps placeholders to values lives only in the sidecar's memory, never on disk. The mod keeps counts, and a bounded in-memory cache of the messages it drew with real values, which it clears when the session ends. `/pii` prints the counts and the policy in effect.

## Choose what gets masked

The sidecar reads the masking policy from `~/.config/nullpii/config.json`, or from the file `NULLPII_CONFIG` names, when it starts. The `nullpii` CLI and the gateway use the same file. Every key is optional:

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Bash", "Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob"]
}
```

- **`disabledCategories`**: categories that reach Claude unmasked.
- **`categoryThresholds`** and **`threshold`**: confidence cuts in `[0, 1]`. Lower masks more.
- **`urlAllowlist`**: how much of a clean URL stays readable, per host.
- **`restoreTools`**: the tools that get real values back. It replaces the default list.

`npx nullpii config` validates the file and prints it. Restart the sidecar after a change; `/pii` then shows the new policy. You can also ask Claude, for example "stop masking company names". The plugin's `nullpii-policy` skill tells Claude how to edit the file safely, and the edit is put to you before it is written.

## Fails closed

If the sidecar cannot be reached, or the mod has no sidecar token:

- a prompt is not sent, and goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why.

## Set up

1. In a terminal of its own, start a gateway with the sidecar API on (a version with session secrets, whose `restore` takes `tool`):

   ```bash
   export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
   echo "$NULLPII_SIDECAR_TOKEN"   # you give this to the mod next
   npx -p nullpii -p @lbroth/nullpii-gateway nullpii-gateway
   ```

2. Give the mod the same token through its `sidecar_token` option. For an installed plugin, run `/plugin configure` on it: the dialog masks the value and keeps it in your system's secure storage, and Claude Code does not pass it to the commands Claude runs. For a session started with `--plugin-dir`, you can instead export `NULLPII_SIDECAR_TOKEN` in the shell that starts Claude Code:

   ```bash
   claude --plugin-dir ./packages/claude-code-mod
   ```

   A token in that shell's environment is inherited by every command Claude runs there. On its own it reads nothing: each sidecar session also has a secret, which the sidecar hands to the mod when the session opens and which the mod keeps in memory only. A command holding just the token cannot read, restore or close your session.

The `sidecar_url` option, or `NULLPII_SIDECAR_URL`, sets the sidecar address (default `http://127.0.0.1:8787`).

## Limits

- **The policy guard is best effort.** It recognises a file tool writing any `…/nullpii/config.json` (whatever the case, with `./`, `../` and repeated separators resolved, and relative paths taken from the session's directory) or the loaded policy file, and a shell command that names a `nullpii` directory together with a `config.json`, or `NULLPII_CONFIG`. A command that reaches the file another way (a variable, a symlink, a script it runs), or an MCP tool that writes files, is not caught. The change still needs a sidecar restart, and `/pii` shows the policy the sidecar loaded.
- **Auto mode.** Claude Code denies a tool call whose arguments a hook changed after the model wrote them. A local tool call that contains a placeholder is therefore refused in auto mode. Calls without placeholders are passed on unchanged and run normally.
- **Tool rows and tool results on screen show placeholders.** Prompts and replies are drawn with real values. If the sidecar is unreachable, they show placeholders too.
- **Images and other binary attachments are not scanned.**
- **Detection is statistical.** nullpii's leak rate is measured and published, and it is not zero. Treat this as pseudonymization with a measured leak rate, not anonymization.
- **A placeholder from an expired sidecar session** (idle longer than `NULLPII_VAULT_TTL_MS`, or a sidecar restart) no longer restores, and stays a placeholder.

## Develop

```bash
claude plugin validate .   # what Claude Code reads from the mod
claude plugin test         # tests, with a fake sidecar; no session or network
```

License: Apache-2.0.
