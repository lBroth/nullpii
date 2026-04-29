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
- **Model fetch at runtime** — `src/model-manager.ts` pulls
  `openai/privacy-filter` at the pinned commit SHA defined in
  `src/defaults.ts` (`DEFAULT_MODEL_REVISION`). The earlier
  Python build-time fetch+verify pipeline was dropped; reproducibility
  lives in the SHA pin and HF's own integrity guarantees.
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
  `CudaBackend`. Tree-shakable via subpath exports.
- **Router + Model Manager** — `selectBackend(modelDir, config)` with
  dynamic backend imports and CUDA → MPS → CPU auto priority;
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
- **GLiNER fine-tune (nullpii)** — two-round fine-tune of
  `urchade/gliner_multi_pii-v1` on ai4privacy + Isotonic + the project's
  own dev-prompts-synth generator. Multilingual F1 0.93–0.97 on
  isotonic-en/de/fr/it (preview, n=100). Published as PT FP32 +
  ONNX FP32 + ONNX INT4 (`MatMulNBitsQuantizer`). HF model id
  `lBroth/nullpii` (publication script under
  `scripts/release/`).
- **Documentation** — README with quick-start examples, this
  CHANGELOG, CONTRIBUTING.md, SECURITY.md, plus the research write-up
  in `COMPARISONS.md` + `EVAL_RESULTS.md` at the repo root.

### Architecture decision

Project shipped as a single `nullpii` npm package (was originally
multi-package). Backend tree-shaking preserved via conditional subpath
exports + optional `peerDependency` `onnxruntime-node`.

### Scope (focused on the comparison study)

The project pivoted from a Claude Code plugin to a research +
reproducibility kit comparing `openai/privacy-filter` (the well-known
1.5B model) against a fine-tuned `urchade/gliner_multi_pii-v1` (278M)
on the same PII detection task. The npm library is the runtime over
`openai/privacy-filter`; the HF model is the GLiNER fine-tune; the
write-up lives in `COMPARISONS.md` + `EVAL_RESULTS.md` at the repo
root. The Claude Code plugin and Anthropic SDK middleware that earlier
0.x versions shipped have been removed; previous code is preserved on
the `plugin-backup-v0.0.9` branch.

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
