# nullpii — plan (honest hobby pivot)

Branch: `bench-runpod-on-demand`. Last refreshed 2026-05-05 (post hobby-pivot).

## Framing

This is a **night hobby project** — not a production-ready PII tool, not a research paper, not a commercial product.

Story: since I started using Claude Code I stopped playing video games. nullpii is the night toy. The interesting parts are the **engineering rigor + audit transparency**, not the F1 numbers. F1 ~0.72 macro on a leak-disclosed bench is mediocre vs vendor claims; the F1 vendor claims are **not reproducible** (see `CLAIM-VERIFIER-01` below). For real GDPR-grade PII, use Presidio. For an honest hobby experiment + adversarial preprocessor lift + audit journal, this repo.

Two deliverables:
- **HF model card**: `lBroth/nullpii-v10-router-embedding` (distiluse + 5 LoRA on `urchade/gliner_multi_pii-v1`, ~430 MB). Apache 2.0.
- **npm package**: `nullpii@0.1.0` (GLiNER base + recognizer pack + adversarial preprocessor + reversible vault). Apache 2.0.

## Status snapshot (2026-05-05)

**Done**:
- v10 LoRA training (5 adapters: devops, legal, medical, narrative, enterprise) on `urchade/gliner_multi_pii-v1`.
- Local Mac CPU bench `bench-v10-release-local`: 27 datasets × 1 shipping router. router-embedding mixed F1 0.7172, held-out non-adversarial F1 0.7008 (honest OOD). Output `packages/eval/published-bench/matrix.{json,csv}` + `confusion.json`.
- 25/25 audit findings F01–F25 closed. Test suite 191 pass / 8 skipped.
- Pipeline decision: ship `nullpii-v10-router-embedding` (distiluse, ~430 MB). distiluse wins `nullpii-bench` +0.118 (gate-tuning caveat disclosed) and adversarial-typo/unicode (preprocessor effect, also disclosed).
- TS validators (Luhn, IBAN-97, CPF, Italian CF, BTC base58check) wired into recognizers.
- Latency p50/p95 Mac M-series for both routers (`latency-bench-2026-05-05`).
- Phase A doc cleanup: nullpii positioned on `urchade/gliner_multi_pii-v1` (was `openai/privacy-filter`).
- Red-team audit: 20 inflation mechanisms documented at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`. ASYM-NORM-01 closed 2026-05-05 (bare-mode contract honest in `gliner_v2_predictor` + `gliner_nemotron_pii_predictor`).
- **CLAIM-VERIFIER-01** (2026-05-05): published competitor F1 claims (Presidio 0.85+, piiranha 0.99) **NOT reproducible** with standard methodology. Presidio on its own PresidioSentenceFaker output: span IoU 0.330, label-agnostic 0.555, seqeval 0.330, official `presidio-evaluator` package broken on Faker output. Either competitors use proprietary test sets, token-level F1 with non-comparable tokenization, or selective entity scope. Documented at `packages/eval/scripts/verify_claims.py`.
- Phase B step 1 (DEFAULT_MODEL_REPO swap): `openai/privacy-filter` → `onnx-community/gliner_multi_pii-v1`. 191 tests still pass (mock-heavy surface).
- Local cleanup: 74 dev artifact dirs + adapter checkpoint history moved to `packages/eval/results/_archive/` and `packages/eval/results/train/_archive/`. Active results dir 37 GB → 1.2 GB.

**In flight**: Phase B step 2-8 (TS GLiNER tokenizer + ONNX 6-input I/O + span decoder + tests, ~14-20 h).

For the public training summary (Art. 53 transparency), see [`TRAINING.md`](TRAINING.md). The full engineering journal is at `packages/eval/private/v10/V10_JOURNAL.md` (will be moved to public `docs/JOURNAL.md` at publish time).

## Phase B — npm runtime: drop `openai/privacy-filter`, ship GLiNER (~14-20 h)

User direction (2026-05-05): npm runtime base must match the bench (`urchade/gliner_multi_pii-v1`). Phase A landed the doc cleanup; Phase B is the code refactor.

GLiNER ONNX has a 6-input contract incompatible with the current 2-input pipeline. No JS library supports GLiNER natively (`transformers.js` doesn't include the architecture; no `gliner-js` package exists). Custom TS port required.

### GLiNER ONNX inference contract

Verified against `onnx-community/gliner_multi_pii-v1/onnx/model_q4.onnx`:

- Inputs (6): `input_ids`, `attention_mask`, `words_mask` (subtoken → word index map), `text_lengths`, `span_idx` (candidate start/end word pairs), `span_mask` (bool valid).
- Output: `logits` shape `[B, seq_len, num_spans, num_classes]` — argmax over classes per span > threshold = predicted span.
- Tokenization: SentencePiece + special tokens `<<ENT>>` (between labels), `<<SEP>>` (between label list and text). Prompt: `<<ENT>>private_email<<ENT>>private_person<<ENT>>… <<SEP>> {text}`.

### Step-by-step

| Step | Effort | Status |
|---|---:|---|
| 1. Swap `DEFAULT_MODEL_REPO` `'openai/privacy-filter'` → `'onnx-community/gliner_multi_pii-v1'` | 5 min | ✅ done 2026-05-05 |
| 2. `src/gliner-tokenizer.ts` (~150 LOC) — SentencePiece + prompt-formatting + words_mask tracking | 3-5 h | 🔴 pending |
| 3. `src/backend/gliner-ort-backend.ts` (~120 LOC) — wraps `OrtBackend` with 6-input feed | 3-4 h | 🔴 pending |
| 4. `src/gliner-spans.ts` (~80 LOC) — `span_idx` candidate pairs (max_span_length default 12) + `span_mask`. `src/gliner-decoder.ts` (~100 LOC) — argmax + threshold filter, map (start_word, end_word) → char offsets | 2-3 h | 🔴 pending |
| 5. Modify `src/nullpii.ts` `sanitize()`: drop `viterbiBioesDecode` call; wire GLiNER decoder. Output spans flow through unchanged `runRecognizers + filterNeverPii + boundary refine + vault` | 1-2 h | 🔴 pending |
| 6. Drop `src/labels-bioes.ts` (64 L), `src/viterbi.ts` (276 L), transition-biases types | 30 min | 🔴 pending |
| 7. Update tests: drop viterbi/bioes tests; add `gliner-tokenizer.test.ts` (round-trip vs Python) + `gliner-decoder.test.ts` (synthetic logits → spans). F1-parity ±0.005 vs Python `gliner_v2_predictor` baseline on 10-sample fixed subset | 3-4 h | 🔴 pending |
| 8. Smoke test 3 backends (CPU/MPS/CUDA) + CLI sanitize/restore round-trip | 1 h | 🔴 pending |

**Risk**: F1 mismatch from tokenizer / words_mask edge cases. Mitigation: side-by-side test vs Python output until token-level identical on 10-sample fixture.

**Out of scope of Phase B**: shipping the LoRA router stack (merged-LoRA ONNX export). Phase B closes "different model" half of CONFIG-SHIPPED-01; LoRA-shipping closes "different pipeline" half — deferred. README will state explicitly: "npm = base GLiNER + post-process; HF = full router stack measured in bench. v0.2 will unify if there's interest."

## Reduced bench (post Phase B)

Drop comprehensive 27-dataset × 19-tool matrix. Keep targeted hobby-bench:

| Aspect | v10 release-grade plan | Honest hobby plan |
|---|---|---|
| Datasets | 27 | **10** |
| Tools | 19 | **9** |
| Cells | 513 | **90** |
| Wall time Mac CPU `--parallel-tools 4` | ~12-15 h | **6-8 h** |
| Cloud GPU sprint | required ($15-20) | **dropped** |

**Reduced tool list** (brand recognition + we have working adapters for all):
- `nullpii-v10-router-embedding`
- `presidio` (well-known reference)
- `nemotron-pii-raw` (in-distribution disclosed)
- `piiranha` (popular HF)
- `deberta` (popular HF)
- `gliner-onnx-pii-fp32` (our base, fair)
- `gliner-pii-large-v1` (knowledgator, popular)
- `openai-bioes` (proper opf usage)

**Reduced dataset list** (where we win + canonical PII benches):
- `nullpii-bench` (project gold, OOD-ish, in-template-family disclosed)
- `tab-echr` (legal, in-distribution disclosed)
- `nemotron-pii-test` (Nemotron own, in-distribution disclosed for `enterprise` route)
- `presidio-synthetic` (Presidio own data — fair self-bench)
- `ai4privacy-300k-heldout-v10` (held-out, offset 100k+)
- `isotonic-en-heldout-v10`, `isotonic-de-heldout-v10` (multilingual heldout)
- `adversarial-typo`, `adversarial-unicode`, `adversarial-code` (where preprocessor wins)

## Open work tables

### Bench / publish

| # | Item | Effort | Status |
|---|---|---:|---|
| Phase B steps 2-8 — TS GLiNER tokenizer + 6-input ONNX I/O + span decoder + tests | ~14-20 h | ✅ done 2026-05-05 |
| Ship full router stack in npm — distiluse encoder ONNX + 5 merged-LoRA shards + TS router + multi-backend lazy-loader + nullpii.ts wire | ~7-9 h | ✅ done 2026-05-05 |
| Bench wire `nullpii` tool — subprocess `node bin/nullpii.mjs scan --ndjson` (canonical user-facing row) | 1 h | ✅ done 2026-05-05 |
| Drop dead TS surface — `viterbi.ts`, `labels-bioes.ts`, `span-decoder.ts`, `tokenizer.ts`, `chunking.ts`, `transition-biases.ts`, `ModelRefConfig` | 30 min | ✅ done 2026-05-05 |
| Brand attribution — Microsoft Presidio / NVIDIA Nemotron / Google distiluse / Microsoft mDeBERTa-v3 / OpenAI in user-facing docs | 30 min | ✅ done 2026-05-05 |
| Bump `package.json` 0.0.7 → 0.1.0 | trivial | ✅ done 2026-05-05 |
| CHANGELOG `[0.1.0]` entry | 30 min | ✅ done 2026-05-05 |
| README first-call download disclaimer (~6 GB from HF on first `sanitize()`) | 5 min | ✅ done 2026-05-05 |
| Move bench results to `packages/eval/published-bench/` (out of gitignored `results/`) | 5 min | ✅ done 2026-05-05 |
| HF push pipeline — `release.yml` `hf-push` job + `push-to-hf.sh` (build + stage + upload to `lBroth/nullpii-v10-router-embedding`) | 1 h | ✅ done 2026-05-05 |
| HF adapters one-shot push — `push-adapters-to-hf.sh` writes raw LoRA weights + prototypes to `lBroth/nullpii-v10-adapters` | 30 min | ✅ done 2026-05-05 |
| **Commit + tag + push v0.1.0 — user runs git** | 5 min | 🔴 user-action |
| Run reduced bench (9 × 10) | Mac CPU `--parallel-tools 4` overnight | 6-8 h | 🔴 post-publish (validate numbers) |
| Polish README (~150 LOC, honest hobby framing) | rewrite | 1 h | 🟡 partial — current README at ~200L |
| Move `private/v10/V10_JOURNAL.md` → public `docs/JOURNAL.md` | move + diff polish | 30 min | 🔴 |
| Write `docs/BENCH_RUNBOOK.md` (Mac CPU reproducer steps) | new | 30 min | 🔴 |

### 🔴 BLOCKERS before tag v0.1.0

#### 1. Strip dead predictors from `adapters.py`

After dropping unused tool builders from `bench_full.py` (commit `526dfa0`), the matching predictor function bodies in `packages/eval/src/nullpii_eval/adapters.py` are uncalled but still bulk up the file (~3580 LOC). Drop:

- `gliner2_predictor`
- `openai_pipeline_batch_predictor` / `openai_pipeline_predictor` / `openai_bioes_predictor` / `openai_official_predictor`
- `scrubadub_predictor`
- `aws_comprehend_predictor` / `gcp_dlp_predictor` / `azure_pii_predictor`
- `nullpii_pool_predictor` / `nullpii_predictor` (legacy daemon variants)
- `gliner_pii_predictor`, `make_best_ensemble`, `gliner_chunked_predictor`, `complementary_v6_v8_predictor` (legacy)
- `encoding_deobf_predictor` / `whitespace_deobf_predictor` / `stopword_filter_predictor` / `semantic_verifier_predictor` / `tiny_verifier_predictor` (ablations)

Plus owning helper constants (`_OPENAI_LABELS`, etc.).

Approach: grep for callers per function (confirm none), delete body + owned helpers, smoke `python -c "from nullpii_eval.adapters import *"`, run pytest in `packages/eval/tests/`, smoke bench (1 dataset × 8 tools × 10 samples). Estimated 30-45 min. Tracked as task #24.

#### 2. Fix nullpii subprocess crash

Overnight bench 2026-05-05 23:10 revealed: the canonical `nullpii` row (`node bin/nullpii.mjs scan --ndjson` subprocess) crashes on EVERY dataset. First failure: `RuntimeError: nullpii subprocess closed stdout unexpectedly` at idx=53 on `nullpii-bench`. Subsequent: `BrokenPipeError: [Errno 32] Broken pipe` at idx=0 of every later dataset — pool poisoned. Net: 10/10 nullpii cells fail (zero data points for the user-facing row).

Other 7 tools work; Python re-impl `nullpii-v10-router-embedding` numbers match published bench exactly (sanity passes).

Investigation steps for tomorrow:

1. **Reproduce manually**: `node bin/nullpii.mjs scan --ndjson --model-dir /tmp/nullpii-stack-test --backend cpu`, pipe ~100 sample texts from `nullpii-bench` (or `presidio-synthetic`) on stdin, observe exit and stderr. Find the input that kills the daemon.
2. **Read** `src/cli/commands/scan.ts:runNdjson` — confirm the for-await loop catches per-sample errors, doesn't break on empty lines / malformed input / sanitize exceptions.
3. **Add per-sample try/catch** in `runNdjson` so a single failing sample emits `{"error": "..."}` instead of throwing and killing the daemon. SIGPIPE handler for graceful exit on broken stdout.
4. **Re-test** subprocess with bench harness on a small subset before relaunching overnight.

Estimated: 1-3 h debug + fix + retest. Must land before v0.1.0 tag — shipping a release where the published canonical row crashes on real input is unacceptable.

### Release commit + tag (user-action)

Pre-flight before tagging:

1. **Subprocess crash fix landed + bench rerun produces valid `nullpii` cells** (see blocker above).
2. `huggingface-cli login` locally
3. `bash packages/eval/scripts/release/push-adapters-to-hf.sh` — push raw LoRA + prototypes to `lBroth/nullpii-v10-adapters` (one-shot)
4. GitHub repo Settings → Secrets: add `NPM_TOKEN` + `HF_TOKEN`

Commit + push:

```bash
# stage everything (Phase B v2 work + cleanups + docs)
git add -A
git commit -m "release(v0.1.0): full router stack — distiluse + 5 merged-LoRA + recognizer pack + audit"

# tag triggers the release.yml workflow:
#   verify (lint + typecheck + test + build + license + circular + sbom)
#   → publish (npm publish --provenance)
#   → hf-push (build + stage 6 GB + upload to lBroth/nullpii-v10-router-embedding)
#   → github-release (extract CHANGELOG [0.1.0] body + attach bom.json)
git tag v0.1.0
git push origin phase-b-gliner-ts
git push origin v0.1.0
```

Post-release verification:

- npmjs.com/package/nullpii shows `0.1.0`
- huggingface.co/lBroth/nullpii-v10-router-embedding has all artifacts
- `git tag --list 'v*'` shows `v0.1.0`
- GH release page contains the CHANGELOG body + `bom.json` SBOM

### What is NOT on the work list right now

These were previously planned but **dropped at hobby pivot 2026-05-05**:

- **Cloud GPU sprint** (B1 + B2 — bare-mode competitor matrix on 5090 + Linux x86 latency). Cost vs benefit poor for hobby project; Mac CPU bench numbers good enough for the narrative.
- **Adapter retrain sprint** (A1-A5 — re-train `enterprise` LoRA without Nemotron). Disclosure-only resolution: `nemotron-pii-test` is documented as in-distribution diagnostic, not OOD claim.
- **Honest-numbers patches** (H1-H11 — margin sweep, INDIST stripping, `--policy exact` flag, per-locale split, etc.). Disclosure-only resolution: caveats documented in README + model cards.
- **Held-out routing-eval corpus** (500 docs hand-annotated). Required for production claim, not for hobby.
- **Merged-LoRA ONNX export** (closes CONFIG-SHIPPED-01 fully). Deferred to v0.2 if there's interest.
- **Operational / shipping items** (O1-O9 — CI regression bench, security disclosure timeline, performance regression budget, license audit). Hobby project, not production release path.
- **Customer-facing items** (C1-C4 — getting-started tutorial, integration recipes, FAQ). Defer until users exist.
- **Review-grade compliance** (R1-R3 — threat model, data residency claim, backwards-compat policy). Out of scope for hobby.
- **Use-case showcase doc** (B4 — concrete win/lose examples). Nice-to-have, not blocking publish.
- **DPIA template regen** (B3 — needs cloud-sprint output). Dropped with cloud sprint.
- **Portkey + LiteLLM integration shims**. Distribution multipliers — work after npm exists + has users.
- **Branch merge to `main`**. Decide post-publish.

### Permanent exclusions

- Cloud-API rows (`aws-comprehend`, `gcp-dlp`, `azure-pii`) — paid + lock-in. Available in `bench_full.py` via opt-in `--tools` but excluded from canonical bench.
- Per-domain adapter rows as user-facing tools — internal building blocks for the routers only.
- Older nullpii variants (`nullpii`, `nullpii-v8`, `nullpii-v9`, `nullpii-ensemble-*`, `nullpii-ablation-*`, `nullpii-runtime`, `nullpii-v10-router-{hybrid,hybrid-v2,embedding-expanded}`, `regex`-only, wrapped `gliner+regex` etc.) — purged from `bench_full.py` on 2026-05-04.
- **Feature flags / runtime toggle service** (LaunchDarkly / GrowthBook / Unleash). nullpii is a local library — no central toggle service makes sense, no outbound network call (would violate privacy guarantee), determinism required for compliance audit. Behaviour configured per-instance via typed `NullPiiConfig`. Re-evaluate only if a SaaS / multi-tenant product layer is built on top.
- **Multi-tenant / per-tenant config** runtime layer. Same reasoning — nullpii is a library, not a service. If a buyer needs per-tenant policy, they construct multiple `NullPii` instances and route at the application layer.

## Audit findings status

| Tier | Findings | Status |
|---|---|---|
| F-series (audit 2026-05-04) | F01-F25 | 25/25 closed |
| Red-team (2026-05-05) | LEAK-AI4-OFFSET-01, LEAK-TAB-LEGAL-01, LEAK-NEMO-ENTERPRISE-01, TUNE-ENTGATE-01, CONFIG-SHIPPED-01, LEAK-TAB-GENERAL-01, LEAK-ISO-OFFSET0-01, LEAK-DEVPASTE-TEMPL-01, ASYM-NORM-01, HARNESS-PARTIAL-IOU-01, LANG-CJK-OMITTED-01, LANG-MACRO-MISLABEL-01, RECALL-HEADLINE-01, TUNE-F11-NULLPII-BENCH, REPRO-RUNTIME-01, SEED-VARIANCE-01, HARNESS-EMPTYDOC-01, LATENCY-COLDSTART-01, LATENCY-WALLS-01, LMSYS-ENRON-OMIT-01 | ASYM-NORM-01 ✅ closed; CONFIG-SHIPPED-01 50% (Phase A done, Phase B in progress); rest **disclosed in docs**, not fixed (hobby project — disclosure is the resolution) |
| New 2026-05-05 | CLAIM-VERIFIER-01 | ✅ open finding documented (competitor claims 0.85+ not reproducible) |

For full red-team report including severity + Δ F1 estimate per finding, see `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`.

## Sign-off

Hobby pivot 2026-05-05. Path narrowed from "publishable production tool with cloud-validated head-to-head matrix" → "honest night experiment, audit journal, reduced Mac CPU bench, HF + npm publish".

Next concrete checkpoint: Phase B step 2-3 complete (TS GLiNER tokenizer + ONNX 6-input I/O working on a 1-sample smoke test). ETA tomorrow afternoon.
