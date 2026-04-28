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
at the local checkout directly:

```bash
# 1. Build the core + plugin once
git clone https://github.com/lBroth/nullpii.git
cd nullpii
npm install
npm run build
cd packages/claude-code-plugin && npm install && npm run build && cd -

# 2. Inside Claude Code, add the local plugin
/plugin add /absolute/path/to/nullpii/packages/claude-code-plugin

# 3. Confirm the plugin is visible
/plugin list
```

Claude Code reports the marketplace id assigned to the local install —
use it in `enabledPlugins` / `pluginConfigs` exactly like the
production snippet above. If the schema rejects the path, the
plugin's `.claude-plugin/plugin.json` manifest is missing or
incomplete — verify exact required fields with `/plugin --help` on
your Claude Code version.

## What it does

Two hooks, registered automatically:

- **`prePrompt`** — every outgoing prompt is run through nullpii.
  Detected PII spans become typed placeholders. The vault session id
  is stashed against your conversation id.
- **`postResponse`** — the model's reply is matched against
  `PLACEHOLDER_REGEX` and any placeholders that originated in this
  conversation are restored to their original values before display.

Multi-turn conversations reuse the same vault session, so a follow-up
that quotes back an earlier value (e.g. "remind me, what was John's
email again?") resolves correctly.

When the conversation ends, the session is destroyed and the underlying
`Map` becomes unreachable. No PII is persisted.

## Example

You type into Claude Code:

```
Draft a polite refund email to Maria Rossi (maria.rossi@example.it)
about order #ACME-2026-04812.
```

Anthropic's API sees:

```
Draft a polite refund email to [[NULLPII:private_person:0]]
([[NULLPII:private_email:0]]) about order #ACME-2026-04812.
```

You see in your terminal:

```
Subject: Refund for order #ACME-2026-04812

Hi Maria,

Thanks for your patience. We've processed your refund for order
#ACME-2026-04812 to maria.rossi@example.it. ...
```

Maria's name and email never left your machine. The order id stays
intact because it doesn't match any of the eight PII categories.

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
