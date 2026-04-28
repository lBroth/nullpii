# Claude Code

The fastest way to put `nullpii` in front of an LLM. **No code changes
to your codebase**, just a one-line plugin install.

## Install

```bash
npm install -g @nullpii/claude-code
```

Then enable + configure the plugin in `.claude/settings.json`. Claude
Code uses an `enabledPlugins` map (not a bare array) and a parallel
`pluginConfigs` map, both keyed by `<plugin-id>@<marketplace-id>`:

```jsonc
// .claude/settings.json
{
  "enabledPlugins": {
    "@nullpii/claude-code@<marketplace-id>": true
  },
  "pluginConfigs": {
    "@nullpii/claude-code@<marketplace-id>": {
      "backend": "auto"
    }
  }
}
```

Replace `<marketplace-id>` with the marketplace where the plugin is
registered (`anthropic` for the official marketplace once we publish;
your custom marketplace id for self-hosted or dev-local installs).

Open Claude Code, send a prompt with PII, and watch the wire traffic
— all you'll see is `[[NULLPII:private_person:0]]` and friends. The
reply you read in the chat panel has the originals restored.

## Local development install (pre-publish)

Before the plugin lands on the official marketplace, point Claude Code
at the local checkout as a marketplace source:

```bash
# 1. Build the core + plugin once
git clone https://github.com/lBroth/nullpii.git
cd nullpii
npm install
npm run build
cd packages/claude-code-plugin && npm install && npm run build && cd -

# 2. Inside Claude Code, register the local plugin path as a marketplace
/plugin marketplace add /absolute/path/to/nullpii/packages/claude-code-plugin

# 3. Confirm the marketplace + plugin are visible
/plugin marketplace list
/plugin list
```

Claude Code prints the marketplace id assigned to the local source.
Use that id in `enabledPlugins` / `pluginConfigs` exactly like the
production snippet above. If the schema rejects the path, the
plugin's `.claude-plugin/plugin.json` manifest is missing or
incomplete — verify exact required fields with `/plugin --help` on
your Claude Code version.

## What it does (current behaviour)

Three hooks, registered automatically:

- **`SessionStart`** — spawns a background `nullpii serve` daemon over
  a Unix socket. Loads the model ONCE per session (~5–10 s on first
  prompt; subsequent prompts ~30 ms).
- **`UserPromptSubmit`** — sends every outgoing prompt to the daemon.
  If PII is detected, the hook **blocks** the prompt with
  `decision: 'block'` and surfaces the sanitized version in the
  rejection reason. You copy + resend the redacted text.
- **`Stop`** — SIGTERMs the daemon, unlinks the socket, frees the
  model.

::: warning Why "block" and not silent rewrite
Claude Code's `UserPromptSubmit` hook contract supports two outcomes:
add context (`additionalContext`) or block (`decision: 'block'`). It
**cannot rewrite the outgoing prompt**. So to actually prevent a
leak we must block the original and let you decide whether to resend
the sanitized version. A future build will sit between Claude Code
and the Anthropic API as an MCP server / local proxy and rewrite
transparently — see roadmap.
:::

When the conversation ends, the session is destroyed and the
underlying `Map` becomes unreachable. No PII is persisted to disk.

## Example

You type into Claude Code:

```
Draft a polite refund email to Maria Rossi (maria.rossi@example.it)
about order #ACME-2026-04812.
```

Claude Code shows the prompt was blocked:

```
[nullpii] blocked: 2 PII span(s) detected in your prompt.

Your prompt has not been sent to Claude. Sanitized version below —
copy + resend if intended:

Draft a polite refund email to [[NULLPII:private_person:0]]
([[NULLPII:private_email:0]]) about order #ACME-2026-04812.
```

You copy the sanitized line, paste it back, hit enter. Anthropic's
API only ever sees the placeholders. The model's reply contains the
placeholders too (until the proxy / MCP variant lands and restores
them in-flight) — Maria's name and email never left your machine.

## Configuration

Lives under `pluginConfigs["@nullpii/claude-code@<marketplace-id>"]`:

| Field             | Type                                                   | Default |
| ----------------- | ------------------------------------------------------ | ------- |
| `backend`         | `cpu` / `mps` / `cuda` / `rocm` / `auto`               | `auto`  |
| `variant`         | `fp32` / `fp16` / `int8` / `int4` / `int4f16` / `auto` | `auto`  |
| `modelDir`        | string                                                 | (auto)  |
| `recognizers`     | `'none'` (disable built-ins) or `Recognizer[]` (replace) | built-in pack |
| `boundaryRefine`  | `boolean` (trim span edges)                            | `true`  |

`backend: 'auto'` walks **CUDA → MPS → ROCm → CPU**. On most macOS
laptops today, `cpu` with `variant: 'int8'` is the fastest path
(see [Backends](/guide/backends)).

The built-in recognizer pack covers URL, email, AWS / GitHub / Stripe
/ OpenAI / Anthropic keys, IBAN, US SSN. The ML model alone misses
~66% of URLs and most secrets even with clear surrounding context;
the pack closes that gap with high-precision regexes (≥0.9
confidence each). All defaults live in `nullpii`'s `src/defaults.ts`
— a single source of truth.

Unknown fields are ignored — forward-compatible.

## Verifying it works

Send a prompt that contains an obvious email. Watch the JSON request
that Claude Code emits (e.g. via a proxy or `CLAUDE_CODE_DEBUG=1`).
The `messages[*].content` on the wire contains placeholders, not the
original.

## Privacy notes

- The `nullpii` engine is loaded once per Claude Code session.
- The vault is **in-memory only** — closing Claude Code drops it.
- The plugin **never** logs or transmits original PII values; only
  per-conversation counts and the short prefix of session ids.

See [Security model](/guide/security) for the full threat model.
