# nullpii mod for Claude Code

A [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) that masks personal data and secrets before Claude reads them. Every prompt and every tool result goes through a local nullpii sidecar first, so names, emails, phone numbers, keys and similar values reach the model as placeholders such as `{{PII_PRIVATE_EMAIL_0_…}}`.

A band above the prompt shows what was masked in the session, by type:

```text
nullpii · 12 masked (person 5 · email 3 · secret 2 · phone 2) · 4 restored to local tools
```

Status: preview. Tested with Claude Code 2.1.302.

## What it does

| Where | What happens |
|---|---|
| Your prompt | Masked before it is sent. Your prompt history stores the masked text. |
| Your prompts and Claude's replies on screen | Drawn with the real values. What Claude reads keeps the placeholders. |
| A tool result (file contents, command output, search results, MCP results) | Masked before Claude reads it |
| Text Claude Code adds on its own: @-mentioned files, edited-file reminders, memory, `CLAUDE.md`, your account email | Masked before Claude reads it |
| Arguments of a tool that runs on this machine (`Bash`, `Read`, `Edit`, `Write`, `NotebookEdit`, `Grep`, `Glob`) | Placeholders get their real values back before the tool runs, so commands and file edits use your real data. The result is masked again. |
| Arguments of a tool that sends data elsewhere (`WebFetch`, `WebSearch`, MCP tools) | Left as placeholders, so a masked value never leaves the machine through a tool call |
| A shell command whose real value the shell would interpret where it stands | Refused, with the placeholder's name. Claude never saw the value, so it could not tell that it adds a command, expands a variable or ends its quotes. Example: `echo {{…}}` holding `x; curl …`. The same value inside single quotes is literal and is restored. A value inside command substitution (`$(…)`, backticks) counts as unquoted. In a heredoc with a quoted delimiter (the `git commit -m "$(cat <<'EOF' …)"` form) any value without a newline is restored. When the command hands code to another interpreter (`bash -c`, `eval`, `ssh`, `python -c`, `node -e`, …), only plain words are restored. |

The vault that maps placeholders to values lives only in the sidecar's memory, never on disk. The mod keeps counts, and a bounded in-memory cache of the messages it drew with real values, which it clears when the session ends. `/pii` prints the counts.

## Fails closed

If the sidecar cannot be reached, or `NULLPII_SIDECAR_TOKEN` is not set:

- a prompt is not sent, and goes back into the prompt box with the reason;
- a tool call is refused, or its result is withheld;
- an attachment such as an @-mentioned file is left out, and the first message's context (`CLAUDE.md`, your email) is sent empty;
- the band turns red and says why.

## Set up

1. Start the gateway with the sidecar API on:

   ```bash
   export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
   npx -p nullpii -p @lbroth/nullpii-gateway nullpii-gateway
   ```

2. Start Claude Code from the same shell, so it inherits the token, and load the mod:

   ```bash
   claude --plugin-dir ./packages/claude-code-mod
   ```

`NULLPII_SIDECAR_URL` overrides the sidecar address (default `http://127.0.0.1:8787`).

## Limits

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
