# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Repo bootstrap** — npm workspaces, TypeScript strict ESM (NodeNext,
  `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`), Biome lint+format,
  Vitest with 85/80 coverage thresholds, Lefthook pre-commit, license-checker,
  madge circular-import check, GitHub Actions CI on Node 24 (Ubuntu / macOS /
  Windows), Apache 2.0 LICENSE + NOTICE.
- **Model fetch & verify pipeline** (`packages/convert/`) — Python 3.12.
  Pins `openai/privacy-filter` to commit SHA `7ffa9a04…`, downloads the ONNX
  variants (fp32 / fp16 / int8 / int4 / int4+fp16), produces a deterministic
  `manifest.json`, runs SHA256 + optional sigstore integrity, smoke-tests
  every variant, and runs an inter-format consistency check on 50 bundled
  prompts.
- **Type system + errors** — `PiiLabel` / `PiiCategory` unions, `PII_LABELS`
  tuple (33 BIOES), `PiiSpan`, `VaultToken`, `SanitizeResult`,
  `RestoreResult`, `NullPiiConfig`, `BackendName`, `ModelVariant`,
  `BackendProvider`, `InferenceInputs`, `InferenceOutputs`,
  `MAX_SEQUENCE_LENGTH`, `PLACEHOLDER_REGEX`, `PLACEHOLDER_TEMPLATE`.
  Custom error classes: `NullPiiError` (base) + `ModelNotFoundError`,
  `BackendNotAvailableError`, `ModelNotInitializedError`, `TextTooLongError`,
  `SessionNotFoundError`, `InvalidPathError`.
- **Tokenizer** — `TokenizerWrapper` around `@anush008/tokenizers`. Lazy
  load, `encode()` returns `inputIds` / `attentionMask` / `offsetMapping`.
- **Viterbi decoder** — `viterbiBioesDecode`, `buildTransitionMatrix`,
  `parseLabel`, `isValidTransition`, `isValidStart`. Numerically stable
  log-softmax, forward DP with backpointers, backtrack.
- **Span decoder** — `decodeSpans` builds char-level `PiiSpan`s from BIOES
  labels and offset mapping, including mean per-span score.
- **Backends** — `OrtBackend` abstract base; `CpuBackend`, `MpsBackend`,
  `CudaBackend`, `RocmBackend`. Tree-shakable via subpath exports.
  ORT execution providers cover all four.
- **Router + Model Manager** — `selectBackend(modelDir, config)` with
  dynamic backend imports and CUDA → MPS → ROCm → CPU auto priority;
  `ModelManager` with HF download + SHA256 cache under `~/.nullpii/models/`.
- **PiiVault** — `createSession` (UUID v4), `sanitize`, `restore`,
  `destroySession`. Per-label indexed placeholders. Back-to-front
  replacement preserves char offsets. In-memory only.
- **Core engine `NullPii`** — orchestrates tokenize → infer → Viterbi →
  span-decode → vault. Lazy idempotent `init()`. Functional wrappers
  `sanitize` / `restore`. End-to-end byte-for-byte idempotent.
- **CLI** — `npx nullpii scan|sanitize|restore|models|benchmark` with
  `--format json` and `--model-dir` overrides. `commander` + `chalk` +
  `cli-progress` (all MIT).
- **Anthropic middleware** — `nullpii/middleware/anthropic`. Drop-in
  proxy that preserves the SDK's TypeScript surface.
- **Claude Code plugin** (`packages/claude-code-plugin/`) — `prePrompt`
  + `postResponse` hooks, per-conversation session reuse, settings
  read from `.claude/settings.json`.
- **Documentation** — full README with quick-start examples, this
  CHANGELOG, CONTRIBUTING.md, SECURITY.md, BENCHMARK.md.

### Architecture decision

Project shipped as a single `nullpii` npm package (was originally
multi-package). Backend tree-shaking preserved via conditional subpath
exports + optional `peerDependency` `onnxruntime-node`.

### Scope (focused on Claude Code + TS ecosystem)

OpenAI SDK and Vercel AI SDK middleware were removed before 1.0 to keep
the surface area narrow and the marketing message clear. The library
targets Claude Code users + TS developers using `@anthropic-ai/sdk` or
the programmatic `NullPii` class directly.

### Removed before 1.0

- **WebGPU backend** dropped. `@huggingface/transformers` was the only
  realistic browser path and it transitively pulled `sharp` →
  `@img/sharp-libvips-*` (LGPL-3.0-or-later). To keep the dependency
  tree 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0), the WebGPU
  backend was removed entirely. May return as a separate package once an
  LGPL-free browser ONNX path is available.

### Spec deviations (with rationale)

- **Step 002**: own ONNX/CoreML/GGUF conversion was dropped. The
  upstream HF repo already publishes ONNX variants; the model uses a
  custom architecture without public modeling code, so re-converting
  introduces risk without benefit. CoreML covered by ORT
  `CoreMLExecutionProvider`; GGUF unsupported for non-causal LMs.
- **Step 004**: tokenizer uses `@anush008/tokenizers` (NAPI bindings)
  instead of `@huggingface/transformers` (JS, no offset mapping at
  the tokenizer level).

[Unreleased]: https://github.com/lBroth/nullpii/compare/HEAD...HEAD
