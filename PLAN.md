# nullpii — v0.2 Plan: OSS self-hosted gateway

> Status (2026-05-13): partial. The unified-model retrain is **done** —
> single ONNX, permissive-only training, ~1.2 GB download. `src/` cleanup
> + tests + docs landed. Pending: HF upload + revision pin, full
> publishable competitor matrix, and the gateway / docker / blog-post
> work outlined below. Sections 7 (honest headline metric) and 9
> (licensing audit) are done — see CHANGELOG 0.2.0 + NOTICE.

## Positioning

**nullpii is and will remain Apache-2.0 self-hosted.** No SaaS, no
managed service, no enterprise tier, no per-seat licensing. The library
+ a future gateway are pieces of infrastructure the user installs on
their own hardware, audits, and forks if needed.

This positioning is a deliberate commitment — same model as Microsoft
Presidio, Ollama, LiteLLM (core), Langfuse (core), PostHog. It rules
out:

- SOC 2 / vendor SLAs (not a service provider)
- DPA / sub-processors agreements (not a data processor)
- Phone-home telemetry (not now, not ever)
- License re-rugs à la Mongo SSPL / Elastic / Terraform BSL

It rules in:

- Air-gapped / on-prem deployments as first-class
- Legal / Compliance review reduces to reading the repo
- Revenue model (if any, later) = open-core extras + paid support,
  never the core

A short statement to this effect should land at the top of the README
in the v0.2 cycle so adopters get an explicit non-rug-pull commitment.

## Why a gateway, on top of the npm library

The current shape (`npm i nullpii` + CLI) is correct for embedding in
TS/JS apps, but the highest-leverage deployment in an enterprise
self-host scenario is a **drop-in proxy** in front of LLM provider
APIs. One container, one endpoint, zero application code changes — the
dev only flips `baseURL` from `api.anthropic.com` (or
`api.openai.com`) to the internal gateway.

The 6 GB model footprint, which is a friction point for the npm
library, is **not a problem** in this shape: it's loaded once on a
server, amortised across every request from every internal app.

```
[internal app] ──prompt with PII──▶ [nullpii-gateway] ──sanitised──▶ [Anthropic / OpenAI / Mistral]
                                          ▲                                        │
                                          │                                        │
[internal app] ◀─restored response─── [nullpii-gateway] ◀───response w/ placeholders
```

## Proposed work for v0.2

Numbered roughly in dependency order. Each item is independently
shippable.

### 1. `packages/gateway` — HTTP proxy

- Fastify or Hono server (lean, fast, native ESM).
- Endpoints:
  - `POST /v1/messages` — Anthropic-compatible
  - `POST /v1/chat/completions` — OpenAI-compatible
- Per request:
  1. `sanitize()` each user/system message, store sessionId in request
     context.
  2. Forward to upstream provider with sanitised body.
  3. `restore()` the response body before returning to caller.
- Auth: out-of-scope for the core. Operators put their own
  ingress/mTLS/API-key layer in front (typical enterprise pattern).
- Config via env vars: `NULLPII_UPSTREAM`, `NULLPII_MODEL_DIR`,
  `NULLPII_BACKEND`, `NULLPII_VAULT_TTL_MS`, …

### 2. Streaming-safe placeholder handling

Non-trivial. SSE chunks from upstream can split a placeholder mid-token
(`{{PII_PRIV` … chunk boundary … `ATE_PERSON_0}}`). The gateway must
buffer until placeholder boundaries are resolvable before forwarding
restored text downstream.

Approach:

- Maintain a small rolling buffer (≤ longest possible placeholder, ~64
  chars).
- Flush everything up to the last unambiguous non-`{` character on
  each chunk.
- Resolve completed `{{…}}` against the session vault.
- Emit a regression test corpus that fragments every placeholder at
  every byte offset.

### 3. `VaultStore` interface

Today the vault is in-process Map. For multi-replica deploys behind a
load balancer it has to be pluggable.

```ts
interface VaultStore {
  put(sessionId: string, mapping: Record<string, string>): Promise<void>;
  get(sessionId: string): Promise<Record<string, string> | null>;
  destroy(sessionId: string): Promise<void>;
}
```

Implementations to ship:

- `MemoryVaultStore` (default, current behaviour, single-replica).
- `RedisVaultStore` (multi-replica, with TTL).

Sticky-session via load balancer is also valid and should be
documented as the simpler alternative.

### 4. Quantized model variants

Unified GLiNER ONNX is ~1.2 GB FP32. Ship int8 (~350 MB) and int4
(~200 MB) sidecars alongside `model.onnx` in the HF repo so users on
tight-RAM / cold-start-sensitive workloads can opt in. Trade-off needs
to be benched and disclosed in the model card the same way the
model-only vs full-runtime delta is already disclosed today (int8 was
lossier than rank-32 fp32 in pre-ship experiments — re-bench against
the unified-aug2 weights).

Surfaced as `variant: 'fp32' | 'int8' | 'int4' | 'auto'` in
`NullPiiConfig` (the field already exists; this is wiring on both
the runtime fetcher and the model-manager manifest).

### 5. Two Docker images

- `nullpii/gateway:slim` — code only, mounts/downloads model on first
  boot. Small image, slow first start.
- `nullpii/gateway:fat` — model pre-baked into the image. Big image
  (~6.5 GB), instant start, ideal for air-gapped registries.

Both built in CI on every release tag. Multi-arch (amd64 + arm64).

### 6. `examples/` — copy-paste integrations

Each example must be runnable with `docker compose up` + a single
`curl` or 10-line script:

- `examples/anthropic-proxy/` — drop-in for `@anthropic-ai/sdk`
- `examples/openai-proxy/` — drop-in for `openai` Node SDK
- `examples/langchain-middleware/`
- `examples/llamaindex-callback/`
- `examples/log-scrubber/` — sidecar that redacts PII from app logs
  before they reach the SIEM

A dev who sees their stack listed is a dev who stars the repo.

### 7. Honest headline metric

The README headline today emphasises mixed-8 macro F1 (0.7846), which
mixes in-distribution diagnostic rows. The cleaner number is
**held-out OOD multilingual F1 = 0.7662 across 6 datasets in 4
languages** — that should be the headline; mixed-8 stays as supporting
detail with the existing ⚠ markers.

This is purely a README edit, no code change.

### 8. Content marketing — three posts from existing material

All three are already written internally; just need a public form.

- **"PII redaction benchmarks aren't reproducible"** — derived from
  the `CLAIM-VERIFIER-01` finding. Shows Presidio
  0.85+ and piiranha 0.99+ vendor numbers don't survive standard
  span-IoU methodology. HN-front-page material.
- **"Why we chose `{{PII_TYPE_N}}` as the placeholder format"** —
  derived from `packages/eval/private/PLACEHOLDER_FORMAT_ANALYSIS.md`.
  Empirical study across 6 formats × 6 LLM tasks.
- **"Multilingual PII redaction with one model"** — derived from the
  isotonic-{en,de,fr,it} held-out results.

Content drives discoverability; without it OSS dies in silence.

### 9. Licensing audit pass

Quick legal due-diligence pass before pushing the gateway publicly:

- Confirm the HF weights (`lBroth/nullpii`) ship under a permissive
  licence compatible with Apache-2.0 redistribution.
- Confirm each training dataset's terms allow the resulting weights
  to be redistributed (TAB ECHR, Isotonic, ai4privacy, Nemotron,
  presidio-synthetic — some are CC-BY, some research-only).
- Document the audit result in `NOTICE` so enterprise Legal can
  rubber-stamp adoption.

This is the most likely silent dealbreaker for a bank/health/legal
adopter.

## Out of scope for v0.2

To stay focused:

- SSO, RBAC, multi-tenancy
- Fine-tuning UX (the LoRA training recipe stays in `packages/eval/`
  for advanced users)
- Web UI / dashboard
- Cloud-managed offering of any kind

## Success metrics for the v0.2 cycle

Not revenue or signups — the OSS self-host equivalents:

- `docker run nullpii/gateway:slim` redacts a first request in < 5
  minutes from a clean machine, documented in the README.
- First 50 GitHub issues triaged within 48h.
- One of the three blog posts on HN front page or /r/MachineLearning
  top-week.
- At least one external contributor PR merged.
- One public reference deployment (a user willing to be quoted).

These are leading indicators that the project is alive; the lagging
indicator (downloads, stars) follows.
