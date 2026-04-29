# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- TypeScript ESM library (`nullpii` on npm) with `sanitize` / `restore`
  + reversible in-memory vault.
- Constrained Viterbi BIOES decoder over `openai/privacy-filter` ONNX,
  pinned by SHA in `src/defaults.ts` (`DEFAULT_MODEL_REVISION`).
- Backends: `cpu`, `mps`, `cuda` (subpath exports, tree-shakable).
  Variants: `fp32`, `int4`, `auto` (default `int4`).
- CLI: `nullpii scan|sanitize|restore|models|prefetch|doctor|benchmark`.
- Recognizer packs (`packages/recognizers-{cloud,finance,id-it}`) for
  AWS / GitHub / Stripe keys, IBAN/Luhn, Italian CF + PIVA.
- Research kit (`packages/eval/`, gitignored): bench harness, dataset
  loaders (ai4privacy, Isotonic, project-bundled `nullpii-bench`),
  GLiNER fine-tune scripts.
- Fine-tuned model `lBroth/nullpii` on HuggingFace Hub: PT FP32 +
  ONNX FP32 + ONNX INT4 (`MatMulNBitsQuantizer`). Multilingual F1
  0.93–0.97 on isotonic-en/de/fr/it (preview, n=100). Publication
  script: `scripts/release/push-to-hf.sh`.
- Tests: 145 pass / 8 skipped (artifact-gated). Coverage thresholds
  85% lines / 80% branches in CI.

[Unreleased]: https://github.com/lBroth/nullpii/compare/HEAD...HEAD
