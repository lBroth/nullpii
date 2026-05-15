# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — unreleased

Unified-model + gateway track. Renamed from the in-flight `0.2.0` line to
mark the gateway preview (`@nullpii/gateway`) shipping alongside core.

### Added (post-0.2 rename)

- **`@nullpii/gateway` preview (`0.0.x`).** Self-hosted HTTP proxy for
  Anthropic Messages API. Non-streaming + streaming SSE, per-block
  `RestoreStream` for placeholders straddling delta boundaries,
  `count_tokens` passthrough, Fastify + multi-arch Docker
  (`linux/amd64,linux/arm64`) published to GHCR. Worked Claude Code
  integration walkthrough under `examples/claude-code/` with both
  HF-fetch and host-mounted-model compose variants. PLAN §1.
- **`RestoreStream` core API** (`nullpii.RestoreStream`,
  `RestoreCapable`) — SSE-safe placeholder buffer used by the gateway
  + any caller streaming LLM output. Holds open `{{...` tails across
  chunk boundaries, bounded by `MAX_OPEN_BUFFER` (256 chars).
  PLAN §2.
- **`NullPii.createSession()`** — symmetric with `destroySession()`,
  lets multi-call sanitize flows share one vault session.
- **Bench fairness re-audit.** GLiNER baselines now get native-language
  labels (instead of `_NULLPII_8` underscore form). Piiranha chunked
  with 1000-char stride / 200-char overlap to dodge 256-token
  truncation. OpenAI Privacy Filter wired via upstream `opf` Python
  API with constrained Viterbi (not naive BIOES). Phase 2 publishable
  matrix pending.

### Changed

- **Single unified GLiNER ONNX replaces the v0.1 5-shard routed stack.** No more cosine domain router, no distiluse sentence encoder, no per-domain dispatch. One LoRA, rank 32, merged into `urchade/gliner_multi_pii-v1`. Trained on a permissive-only corpus (legal attribution in [NOTICE](NOTICE) + the `lBroth/nullpii` model card).
- **Default HF download: ~6 GB → ~1.2 GB FP32** (~350 MB int8). One file `model.onnx` + `tokenizer.json` + `gliner_config.json` + `tokenizer_config.json`.
- **`src/`**: deleted `distiluse-encoder.ts`, `router-embedding.ts`, `unified-mode.ts` (transitional), `backend/multi-backend.ts`. Added `backend/unified-backend.ts` (single ORT session). `sanitize()` no longer encodes / routes — straight chunk → infer → recognizers + base64 → dedupe → vault.
- **`packages/eval/scripts/release/`**: dropped `export_router_artifacts.py` + `export_merged_lora_onnx.py`; new `export_unified_onnx.py`. `release.sh` rewritten for the unified pipeline.
- **`packages/eval/weights/`**: dropped `router/` + 5 per-domain `adapters/*`.

### Added

- **Base64-aware PII detector** (`src/base64-detector.ts`): finds base64-wrapped emails / `sk-` API keys / 13–19 digit runs and tags them at the source coordinates with score 0.99999 so cross-label dedupe picks the decoded label over the model's `secret` fallback.
- **Recognizer pack now runs on `normalized` too** (not only `escaped`): catches url/entity-encoded PII as full spans, with the hits remapped back to escaped offsets via `normToOrig`.
- **`normalize.ts` email-anchor fix**: URL `%XX` and HTML `&#NN;` decoding now restore `@`/`.`/`+`/`-` (previous `EMAIL_ANCHOR_CHARS` skip-list left fully-encoded emails undetectable; `adversarial-encoding` went 0.126 → 0.336 → 0.631 with the layered fixes).
- **Unified-model release flow**: `bash packages/eval/scripts/release/release.sh --dry-run` stages the 4-file manifest under `packages/eval/results/release/hf-staging/`; drop `--dry-run` to publish to `lBroth/nullpii`.
- **examples/05-local-model.ts** + `examples/README.md` "Loading from a local model directory" section.
- **Bench infra**: `bench_full.py:run_combo` real-batches batched-tool predictors (`is_batch=True` flag). RunPod scripts updated — `bench-on-pod.sh` default `--parallel-tools 2` (VRAM-safe), unified manifest, `NULLPII_MODEL_DIR` auto-set; `setup-on-pod.sh` now installs `onnxruntime-node` explicitly (npm optional-peerDep gotcha).

### Bench (partial, 2026-05-13)

Pod 5090 SECURE on `retrain-unified-phase1`, 14/24 datasets covered before teardown (`packages/eval/results/runpod-20260513/matrix.json`). Local M5 covers nullpii rows (pod nullpii subprocess died with `BrokenPipeError` under parallel-tools contention — fixed in `nullpii_runtime_predictor` hardening but not yet re-run). Full publishable matrix lands in the next bench cycle.

### Honest framing

v0.2 isn't tagged yet. The HF upload + the final headline numbers ship together once the full matrix re-runs cleanly.

## [0.1.0] — 2026-05-06

First public release. Local PII sanitization with reversible vault.

### Added

- npm runtime ships the full router stack: **Google distiluse** sentence encoder + 5 per-domain LoRA adapters (devops / legal / medical / narrative / enterprise) merged into the GLiNER backbone (`urchade/gliner_multi_pii-v1`, **Microsoft mDeBERTa-v3** base + GLiNER head). Cosine-similarity routing with an enterprise-route gate (margin ≥ 0.10).
- Adversarial preprocessor (`_normalize_for_detection`): NFKC + unidecode + zero-width strip + HTML entity / URL `%XX` decode + spaced-PII despace. Span offsets remap back to the original text.
- Recognizer pack (~70 patterns): URL / email / AWS / GitHub / Stripe / OpenAI / Anthropic keys / IBAN / SSN / CPF / Italian Codice Fiscale / Bitcoin (base58check-validated) / etc.
- TypeScript validators: Luhn (credit cards), IBAN mod-97, CPF mod-11×2, Italian CF check letter, BIP-13 base58check.
- Mustache placeholder format `{{PII_<TYPE>_<N>}}` (e.g. `{{PII_PRIVATE_EMAIL_0}}`). Chosen over `[[NULLPII:type:i]]` after empirical evaluation of 6 candidate formats × 6 LLM task scenarios — ~20% lower token cost (cl100k_base), no markdown / wiki-link collision, universal training signal (LLMs deeply trained on Mustache / Handlebars / Jinja2 / Anthropic-prompt-eng convention to preserve template variables). See `packages/eval/private/PLACEHOLDER_FORMAT_ANALYSIS.md`.
- `wrapForLLM(sanitized, task?)` helper — prefixes the prompt with a built-in PII-preservation hint that saturates round-trip preservation to ~100% across translate / summarise / rewrite / json / markdown / adversarial `ignore-syntax` task scenarios. Hint cost ~80 prompt tokens once; break-even at ~5 placeholders.
- Per-PUA-codepoint placeholder escape (``) — round-trip safe.
- 8-class output: `private_person`, `private_email`, `private_phone`, `private_address`, `private_date`, `private_url`, `account_number`, `secret`.
- CLI: `nullpii sanitize`, `nullpii restore`, `nullpii scan` (`--ndjson` for batch detection).

### Bench (MacBook Pro · Apple M5 Pro · 48 GB · macOS 26.4 · CPU backend, 8-dataset macro surface, fair-serial cap=5 000)

Macro F1, IoU ≥ 0.5 partial-match span scoring, `--parallel-tools 1`. 7 tools head-to-head: `nullpii` vs Microsoft Presidio, NVIDIA Nemotron-PII, piiranha, Microsoft DeBERTa-v3, GLiNER ONNX FP32, `gliner-pii-large-v1`. Per-tool matrix at `packages/eval/published-bench/matrix.csv`.

- **Mixed F1 (8 datasets) — 0.7846** vs next-best baseline `nemotron-pii-raw` 0.5912 (+0.19). nullpii wins 7 of 8 macro datasets. `nemotron-pii-test` excluded from macro (enterprise adapter in-distribution + self-bench for `nemotron-pii-raw`); row still shown in README table with ⚠.
- **Held-out OOD multilingual (6) — F1 0.7662.** Real generalisation across en + de + fr + it: `presidio-synthetic`, `ai4privacy-300k-heldout`, `isotonic-{en,de,fr,it}-heldout`.
- **In-distribution diagnostic (2) — F1 0.8396.** `nullpii-bench` ⚠ self-authored (project bench corpus, 2,421 rows) 0.7622 / `tab-echr` 0.9170. Treat as project regression test, not OOD generalisation.

### Latency (MacBook Pro · Apple M5 Pro · 48 GB · CPU backend, n=50/size)

| Input size | p50 | p95 | p99 |
|---|---:|---:|---:|
| 100 chars | 81 ms | 87 ms | 91 ms |
| 1 000 chars | 230 ms | 251 ms | 259 ms |
| 10 000 chars | 2.15 s | 2.25 s | 2.83 s |

### Cross-tool throughput (fair, serial — `--parallel-tools 1`)

7 tools × 9 canonical datasets (cap 5 000), aggregate `Σ n / Σ wall_s` per tool. Source: `packages/eval/results/bench-full-fair-20260506/matrix.json`.

mixed F1 = 8-dataset macro (nemotron-pii-test excluded from F1 aggregate, included in wall-time total).

| Tool | mixed F1 | total samples | wall (s) | samp/s |
|---|---:|---:|---:|---:|
| `presidio` | 0.3979 | 37 548 | 237.0 | **158.4** |
| `gliner-onnx-pii-fp32` | 0.4288 | 37 548 | 1 022.8 | 36.7 |
| **`nullpii`** | **0.7846** | 37 548 | 1 398.1 | 26.9 |
| `deberta` | 0.4301 | 37 548 | 1 564.6 | 24.0 |
| `piiranha` | 0.4152 | 37 548 | 1 661.1 | 22.6 |
| `gliner-pii-large-v1` | 0.4312 | 37 548 | 6 737.6 | 5.6 |
| `nemotron-pii-raw` | 0.5912 | 37 548 | 8 079.6 | 4.6 |

`presidio` (regex/SpaCy) tops throughput, lowest F1. `nullpii` runs the full distiluse + GLiNER + 5-LoRA stack and lands in the top-tier on throughput while topping F1 by **+0.19** over the next-best tool (`nemotron-pii-raw`).

### Model artifacts

- HuggingFace Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) (~6 GB FP32 — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes JSON). First call to `sanitize()` downloads everything to `~/.cache/nullpii/`.
- Raw LoRA weights ([`lBroth/nullpii-adapters`](https://huggingface.co/lBroth/nullpii-adapters), ~17 MB) — upstream of the merged repo, used by the release pipeline.
- Built on `urchade/gliner_multi_pii-v1` (Zaratiana et al., NAACL 2024, Apache-2.0). Per-domain LoRA training data composition + recipe documented on the HF model card. ⚠ The weights' effective licence is the intersection of all training-data licences — some adapters currently use non-permissive sources (ai4privacy / Isotonic), so the weights are NOT releasable under Apache-2.0 as-is; see [NOTICE](NOTICE) "BLOCKER".

### Red-team disclosures

- 3 in-distribution bench rows disclosed (`nullpii-bench`, `tab-echr`, `nemotron-pii-test`) — adapters trained on slices of those datasets, F1 reported with ⚠ memorisation flag in the per-row table.
- `CLAIM-VERIFIER-01` documents that competitor F1 claims (Presidio 0.85+, piiranha 0.99) are not reproducible with standard methodology — see `packages/eval/scripts/verify_claims.py`.

### Honest framing

Night-hobby experiment, not a production-ready PII tool, not a research paper, not a commercial product. Interesting for the engineering rigor + adversarial preprocessor, not for being state-of-the-art on F1.
