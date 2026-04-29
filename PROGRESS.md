# Progress

## Version: 0.9.0 — release-ready (publish deferred)

## Status

Local pipeline complete end-to-end:

- Detection runs locally on `openai/privacy-filter` (Apache-2.0)
- Reversible vault: sanitize → LLM → restore byte-for-byte
- Backends: CPU / MPS / CUDA / ROCm — all tree-shakable subpath exports
- CLI: `npx nullpii scan|sanitize|restore|models|benchmark`
- GLiNER v2 fine-tune (HF model `lBroth/nullpii-gliner-pii-v2`):
  PT FP32 + ONNX FP32 + ONNX INT4, multilingual F1 0.93–0.97 on
  isotonic-en/de/fr/it (preview, n=100)
- Build-time pipeline (`packages/convert/`): pinned upstream revision,
  SHA256 + sigstore verify, smoke + per-format consistency checks
- 100% permissive license tree (zero LGPL/GPL/AGPL)
- Tests: 123 pass, 1 skipped (network-gated)
- Coverage: ≥85% lines / ≥80% branches
- Docs site: VitePress build clean

## Deferred publish actions

See `TODO_PUBLISH.md`. Requires user approval — not auto-executed.

- npm publish `nullpii@1.0.0` (with `--provenance`)
- HuggingFace mirror `nullpii/privacy-filter-onnx`
- HuggingFace upload `lBroth/nullpii-gliner-pii-v2` (PT + ONNX FP32 + INT4 + model card)
- GitHub Pages deploy (workflow ready)
- Hardware-gated tests (CUDA/ROCm runners)
- Full bench (n≥5k per dataset) for the v2 fine-tune to graduate from preview

## Notable decisions

### Single npm package
Originally split across `@nullpii/types`, `@nullpii/core`,
`@nullpii/backend-*`. Collapsed to one `nullpii` package with
conditional subpath exports + optional `peerDependency` on
`onnxruntime-node`. Tree-shaking preserved; one release / one README /
one changelog.

### No own model conversion
The upstream HF repo already publishes ONNX (fp32 / fp16 / int8 /
int4 / int4f16). The model uses a custom architecture with no public
modeling code, so re-converting would introduce risk for no gain.
Pipeline = fetch + cryptographic verify, not transform.

### CPU is the fastest path on macOS today
ORT's `CoreMLExecutionProvider` cannot service every op in the custom
architecture and falls back to CPU mid-graph. Until upstream adds the
missing ops or we ship a separate CoreML mlpackage, `'cpu'` is the
recommended backend on macOS.

### WebGPU dropped
`@huggingface/transformers` was the only realistic browser path and it
transitively pulled `sharp` → `@img/sharp-libvips-*` (LGPL-3.0-or-later).
To keep the dependency tree 100% permissive, the WebGPU backend was
removed entirely. May return when an LGPL-free browser ONNX path exists.

### Tokenizer library
`@anush008/tokenizers` (NAPI bindings to upstream Rust tokenizers, MIT)
instead of `@huggingface/transformers` JS — the latter does not expose
`offset_mapping` at the tokenizer level, and the offsets are mandatory
for char-level span reconstruction.
