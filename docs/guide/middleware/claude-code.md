# Claude Code

`@nullpii/claude-code` is a **lifecycle plugin**: it loads the PII
model into memory when Claude Code starts and unloads it when the
session ends. The plugin itself does not rewrite prompts — that is
not possible with the current Claude Code hook API. **For actual
in-flight sanitization use the [Anthropic SDK middleware](./anthropic.md)**
in your application code.

What the plugin gives you:

- `SessionStart` → spawns a `nullpii serve --socket <path>` daemon in
  the background. The model is downloaded on first run (~3 GB fp16,
  cached in `~/.cache/nullpii/`) and stays resident across prompts.
- `Stop` → SIGTERMs the daemon, unlinks the socket + state file.
- **Watchdogs** for the case where Claude Code exits without running
  the Stop hook:
  - **idle timeout** — the daemon self-terminates after 30 min with
    no socket activity.
  - **parent-pid liveness** — the daemon polls the Claude Code pid
    every 5 s; if it disappears, daemon self-terminates.

No on-the-wire interception happens from inside Claude Code. If you
need transparent sanitize-then-restore around Anthropic API calls,
write your code against `@anthropic-ai/sdk` and wrap the client with
`withNullPii(client)`.

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

## What it does

Two hooks, registered automatically:

- **`SessionStart`** — spawns a background `nullpii serve` daemon
  over a Unix socket and pre-loads the model. First run downloads
  ~3 GB; subsequent runs reuse the cache.
- **`Stop`** — terminates the daemon and unlinks its state.

The daemon is configured with two safety-net watchdogs so the model
unloads even if Claude Code exits without firing `Stop`:
- **idle timeout** (`--idle-timeout-ms`, default 30 min)
- **parent-pid liveness** (`--parent-pid`, polled every 5 s)

::: tip For real sanitization
The plugin does not block or rewrite prompts. Use the
[`withNullPii(client)`](./anthropic.md) middleware around your
Anthropic SDK client for transparent in-flight sanitize → API →
restore.
:::

## Verifying the daemon

```bash
# After Claude Code session opens:
ls ~/.cache/nullpii/plugin/        # daemon-<sessionId>.json present
lsof -U | grep nullpii              # daemon listening on socket
# After Stop fires (or Claude Code exits + watchdog kicks in):
ls ~/.cache/nullpii/plugin/        # state file gone
```

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
