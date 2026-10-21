# Claude Code through the nullpii gateway

Point Claude Code (or any Anthropic SDK client) at a local
`nullpii-gateway` container. Prompts are PII-sanitized before they
leave your machine; placeholders are restored in the response. Apache-
2.0, self-hosted, no telemetry.

## Quickstart

```bash
# 1. Clone the repository: the compose file builds the image from it
git clone https://github.com/lBroth/nullpii.git
cd nullpii

# 2. Download the model (~1.2 GB) into the gateway's cache volume, once
docker compose -f examples/claude-code/docker-compose.yml run --rm gateway \
  node bin/nullpii.mjs prefetch --backend cpu

# 3. Start the gateway
docker compose -f examples/claude-code/docker-compose.yml up -d

# 4. Wait for it to be healthy
docker compose -f examples/claude-code/docker-compose.yml ps
# STATUS shows "healthy" within about 30 seconds

# 5. Smoke test
curl -fsS http://localhost:8787/health
# {"status":"ok"}

# 6. Point Claude Code at it
export ANTHROPIC_BASE_URL=http://localhost:8787
export ANTHROPIC_API_KEY=sk-ant-…   # your real key, passed through

# 7. Run Claude Code normally
claude "summarise the email I just wrote to John Doe at john@acme.io"
```

The health check is a liveness probe: `/health` answers as soon as the server listens, and does not wait for the model. If you skip step 2, the first request that needs the model downloads it into the volume and waits for the download, which can take minutes on a slow link. The `nullpii-model-cache` volume keeps the model across restarts and `docker compose down` (not `down -v`).

To use the gateway as the sidecar of the [Claude Code mod](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod), set `NULLPII_SIDECAR_TOKEN` in the shell that starts it: the compose file passes it through to the container, and without it the sidecar API stays off.

```bash
export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
docker compose -f examples/claude-code/docker-compose.yml up -d
```

Give the mod the same token; its default sidecar URL, `http://127.0.0.1:8787`, is the port this compose file publishes.

### Alternative: persist via Claude Code settings

Skip the `export`s by writing the same vars into Claude Code's
settings file. They're picked up on every `claude` invocation.

Project-local (per-repo) — `.claude/settings.local.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8787",
    "ANTHROPIC_API_KEY": "sk-ant-…"
  }
}
```

User-global — `~/.claude/settings.json` uses the same shape;
project-local wins on conflict. Add `.claude/settings.local.json`
to `.gitignore` if you keep the API key inline.

The gateway sees the raw prompt, runs GLiNER locally, replaces
`John Doe` and `john@acme.io` with placeholders, forwards the
sanitized text to `api.anthropic.com`, and restores the placeholders
in the streamed response before Claude Code prints it. The SSE
restorer (`RestoreStream`, exported from the `nullpii` core) buffers
placeholders that straddle delta boundaries so the client never sees
a half-written `{{PII_…` token mid-stream — see the
[`RestoreStream` section in the root README](../../README.md) for
direct API use.

## What gets sanitized

nullpii masks 19 categories: person, email, phone, address, date, URL,
IP, MAC, passport, driving licence, vehicle id, geolocation, account
number (IBAN, cards, SSN, MRN, national and tax ids) and secret (API
keys, JWTs, private keys, base64-wrapped values), plus, by default,
organisation, occupation, demographic and sensitive attributes, and
titles. Validated recognizers catch structured values (IBAN mod-97,
Luhn, VIN, coordinate ranges). The full label table, and how to turn
categories off, is in the root
[`README.md`](https://github.com/lBroth/nullpii#what-gets-caught).

## Verify the redaction is working

Tail the gateway log while Claude Code is running:

```bash
docker compose -f examples/claude-code/docker-compose.yml logs -f gateway
```

Each `/v1/messages` request emits one structured log line per response
(`anthropic.messages.restored` for non-streaming,
`anthropic.messages.streamed` for SSE). The line carries the
substitution histogram — **counts only, never the PII values**:

```json
{
  "level": 30,
  "msg": "anthropic.messages.streamed",
  "replacements": 3,
  "replacementsByLabel": { "private_person": 1, "private_email": 1, "private_address": 1 },
  "unknownPlaceholders": 0,
  "foreignPlaceholders": 0
}
```

`unknownPlaceholders > 0` means the LLM hallucinated a placeholder
the vault doesn't know about. `foreignPlaceholders > 0` means a
placeholder from a different session leaked into this one. Both are
expected to be `0` on a healthy stream.

## Air-gapped / pinned-checkpoint variant (mount a host model)

For air-gapped hosts or when you want to pin a specific model revision
on disk, use the local-model compose variant instead of the default
HuggingFace download path:

```bash
# 1. Prefetch the model on a host with network access. It goes into the
#    cache, and the command prints the directory ("cached at: …").
npx -p nullpii -p onnxruntime-node nullpii prefetch

# 2. Point the compose at that directory and boot
export MODEL_DIR_HOST=<the directory prefetch printed>
docker compose -f examples/claude-code/docker-compose.local-model.yml up -d

# 3. Same setup as the quickstart from here on
export ANTHROPIC_BASE_URL=http://localhost:8787
export ANTHROPIC_API_KEY=sk-ant-…
claude "summarise email to John at john@acme.io"
```

The directory must contain `model.onnx`, `tokenizer.json`,
`gliner_config.json`, `tokenizer_config.json`. It's mounted read-only.

## Going further

- **A host directory for the model cache**, to see the files: replace
  the named volume with a bind mount. The container runs as the `node`
  user (uid 1000), so the directory must be writable by that uid.
  ```yaml
  volumes:
    - ./nullpii-model-cache:/home/node/.cache/nullpii
  ```
- **Air-gapped deployment.** Pre-fetch the model on a connected
  machine (`npx nullpii prefetch` prints the directory it filled), copy
  that directory over, then mount it into the container:
  ```yaml
  environment:
    NULLPII_MODEL_DIR: /models/gliner
  volumes:
    - /abs/path/to/local/gliner-onnx:/models/gliner:ro
  ```
- **Higher throughput.** Switch to a GPU host with the CUDA backend:
  `NULLPII_BACKEND=cuda` plus the matching `onnxruntime-node` build.
  See the root [README §Backends](../../README.md).
- **Multi-replica.** The vault lives in each replica's memory and is
  not shared. The Messages and Chat Completions routes keep a session
  for one request only, so any load balancer works for them. The
  sidecar API keeps sessions across calls: send each sidecar client to
  the same replica every time (sticky sessions).

## Limitations

- **Two APIs.** The gateway serves the Anthropic Messages API and the
  OpenAI Chat Completions API (`/v1/chat/completions`). For anything
  else, use the core `nullpii` library directly: see the root README.
- **No auth on the gateway itself.** Put your own mTLS / API-key
  layer in front (typical enterprise pattern). The gateway speaks
  plain HTTP because operators add the TLS termination they trust.
- **Vault TTL is per-request** — each `/v1/messages` round-trip mints
  a fresh session and destroys it at the end. Inter-turn conversation
  context lives entirely in the client.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container in `health: starting` for more than a minute, or `unhealthy` | The server is not listening. `docker compose -f examples/claude-code/docker-compose.yml logs gateway` shows why: an invalid variable or policy file stops the gateway at startup, with the reason. The model plays no part here, since `/health` does not wait for it. |
| The first request hangs | The model was not prefetched, so that request is downloading it (~1.2 GB). Let it finish, or run step 2 of the quickstart beforehand next time. The container needs to reach `huggingface.co`. |
| Requests fail with the local-model variant | `MODEL_DIR_HOST` is not a directory holding `model.onnx`, `tokenizer.json`, `gliner_config.json` and `tokenizer_config.json`. The gateway reads the model on the first request, not at startup, so the health check passes either way. |
| `502 nullpii_upstream_error` | Gateway couldn't reach `api.anthropic.com`. Check `NULLPII_UPSTREAM` and outbound DNS. |
| Claude Code prints placeholders instead of names | The LLM moved a placeholder across token boundaries in a way the streaming restorer can't reassemble. File a bug with a redacted repro — these are usually fixable. |
| `unknownPlaceholders > 0` in logs | The LLM made up a placeholder. Usually fine (Claude is told via `LLM_PRESERVATION_HINT` to keep them, but occasionally fabricates). |
