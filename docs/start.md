---
title: Get started
---

# Get started

nullpii runs inside Claude Code as a mod. It masks personal data and secrets before Claude reads them, and it starts a local nullpii sidecar for you. Set it up in one of two ways: let Claude Code do it, or do it by hand.

You need Claude Code 2.1.287 or later, Node.js 22 or later, and `openssl`. The sidecar's first start downloads the detection model (1.2 GB) into `~/.cache/nullpii/`.

## Let Claude Code set it up

Paste this prompt into a Claude Code session:

<div class="np-prompt">

```text
Install the nullpii mod for Claude Code, release v0.5.3. Run these commands in a shell, one at a time, in this order, exactly as written:

1. node --version
   (If it is older than v22, stop and tell me.)
2. claude plugin marketplace add lBroth/nullpii@v0.5.3
3. claude plugin install nullpii@nullpii --scope user
4. printf '{"sidecar_token":"%s"}' "$(openssl rand -hex 32)" | claude plugin configure nullpii@nullpii --values-stdin

Step 4 makes a new sidecar token and hands it straight to Claude Code, which keeps it in my system's secure storage. Never print, echo or save that token. Do not start the sidecar yourself. When the four steps are done, tell me to restart Claude Code.
```

</div>

Unless your permission settings already allow them, Claude Code asks you before each command. When it is done, quit Claude Code and start it again.

## Or set it up by hand

1. Make a sidecar token:

   ```bash
   openssl rand -hex 32
   ```

2. At the prompt of a Claude Code session in a terminal:

   ```text
   /plugin marketplace add lBroth/nullpii@v0.5.3
   /plugin install nullpii@nullpii
   ```

   Pick a scope: **Install for you** puts the mod in every project on this machine. When Claude Code asks for the plugin's options, paste the token into **Sidecar token** and keep the default **Sidecar URL**.

   In the desktop app, where `/plugin` does not run: click **+** next to the prompt box, then **Plugins**, **Add marketplace** with `lBroth/nullpii@v0.5.3`, then **Add plugin**.

3. Restart Claude Code.

`@v0.5.3` pins the mod to the release. The mod sees every prompt and tool result, so install a release, not whatever `main` holds.

## Check that it works

After the restart, the mod starts the sidecar. The line under the prompt says what nullpii is doing. While the sidecar is starting (the first time, while the model downloads), a prompt you send goes back into the prompt box: send it again once the line under the prompt shows the padlock.

Then send a prompt with a name and an email in it, for example:

```text
Write a short welcome note to John Smith, john@acme.io.
```

::: v-pre
The line under the prompt counts what was masked, and Claude works with placeholders such as `{{PII_PRIVATE_EMAIL_0_…}}`. Your screen still shows the real values. Type `/pii` to see the counts and what each category does.
:::

## Update to a new release

The marketplace is pinned to the release you installed, so `marketplace update` alone stays on it, and adding the new tag fails with:

```text
Cannot add marketplace "nullpii": its source doesn't match its extraKnownMarketplaces entry in user or managed settings
```

To move to a new release, change the pin first. In `~/.claude/settings.json`, set `ref` of the `nullpii` entry to the new tag:

```json
"extraKnownMarketplaces": {
  "nullpii": { "source": { "source": "github", "repo": "lBroth/nullpii", "ref": "v<new version>" } }
}
```

Then:

```bash
claude plugin marketplace update nullpii
claude plugin update nullpii@nullpii
```

Restart Claude Code. Your sidecar token and options stay as they are. The release notes are in the [changelog](./changelog).

## Next

- [Choose what gets masked](./guide/claude-code#choose-what-gets-masked): `/pii preset secrets`, `/pii mask url`, `/pii ask url` and the policy file.
- [Limits](./guide/claude-code#limits): what the mod does not cover.
- [Keep one sidecar across sessions](./guide/claude-code#set-up), or use it with `claude -p`.
- Without Claude Code: the [library](./guide/) or the [gateway](./guide/gateway) in front of the Anthropic or OpenAI API.
