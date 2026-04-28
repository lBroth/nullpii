# @nullpii/claude-code

Claude Code plugin: sanitize PII in every prompt locally before it's sent,
restore the original values in every response before display. All running
on your machine — zero cloud calls for the PII detection step.

## Install

```bash
npm install -g @nullpii/claude-code
```

Claude Code 2.x uses two parallel maps in `.claude/settings.json`,
both keyed by `<plugin-id>@<marketplace-id>`:

```json
{
  "enabledPlugins": {
    "@nullpii/claude-code@<marketplace-id>": true
  },
  "pluginConfigs": {
    "@nullpii/claude-code@<marketplace-id>": {
      "backend": "auto",
      "variant": "auto"
    }
  }
}
```

`<marketplace-id>` = the marketplace where the plugin is registered.
Pre-publish, point Claude Code at a local checkout as a marketplace
source:

```bash
/plugin marketplace add /absolute/path/to/nullpii/packages/claude-code-plugin
/plugin marketplace list   # shows the assigned marketplace id
/plugin list               # confirms the plugin loaded
```

## Configuration

| Field      | Type                                          | Default | Description                                |
| ---------- | --------------------------------------------- | ------- | ------------------------------------------ |
| `backend`  | `cpu` / `mps` / `cuda` / `rocm` / `auto`      | `auto`  | Hardware backend                           |
| `variant`  | `fp32` / `fp16` / `int8` / `int4` / `int4f16` / `auto` | `auto` | ONNX model variant                  |
| `modelDir` | string                                        | (auto)  | Override local model dir                   |
| `recognizers` | `'none'` or `Recognizer[]`                 | built-in pack | Disable / replace built-in regex set |
| `boundaryRefine` | `boolean`                              | `true`  | Trim whitespace + punctuation from span edges |

## How it works

The plugin registers two hooks:

- **`prePrompt`**: takes the outgoing prompt text, runs it through the
  `nullpii` engine, replaces PII spans with placeholders, stashes the
  vault session id keyed by `conversationId`, and forwards the sanitized
  text to Claude.

- **`postResponse`**: takes Claude's reply, looks up the vault session
  for the same `conversationId`, restores any placeholders to their
  original values, and forwards the restored text to the user.

Multi-turn conversations reuse the same vault session, so a response
that quotes back an earlier user-supplied name still resolves correctly.

## Privacy notes

- The PII detection step runs **locally** on your machine.
- The vault is **in-memory only**. It is never written to disk.
- The vault session is **destroyed** when the conversation ends.
