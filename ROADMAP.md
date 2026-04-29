# Roadmap

Two deliverables drive the roadmap: the **npm library** (`nullpii`) and
the **HuggingFace model** (`lBroth/nullpii`). Everything
else is in service of the comparison study they enable.

Legend:
- 🚨 critical bug — fix before 1.0
- 🔥 high impact for adoption
- ⭐ differentiator
- 🧪 quality bar
- 🎬 marketing / community

## 🚨 Critical (block 1.0)

- [ ] **Tokenizer truncation silent**
      `MAX_SEQUENCE_LENGTH = 512` truncates without telling the caller.
      Honor the existing `TextTooLongError`; expose `--truncate` opt-in.
- [ ] **Placeholder collision escape**
      If user text already contains `[[NULLPII:secret:0]]`, `restore()`
      replaces it. Add escape on sanitize input + unescape on restore output.
- [ ] **Functional-wrapper instance cache leak**
      `instance(config)` keeps `NullPii` alive forever. Either accept an
      explicit `engine` arg, or cap the cache + LRU evict + dispose on evict.
- [ ] **First-run UX**
      ~1.5 GB download blocks the first sanitize. Add (a) progress callback
      in `init()`, (b) automatic retry with backoff, (c) clear offline-mode
      error when the model dir is empty + the network is down.

## 🔥 Research deliverables

- [ ] **Full bench (n≥5k per dataset)** for nullpii to graduate from preview.
      Output: `packages/eval/results/runpod-YYYY-nullpii-full/matrix.{json,csv}`
      next to the existing 5090 matrix; mirror the table into
      `docs/guide/eval-results.md`.
- [ ] **Publish `lBroth/nullpii` to HF Hub** with a model
      card linking back to the comparison write-up. Recipe under
      `scripts/release/push-to-hf.sh`.
- [ ] **Japanese / non-Latin support gap** — known weakness on both
      `openai/privacy-filter` and v2. Add Japanese / Korean / Chinese
      training data slices and a round-3 fine-tune; track in
      `qualitative_compare.md`.
- [ ] **Publish nullpii v1.0** to npm with `--provenance`.
- [ ] **Public benchmark dashboard** at `lbroth.github.io/nullpii/bench`,
      auto-updated by a CI cron that pulls `matrix.json`.

## ⭐ Differentiation

- [ ] **Custom recognizer API** — already shipping; document edge cases
      and add an example pack for a 4th-party (e.g. healthcare codes).
- [ ] **Vault TTL + max-size** — bound memory; configurable max sessions
      + max placeholders per session, LRU eviction.
- [ ] **Sub-modeled `secret` categories** — split `secret` into API key
      vs JWT vs password via heuristic post-pass or a small classifier.
- [ ] **WASM build** — `nullpii/wasm` subpath; uses `onnxruntime-web`;
      stays LGPL-free.

## 🧪 Quality

- [ ] **F1 confusion matrix** per category, published nightly.
- [ ] **Property tests for vault round-trip** — `fast-check`: any
      `(text, spans)` → sanitize → restore = text.
- [ ] **Mutation testing** with Stryker on `vault.ts`, `viterbi.ts`,
      `span-decoder.ts`. Score ≥75%.
- [ ] **Memory profiling job** — long-running process: 10k prompts,
      assert `heapUsed` plateau.
- [ ] **Bundle size budget** — `size-limit` in CI: `dist/index.js` ≤
      50 KB, declarations only.
- [ ] **Security review** — external pen-test against placeholder
      collisions, vault timing attacks, prompt injection that asks the
      model to dump the vault.

## 🎬 Distribution / DX

- [ ] **Engines `>=22` not `>=24`** — Node 22 is current LTS.
- [ ] **Docker image** for offline use — `nullpii/cli:1.0.0` with model
      baked in; `~2 GB`; tagged + signed.
- [ ] **Telemetry (opt-in, anonymous)** — counts only, no text. Off by
      default; toggle `NULLPII_TELEMETRY=1`.
- [ ] **Examples repo** `nullpii/examples` — 4–6 self-contained scripts:
      customer-support batch redaction, RAG, log scrubbing, audit,
      prefetch in CI.
- [ ] **Demo video** (60–90s) — real terminal: install, sanitize a
      PII-laden prompt, show wire traffic with placeholders, show
      restored reply.

## Out of scope (intentional)

- ❌ Cloud-based redaction fallback
- ❌ Browser-native runtime (deferred until LGPL-free path exists)
- ❌ Domain-specific models (medical / legal) — community contribution
  via the custom-recognizer API
- ❌ "All-in-one PII platform"

## Cut list

**0.x → 1.0 (must-have)**: every 🚨 above, engines bump, full bench
n≥5k, nullpii HF publish, recognizer API examples.

**1.x (next two months)**: WASM build, benchmark dashboard, mutation
tests, public examples repo, JP / non-Latin round-3 fine-tune.

**2.x (later)**: sub-modeled categories, security review, telemetry.
