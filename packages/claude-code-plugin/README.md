# @nullpii/claude-code

Claude Code plugin: sanitize PII in every prompt locally before it's sent,
restore the original values in every response before display. All running
on your machine — zero cloud calls for the PII detection step.

## Install

```bash
npm install -g @nullpii/claude-code
```

Then add to `.claude/settings.json`:

```json
{
  "plugins": ["@nullpii/claude-code"],
  "nullpii": {
    "backend": "auto",
    "variant": "auto"
  }
}
```

## Configuration

| Field      | Type               | Default | Description                                            |
| ---------- | ------------------ | ------- | ------------------------------------------------------ |
| `backend`  | `cpu`/`mps`/`cuda`/`rocm`/`webgpu`/`auto` | `auto`  | Hardware backend                                       |
| `variant`  | `fp32`/`fp16`/`int8`/`int4`/`int4f16`/`auto` | `auto`  | ONNX model variant                                     |
| `modelDir` | string             | (auto)  | Override local model dir (skip download)               |

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
