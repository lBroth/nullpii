# Roadmap — `nullpii` to the stars

Focused on **Claude Code + TypeScript** ecosystem. Anything generic
(OpenAI/Vercel AI/etc.) is intentionally out of scope.

Legend:
- 🚨 critical bug — fix before 1.0
- 🔥 high impact for adoption
- ⭐ differentiator vs Presidio / Private AI
- 🧪 quality bar (validation, perf, security)
- 🎬 marketing / community

---

## 🚨 Critical bugs (block 1.0)

- [ ] **Streaming buffer cross-chunk in middleware**
      `restoreStream` currently calls `restore()` per chunk. A placeholder
      that straddles two stream chunks is split mid-string and never
      restored. Fix: keep a string buffer, emit only up to the last
      complete `[[NULLPII:label:idx]]` plus tail; flush on stream end.
- [ ] **Multi-turn vault retention in Anthropic middleware**
      Today the session is destroyed in a `finally` after every
      `messages.create()` call. A follow-up that quotes back an earlier
      placeholder cannot resolve. Add `withNullPii(client, { conversationKey: id })`
      so calls sharing the same key share a vault. Auto-destroy on
      `client.dispose()` or after a configurable idle TTL.
- [ ] **Placeholder collision escape**
      If user text already contains the literal `[[NULLPII:secret:0]]`,
      `restore()` happily replaces it. Add an escape pass on sanitize
      input (`[[` → `[\[`) and an unescape on restore output.
- [ ] **Functional-wrapper instance cache leak**
      `instance(config)` keeps `NullPii` alive forever, keyed on
      `JSON.stringify(config)`. No `dispose()` ever runs. Either: (a) make
      `sanitize()`/`restore()` accept an explicit `engine` arg, deprecate
      the cache; (b) cap the cache + LRU evict + dispose on evict.
- [ ] **Tokenizer truncation silent**
      `MAX_SEQUENCE_LENGTH = 512` truncates without telling the caller.
      Honor the existing `TextTooLongError` and throw when the encoded
      length exceeds the cap; expose `--truncate` opt-in for callers
      who explicitly want the silent path.
- [ ] **First-run UX**
      ~1.5 GB download blocks the first sanitize. Add (a) a progress
      callback in `init()`, (b) automatic retry with backoff, (c) clear
      offline-mode error if the model dir is empty and the network is
      down, (d) a `nullpii prefetch` CLI command.

## 🔥 Claude Code experience (the wedge)

- [ ] **Plugin marketplace listing**
      Submit `@nullpii/claude-code` to the Anthropic plugin index when
      Anthropic ships one. Until then, README/landing page targets
      "drop in via `.claude/settings.json`" search intent.
- [ ] **In-conversation status icon**
      Tiny indicator showing "🛡 PII guarded — N spans this turn".
      Reduces user anxiety, builds trust.
- [ ] **Audit log subcommand**
      `nullpii audit show <conversationId>` prints, locally, count and
      categories of redactions per turn. Counts only — never the
      original PII values.
- [ ] **Whitelist commands / paths**
      `.claude/settings.json` `nullpii.skip: ["^/git ", "^/help"]` to
      skip sanitization for plumbing commands.
- [ ] **Per-user opt-in categories**
      Drop-down or `nullpii.categories: ["private_person", ...]` to
      include/exclude. Today everything is on.
- [ ] **Score threshold**
      `nullpii.threshold: 0.8` — drop spans below confidence. Surface
      this in the JSON config.
- [ ] **Slash command in Claude Code**
      `/nullpii status`, `/nullpii destroy-session`, `/nullpii reload-model`.
- [ ] **Plugin auto-update**
      Detect new `@nullpii/claude-code` versions and prompt; today the
      user has to run `npm i -g` themselves.
- [ ] **Session-end cleanup**
      Currently sessions destroy on conversation end. Verify under all
      Claude Code lifecycle events (process kill, Ctrl-C). Property test.

## ⭐ Differentiation features

- [ ] **Custom recognizer API**
      `addRecognizer({ id, regex, label, score })` for known formats
      (org-specific account ids, legal case numbers, internal SKUs).
      Runs after the ML pass; must not contradict ML decisions.
- [ ] **Reversible RAG mode**
      Persist vault to disk (encrypted) keyed by document id. Restore
      across processes. Library option `vault: { kind: 'file', path, key }`.
- [ ] **Vault TTL + max-size**
      Bound memory: configurable max sessions + max placeholders per
      session, LRU eviction.
- [ ] **Sub-modeled categories**
      Today `secret` is one bucket; offer optional sub-classifiers (API
      key vs JWT vs password). Either via heuristic post-pass or a
      second small model.
- [ ] **Locale awareness**
      Document tested locales explicitly, fix where broken. At minimum:
      EN, IT, DE, FR, ES, JA. Add a per-locale eval.
- [ ] **WASM build**
      For Cloudflare Workers / Bun / Deno. `nullpii/wasm` subpath; same
      API; uses `onnxruntime-web` instead of `-node`. Stays LGPL-free.

## 🧪 Quality / validation

- [ ] **Real F1 evaluation**
      Run on the public PII-Masking-300k test split. Publish numbers
      per category + macro F1. Add a CI job that reruns on every model
      revision bump.
- [ ] **False positive / negative report**
      Curated 100-prompt set per category, plus 200 PII-free decoy
      prompts. Publish confusion matrix. Re-run nightly.
- [ ] **Benchmark vs Presidio**
      Same eval set, comparable hardware. Publish honest numbers in
      `BENCHMARK.md` and on the docs site. Don't cherry-pick.
- [ ] **Property tests for vault round-trip**
      `fast-check`: any `(text, spans)` → sanitize → restore = text.
      Includes adversarial inputs (placeholder-shaped strings, unicode,
      empty spans, overlapping spans).
- [ ] **Mutation testing**
      Stryker on `vault.ts`, `viterbi.ts`, `span-decoder.ts`. Score
      ≥75%.
- [ ] **Memory profiling job**
      Long-running process: `np.sanitize` 10k prompts, assert no leak
      (`heapUsed` plateau).
- [ ] **Bundle size budget**
      `size-limit` in CI: `dist/index.js` ≤ 50 KB, declarations only.
      Backends behind subpath imports stay tree-shakable.
- [ ] **Security review**
      External pen-test against placeholder collisions, vault timing
      attacks, prompt-injection that asks the model to dump the vault.
      Report in `SECURITY.md`.
- [ ] **Coverage gates per file**
      Today thresholds are global. Move to per-file ≥80 lines on
      `vault.ts`, `nullpii.ts`, `tokenizer.ts`.

## 🎬 Distribution / DX

- [ ] **Engines `>=22` not `>=24`**
      Node 22 is current LTS; gating on 24 alone shrinks our addressable
      install base by ~70%.
- [ ] **`nullpii doctor`** CLI
      Probes: model cache present + verified, backend available, ORT
      version, free disk, free RAM. Exit 0 / 1 with a friendly summary.
- [ ] **`nullpii prefetch`** CLI
      Download model in advance — useful in CI / Docker-build phases.
- [ ] **Docker image** for offline use
      `nullpii/cli:1.0.0` with model baked in; `~2 GB`. Tagged + signed.
- [ ] **JSON schema for config**
      `.claude/settings.json` `nullpii.*` keys validated by a published
      schema → IDE autocomplete.
- [ ] **Telemetry (opt-in, anonymous)**
      Counts only, no text. Helps prove adoption + guides roadmap. Off
      by default; toggle `NULLPII_TELEMETRY=1`.

## 🎬 Marketing / community

- [ ] **Demo video** (60–90s)
      Real terminal: install plugin, send PII-laden prompt to Claude
      Code, show wire traffic with placeholders, show restored reply.
- [ ] **Comparison page** `docs/guide/vs-presidio.md`
      Honest side-by-side. Where Presidio wins (multi-lingua, mature
      ecosystem), where nullpii wins (TS-first, drop-in, reversible,
      Claude Code).
- [ ] **Examples repo** `nullpii/examples`
      4–6 self-contained scripts: customer-support, RAG, log scrubbing,
      audit, prefetch in CI, sub-process integration.
- [ ] **Public benchmark dashboard**
      `lbroth.github.io/nullpii/bench` auto-updated by CI cron.
- [ ] **Discord / GH Discussions**
      Single channel. Pin: `troubleshooting`, `release notes`,
      `model accuracy`.
- [ ] **Anthropic blog / partnership**
      If the Claude Code plugin lands, pitch a guest post on the
      Anthropic engineering blog about local PII redaction.

## Out of scope (intentional)

- ❌ OpenAI SDK middleware
- ❌ Vercel AI SDK middleware
- ❌ Any cloud-based redaction fallback
- ❌ Browser-native runtime (deferred until LGPL-free path exists)
- ❌ Domain-specific models (medical / legal) — community contribution
      via the custom-recognizer API
- ❌ "All-in-one PII platform" — we are a focused Claude Code + TS tool

---

## Cut list (sequencing)

**0.x → 1.0 (must-have)**: every 🚨 above, plus the engines bump,
`nullpii doctor`, real F1 eval published, custom recognizer API.

**1.x (next two months)**: streaming fix, RAG file-vault, WASM build,
benchmark dashboard, demo video, examples repo.

**2.x (later)**: locale eval matrix, sub-modeled categories, marketplace
listing, Anthropic blog post.
