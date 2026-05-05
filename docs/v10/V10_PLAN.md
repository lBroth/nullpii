# v10 LoRA-per-domain release plan

Branch: `bench-full-2026-05-05`. Last refreshed 2026-05-05.

## Status snapshot (2026-05-05)

**Completed**:
- v10 LoRA training (5 adapters: devops, legal, medical-experimental, narrative, enterprise) on `urchade/gliner_multi_pii-v1`.
- Unified release bench on Mac CPU: 27 datasets × 2 nullpii routers. nullpii-v10-router-embedding macro F1 **0.7172**, router-xlmr **0.7076**. Output `packages/eval/results/bench-v10-release-local/matrix.{json,csv}` + `confusion.json`.
- 25/25 audit findings closed (F01–F25). Test suite 191 pass / 8 skipped.
- Pipeline decision: ship `nullpii-v10-router-embedding` (distiluse, ~430 MB).
- 8 HF model card drafts, README + COMPETITIVE_ANALYSIS + CHANGELOG refreshed for v10.
- Per-class confusion publisher (`packages/eval/scripts/confusion_report.py`) + `per_class.md`.
- TS validators (Luhn, IBAN-97, CPF, Italian CF, BTC base58check) wired into recognizers.
- Latency p50/p95 Mac M-series for both routers (`latency-bench-2026-05-05`).
- Phase A doc cleanup: `openai/privacy-filter` framing dropped; nullpii positioned on `urchade/gliner_multi_pii-v1`.
- Red-team audit: 20 inflation mechanisms documented at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`.

**Currently in flight**: clean baseline re-bench post-audit-fixes at `bench-v10-baseline-2026-05-05` (2 routers × 27 datasets, ~5-6 h Mac CPU). Validates that F07/F23/F24 fixes are F1-stable before Phase B starts.

For the public training-procedure summary (Art. 53 transparency), see [`TRAINING.md`](TRAINING.md). The full step-by-step engineering journal is internal at `packages/eval/private/v10/V10_JOURNAL.md`. The strategic assessment (rank C+ with 3 reasons since-closed) is internal at `packages/eval/private/v10/STRATEGIC_ASSESSMENT_2026-05-04.md`.

## Path to grade A (top compound-leverage moves)

Two deliverables remain on the path-to-A list. Both unblock multiple downstream wins.

| # | Deliverable | Status | Unlocks |
|---|---|---|---|
| 1 | **Held-out routing-eval corpus** (500 docs hand-annotated, 5 domains × 100) | 🔴 OPEN | Honest router F1 (no test-set tuning of the 0.10 enterprise gate) + DPIA buyer-facing per-class numbers + Path A/B/C v11 decision gate |
| 2 | **Merged-LoRA ONNX export** → npm runtime consumes v10 LoRA stack | 🔴 OPEN | Closes CONFIG-SHIPPED-01's "different pipeline" half. ~1-2 days work |

Publishability today (per strategist + red-team review):

| venue | ready? | strongest framing |
|---|---|---|
| HN / Lobsters / r/ML | ❌ NO (need bare-mode competitor head-to-head + npm runtime running v10) | After fixes: "OSS local reversible PII vault for npm — beats Presidio +X F1, beats Nemotron-PII +0.16 multilingually" |
| Technical blog | ⚠ partial | Adversarial preprocessor lift as standalone finding (adv-unicode 0.466→0.936; adv-whitespace 0.106→0.393) — travels furthest as isolated insight |
| Academic paper / arxiv | ❌ NO | Missing for NeurIPS / ACL: held-out routing eval, multi-seed runs, statistical significance, full ablations, ethics statement covering Art. 9 invisibility. Workshop track realistic in 2-3 months focused work |

## Phase B — npm runtime refactor: drop `openai/privacy-filter`, ship GLiNER (1-2 days)

User direction (2026-05-05): `openai/privacy-filter` does NOT belong in core nullpii. It stays as a competitor row in `bench_full.py` for the bare-mode reference, but the npm runtime base must match the bench (`urchade/gliner_multi_pii-v1`). Phase A landed the doc cleanup; Phase B is the code refactor.

**Why non-trivial**: GLiNER ONNX has a 6-input contract incompatible with the current 2-input pipeline. No JS library supports GLiNER natively (`transformers.js` doesn't include the architecture; no `gliner-js` package exists). Custom TS port required.

**GLiNER ONNX inference contract** (verified against `onnx-community/gliner_multi_pii-v1/onnx/model_q4.onnx`):
- Inputs (6): `input_ids`, `attention_mask`, `words_mask` (subtoken → word index map), `text_lengths`, `span_idx` (candidate start/end word pairs), `span_mask` (bool valid).
- Output: `logits` shape `[B, seq_len, num_spans, num_classes]` — argmax over classes per span > threshold = predicted span.
- Tokenization: SentencePiece + special tokens `<<ENT>>` (between labels), `<<SEP>>` (between label list and text). Prompt: `<<ENT>>private_email<<ENT>>private_person<<ENT>>… <<SEP>> {text}`.

**Step-by-step**:

1. **Drop**: `src/labels-bioes.ts`, `src/viterbi.ts`, BIOES decode path in `src/nullpii.ts:158-176`.
2. **Add** (~450 lines TS):
   - `src/gliner-tokenizer.ts` (~150) — SentencePiece + prompt-formatting + words_mask tracking.
   - `src/gliner-spans.ts` (~80) — `span_idx` candidate pairs (max_span_length default 12) + `span_mask`.
   - `src/gliner-decoder.ts` (~100) — argmax + threshold filter, map (start_word, end_word) → char offsets.
   - `src/backend/gliner-ort-backend.ts` (~120) — wraps OrtBackend with the 6-input call signature; subclass for cpu/mps/cuda.
3. **Modify** `src/nullpii.ts` `sanitize()`: tokenizer call returns 6-tuple + offset map; `inferChunk` calls `gliner-decoder.decodeSpans`. Output spans flow through unchanged `runRecognizers + filterNeverPii + boundary refine + vault.sanitize`.
4. **`src/defaults.ts`**: `DEFAULT_MODEL_REPO` `'openai/privacy-filter'` → `'onnx-community/gliner_multi_pii-v1'`. Pin revision `2e0397a7e8a250d76c37122232b3cbde42c8d629`. `MANAGER_DEFAULT_VARIANT 'int4'` → `onnx/model_q4.onnx` (894 MB working per Python bench).
5. **Tests**: drop `viterbi`/`labels-bioes` tests; add `gliner-tokenizer.test.ts` (round-trip vs Python reference) + `gliner-decoder.test.ts` (synthetic logits → spans). F1-parity threshold ±0.005 vs Python `gliner-onnx-pii-fp32` baseline (~0.34-0.40 nullpii-bench).
6. **Bench integration**: add new tool def `nullpii-runtime-default` in `bench_full.py` mirroring TS pipeline (bare GLiNER + recognizer pack + normalize + never-PII filter + vault). Re-bench just that tool × 27 datasets (~2-3 h Mac CPU). Publish as "default-config F1" column in README.

**Risk**: F1 mismatch from tokenizer / words_mask edge cases. Mitigation: side-by-side test against Python `gliner_v2_predictor` outputs on a fixed 10-sample subset; iterate until token-level identical.

**Out of scope of Phase B**: shipping the LoRA router stack (merged-LoRA ONNX export — separate roadmap item, see Path-to-A #2). Phase B alone closes CONFIG-SHIPPED-01's "different model" half; LoRA-shipping closes the "different pipeline" half.

## Open work tables

### Bench / harness improvements (local)

| # | Item | Local? | Effort | Status |
|---|---|---|---|---|
| B1 | **Latency Linux x86 + 5090 GPU** rows (cold-start incluso) — extend `bench_latency.py` per cold-start measurement (model load + first inference) | ☁ cloud GPU | 30 min GPU + 2 h code | 🔴 cloud sprint |
| B2 | **Bare-mode competitor matrix** on 5090 GPU (Presidio + GLiNER-base + piiranha + deberta + scrubadub + nemotron-pii-raw + openai naive/BIOES/Viterbi) | ☁ cloud GPU | 6-8 h GPU + setup | 🔴 cloud sprint |
| B3 | **DPIA template regen** (`docs/compliance/DPIA_TEMPLATE.md`) — gated on B1 + B2 output (needs competitor F1 + GPU latency) | ✅ local once B1+B2 land | 2 h | 🔴 post-cloud |
| B4 | **Real-world side-by-side use-case showcase** (post final-version pick) — extend `packages/eval/private/train/qualitative_compare.py` for a 30-50 sample curated set; output `docs/showcase/USE_CASES.md` + new section in README ("When nullpii wins / loses — concrete examples"). Honest-framing constraint: include both wins AND losses, no cherry-pick | ✅ local | 4-6 h | 🔴 post-final-version (gated on B2 + version pick) |

### Honest-numbers patches (red-team — must address before publishing)

Independent red-team auditor review (general-purpose subagent, 2026-05-05) surfaced 20 inflation mechanisms. Full report at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`. The 5 critical blockers:

| ID | Finding | Severity | Fix path |
|---|---|---|---|
| **LEAK-TAB-LEGAL-01** | TAB ECHR test docs share 50-char shingles with **127/127** legal training chunks (60/127 verbatim 200-char windows). `tab-echr` row is in-distribution generalisation, not OOD. F1 0.886 likely 0.55-0.70 OOD | **Critical** | Strip `tab-echr` from headline 27-row macro → mark `tab-echr-INDIST`. OR retrain `legal` adapter on non-TAB corpus (HUDOC/EDGAR-redacted) |
| **LEAK-NEMO-ENTERPRISE-01** | `enterprise` adapter trained on Nemotron train; benched on Nemotron test. Disclosed in model card but still in headline macro F1 | **Critical** | Strip `nemotron-pii-test` from headline → `*-INDIST` diagnostic |
| **TUNE-ENTGATE-01** | `router.py:517-531` source admits 0.10 enterprise-gate margin chosen to maximise `nullpii-bench` F1. At margin=0.05, F1 drops 0.11. Entire +0.118 distiluse-vs-xlmr advantage on `nullpii-bench` is largely test-set-tuning artifact | **Critical** | Re-bench with `gated_routes={"enterprise": x}` for `x ∈ {0.0, 0.05, 0.10, 0.15}`; publish range. Tune for real on a held-out routing-eval corpus when built |
| **CONFIG-SHIPPED-01** | npm runs different system from bench. Phase A doc fix landed; full code fix = Phase B refactor (see above) | **Critical** | Phase B + add `default-config` column in README |
| **LEAK-DEVPASTE-TEMPL-01** | `nullpii-bench` and `dev-paste-synth-train` share template family by construction. Bench is in-template-family, not OOD | **Critical** | Reclassify `nullpii-bench` from "OOD gold standard" to "in-template-family but disjoint instances". Build a hand-curated OOD set from real LLM logs (with consent) for true OOD claims |

High-severity (10): see `RED_TEAM_AUDIT_2026-05-05.md`. Summary: LEAK-AI4-OFFSET-01, LEAK-TAB-GENERAL-01, LEAK-ISO-OFFSET0-01, ASYM-NORM-01, HARNESS-PARTIAL-IOU-01, LANG-MACRO-MISLABEL-01, LANG-CJK-OMITTED-01, RECALL-HEADLINE-01, TUNE-F11-NULLPII-BENCH, REPRO-RUNTIME-01.

Medium / Low (4): HARNESS-EMPTYDOC-01, LATENCY-COLDSTART-01, LATENCY-WALLS-01, LMSYS-ENRON-OMIT-01.

#### Honest-numbers patch order (post cloud-sprint)

| # | Patch | Files |
|---|---|---|
| H1 | Re-bench with `gated_routes={"enterprise": 0.0}` — publish margin sensitivity range | `bench_full.py` (no code change, just multiple runs) + `router.py:517-531` (externalise gate constant to config) |
| H2 | Strip `tab-echr` and `nemotron-pii-test` from headline 27-row macro; emit `*-INDIST` diagnostic columns | `bench_full.py` matrix aggregation + `metrics.py` |
| H3 | Add `--policy {partial,exact}` flag; emit both columns in `matrix.csv` | `bench_full.py:441` + `metrics.py:80-94` |
| H4 | Per-locale split for `nullpii-bench` (en/it/de/fr/es) | `bench_full.py` loader + matrix.csv columns |
| H5 | Add `cold_start_ms` column to `bench_latency.py` — measures from `build_predictor()` start to first prediction completion | `bench_latency.py:255-261` |
| H6 | Fix bogus `wall_s` / `samples_per_s` on full-resume cells | `bench_full.py:604-635` |
| H7 | Add `gliner-onnx-pii-fp32+norm` parallel rows to attribute preprocessor lift | `bench_full.py` tool defs |
| H8 | Add `default-config` column (`openai-bioes` today, `nullpii-runtime-default` post-Phase-B) for what `npm i nullpii` ships | `bench_full.py` tool defs + README |
| H9 | README: "worst-class recall" + "default-config F1" + "strict-match F1" columns alongside macro F1 | `README.md` |
| H10 | Ship `pip freeze` + Python version + hardware fingerprint in bench output dir | `bench_full.py` startup |
| H11 | Reclassify `nullpii-bench` from "OOD gold standard" to "in-template-family but disjoint instances" | `README.md` + dataset README |

Order of remaining work: **cloud sprint (B1 + B2)** → **honest-numbers patches (H1–H11)** → **DPIA regen (B3)** → **Phase B TS refactor** → **use-case showcase (B4)** → **README + COMPETITIVE_ANALYSIS final refresh**. Phase B can run in parallel with cloud sprint since it touches only `src/` and is decoupled from Python eval.

### Operational / shipping (newly added)

| # | Item | Effort | Notes |
|---|---|---|---|
| O1 | **Cloud GPU sprint logistics** — concrete cmd + cost estimate. Pick provider (RunPod / Lambda / Vast). Setup script (`packages/eval/private/runpod/launch.sh` already exists — verify still works). Estimated cost $3-5 for one-shot bench | 1-2 h prep + 6-8 h compute | One-time, gated by user availability |
| O2 | **Phase B test plan** — F1 parity threshold ±0.005 TS-vs-Python on a 10-sample fixed subset; specific test fixtures (chosen from `nullpii-bench` covering en + it + de + secret + multi-span) | 2 h | Pre-Phase-B |
| O3 | **Release version cycle** — semver path. Currently `package.json` 0.0.7. Phase B = breaking (drops `viterbiBioesDecode` exports) → 0.1.0 minimum. Define: v0.1.0 = post-Phase-B (npm GLiNER); v0.2.0 = post-merged-LoRA ONNX (npm v10 router); v1.0.0 = post-held-out-routing-eval validated | 30 min | Documentation |
| O4 | **Migration / breaking changes** doc — when Phase B lands, what npm users see. Removed exports list, NullPiiConfig changes (if any), upgrade recipe | 1 h | Pre-Phase-B-publish |
| O5 | **Compatibility matrix** — Node 22 + 24 testing. Browser/WebGPU support deferred (Node-only library, document explicitly) | 2 h | Pre-publish |
| O6 | **CI regression bench** — add a `ci-bench-smoke.yml` GitHub Action that runs `bench_full.py --tools nullpii-v10-router-embedding --datasets nullpii-bench --max-per-dataset 100` on every PR; fail if F1 drops > 0.02 from the canonical | 3-4 h | Pre-publish |
| O7 | **Performance regression budget** — define "block release" thresholds. Current state: p50 router-embedding 226 ms on 1 KB Mac CPU. Budget: p95 ≤ 500 ms on 1 KB Mac CPU; cold-start ≤ 10 s. Document explicitly | 30 min | Pre-publish |
| O8 | **Security disclosure timeline** — extend `SECURITY.md` with explicit "90-day coordinated disclosure" policy + safe-harbor wording for researchers | 1 h | Pre-publish |
| O9 | **License audit / third-party attribution** — re-distributing LoRA weights derived from TAB ECHR (CC BY 4.0) + Nemotron (CC BY 4.0) requires attribution. Centralise in `LICENSES_THIRD_PARTY.md` (referenced from each model card) | 2-3 h | Pre-HF-push |

### Customer-facing (post-release)

| # | Item | Effort | Notes |
|---|---|---|---|
| C1 | **Getting started tutorial** beyond README — step-by-step "your first sanitize call" + restore round-trip + custom recognizer | 3-4 h | Post-Phase-B |
| C2 | **Integration recipes** — extend `examples/` with: Express middleware, LangChain wrapper, Anthropic SDK pre-pass, Vercel AI SDK pre-pass. Currently `examples/` has 4 files | 1-2 days | Post-publish |
| C3 | **Bug report + feature request** GitHub issue templates (`.github/ISSUE_TEMPLATE/`) | 1 h | Pre-publish |
| C4 | **FAQ** — common questions: is it offline? GPU required? cold-start latency? supported languages? | 2 h | Post-publish |

### Review-grade compliance (deeper)

| # | Item | Effort | Notes |
|---|---|---|---|
| R1 | **Threat model** doc — beyond `SECURITY.md`. Adversarial prompts, compromised LLM exfiltration, side channels, vault timing attacks | 4 h | Pre-regulated-buyer engagement |
| R2 | **Data residency claim** — explicit "no data leaves machine after model download" + audit-trail capability for regulated buyers | 2 h | Pre-DPIA-final |
| R3 | **Backwards compat policy** — when 8-class schema changes (e.g. Art. 9 categories added in v11), old vault sessions remain restorable. Document the schema-version field on `SanitizeResult` | 2 h | Pre-v11 |

### What is NOT on the work list right now

- **HuggingFace push** of model artifacts (`lBroth/nullpii-v10-router-{embedding,xlmr}` + 5 LoRA adapters). Cards exist; push deferred. Re-add when user chooses.
- **Held-out routing-eval corpus** (500 docs hand-annotated). Required to honestly close TUNE-ENTGATE-01 and gate v11 Path A/B/C decision; deferred.
- **Merged-LoRA ONNX export** (path-to-A #2). Closes CONFIG-SHIPPED-01 fully. ~1-2 days when scheduled.
- **Portkey + LiteLLM integration shims**. Distribution multiplier — work after npm runtime consumes v10 + after v0.2.0 published.
- **npm publish** / version bump / release tag. Pending Phase B + O3-O8.
- **Branch merge to `main`**. We work on `bench-full-2026-05-05` and decide later.

### Permanent exclusions

- Cloud-API rows (`aws-comprehend`, `gcp-dlp`, `azure-pii`) — paid + lock-in. Available in `bench_full.py` via opt-in `--tools` but excluded from canonical bench matrix.
- Per-domain adapter rows as user-facing tools — internal building blocks for the routers only. Only `nullpii-v10-router-embedding` and `nullpii-v10-router-xlmr` are surfaced.
- Older nullpii variants (`nullpii`, `nullpii-v8`, `nullpii-v9`, `nullpii-ensemble-*`, `nullpii-ablation-*`, `nullpii-runtime`, `nullpii-v10-router-{hybrid,hybrid-v2,embedding-expanded}`, `regex`-only, wrapped `gliner+regex` etc.) — purged from `bench_full.py` on 2026-05-04.
- **Feature flags / runtime toggle service** (LaunchDarkly / GrowthBook / Unleash etc.). nullpii is a local library — no central toggle service makes sense, no outbound network call (would violate privacy guarantee), determinism required for compliance audit (GDPR Art. 35). Behaviour is configured per-instance via the typed `NullPiiConfig` constructor argument; rollback = `npm install nullpii@<prev>`. Re-evaluate only if a SaaS / multi-tenant product layer is built on top.
- **Multi-tenant / per-tenant config** runtime layer. Same reasoning: nullpii is a library, not a service. If a buyer needs per-tenant policy (different recognizers per customer, different thresholds), they construct multiple `NullPii` instances with different `NullPiiConfig` and route at the application layer. We do not bake tenant awareness into the library.

## v11 backbone-upgrade roadmap (post-v10 release, conditional)

After the v10 unified release bench completes, decide whether to retrain on a larger backbone. Decision tree:

```
v10 bench (mDeBERTa-v3-base ~278M + 5 LoRA, total ~430 MB) lands.
│
├─ vs gliner2-large-v1 (deberta-v3-large 340M, fastino-ai)
├─ vs gliner-x-large (MT5-large 580M, knowledgator) ← multilingual incl. CJK/Arabic/Hindi
├─ vs gliner-pii-large-v1 (gliner-large, knowledgator, EN)
├─ vs nemotron-pii-raw (gliner-large-v2.1 600M, NVIDIA)
│
├─ if v10 base wins or ties (≤0.02 F1 below the strongest large) → ship base. Done.
│
└─ if a large-class competitor wins by ≥0.03 F1 → train v11 on a larger backbone.
   │
   ├─ Path A — `nullpii-large` (deberta-v3-large or gliner_large-v2.1 base):
   │  • 5 LoRA, target 0.3% trainable, ~7 MB per adapter (2× v10).
   │  • Train cost: ~12-15 GPU-h on 5090 (vs v10 ~7h).
   │  • npm shipping: ONNX FP32 ~700 MB (2.5× v10), INT4 quant ~480 MB.
   │  • F1 lift target: +0.03-0.05 vs v10 base on multilingual + adversarial.
   │
   └─ Path B — `nullpii-xl` (MT5-large 580M, knowledgator's gliner-x backbone):
      • Adds CJK / Arabic / Hindi coverage — closes the documented v10 dead zone.
      • Train cost: ~20-25 GPU-h on 5090 (MT5 attention is heavier).
      • npm shipping: ~1.2 GB ONNX FP32. INT4 path uncertain (mdeberta INT4
        works; MT5 INT4 needs validation).
      • F1 lift target: +0.05-0.10 on non-Latin scripts; ~+0.02 on Latin
        languages (already at saturation with v10 base).
```

### Path C — unified single model (collapses router + 5 LoRA → 1 fine-tune)

Alternative to Path A / Path B. Triggered by the SAME held-out routing-eval gate: if the routing layer doesn't beat a chunked single-model baseline by ≥0.03 F1 on the held-out routing corpus, the per-domain LoRA architecture isn't load-bearing — collapse it.

**Architecture**:

```
input
  ↓
preprocessor (NFKC + unidecode + zero-width strip + HTML/URL decode + spaced-PII despace)
  ↓
unified_gliner (1 fine-tune on union of 5 domain corpora, ~280 MB base)
  ↓
regex_post_pass + url_filter + never_pii_filter (compliance hard rules)
  ↓
vault.sanitize → placeholder text
```

4 stages instead of 8. Drops: router (single model handles all domains), `boundary_refined` (model learns boundaries directly), 5 LoRA adapters.

**Training recipe**:

- Single GLiNER fine-tune on union of 5 domain training corpora (~103k records: 37k devops + 18k legal + 16k medical + 17k narrative + 15k enterprise).
- **Adversarial training-time augmentation**: inject homoglyph / charswap / unicode-zero-width perturbations on a 30% sample of training records → model learns invariance, replaces part of `_normalize_for_detection` runtime cost.
- LoRA r=16 alpha=32 on `urchade/gliner_multi_pii-v1` (same backbone as v10 base) OR full fine-tune (~6 MB vs ~280 MB depending on storage budget).
- Class-balanced sampling, BF16 cosine LR, 3-5 epochs early-stopped.
- Train cost: ~10-15 GPU-h on 5090 (single longer run vs 5 short LoRA runs).

**npm shipping**:

- 1 ONNX export (~280 MB FP32, ~150 MB INT4) — drop-in replacement for the current `openai/privacy-filter` runtime path.
- No router model to ship → drops the 135 MB distiluse / 1.1 GB xlm-roberta classifier weight from the bundle.
- TS library wrapping: preprocessor (already in npm scope, just needs spec), 1 ONNX inference call, regex pack (already in npm scope), vault. Audit F25 (TS / Python divergence) closes naturally because the surface is smaller.

**Trade-offs vs current router pipeline**:

| Property | v10 router (current) | Path C unified |
|---|---|---|
| Storage (npm bundle) | ~430 MB (base + 5 LoRA + embedder) | **~280 MB** (single model) |
| Inference passes | 2 (embedder + adapter) | **1** (single forward) |
| Per-domain F1 ceiling | adapter-specialised (potentially higher) | **uniform** (no specialisation) |
| Out-of-domain failure mode | graceful (fallback to narrative) | **uniform fail** (no fallback) |
| Routing test-set tuning risk | present (enterprise gate 0.10 tuned on nullpii-bench) | **eliminated** (no router) |
| Training pipeline | 5 sequential LoRA runs | **1 longer run** |
| Adversarial robustness | preprocessor + LoRA (defense in depth) | **augmentation-trained** (single layer) |
| Estimated F1 vs v10 router | baseline | **−0.02 to −0.05** (lose specialisation, gain simplicity) |

**Decision gate**:

Same held-out routing-eval corpus used for v10 routing validation. If routing layer F1 lift over a single-model baseline is:

- ≥ 0.03 → **router architecture is load-bearing**. Stay on v10 router. Proceed to Path A / Path B if a large-class competitor justifies a backbone upgrade.
- < 0.03 → **router architecture is NOT load-bearing**. Switch to Path C unified single model. Per-domain story drops; ship simpler pipeline. (Honest move per strategic assessment 2026-05-04: drop the per-domain narrative, lead with the vault + unified detector + bench harness.)

**When NOT to pick Path C**:

- If multilingual coverage (CJK / Arabic / Hindi) is the v10 gap that needs closing → Path B (`nullpii-xl` MT5-large) is strictly better. Path C uses the same base mdeberta backbone, same multilingual ceiling.
- If a regulated-vertical buyer specifically asks for separable medical / legal / devops profiles for compliance audit traceability → Path C breaks that story.

**Why Path C is on the menu**:

The strategic assessment (2026-05-04, internal) identified the reversible vault — not the per-domain LoRA routing — as nullpii's load-bearing differentiator. Path C is the "honest fallback" if the routing thesis doesn't validate empirically. It still delivers the vault + multilingual detection + bench-harness contributions without the unfalsifiable test-set-tuned routing claim.

### Pipeline robustness (conditional on v11 train)

If v11 ships, also harden:

- **Test-set tuning audit**: re-tune the enterprise-route gate (margin 0.10) on a held-out routing-eval corpus, NOT on `nullpii-bench`. See internal heldout-routing-eval plan.
- **Per-class confusion publication**: ship `confusion.json` alongside `matrix.json` in the release matrix; document how to read it per profile.
- **IoU=0.9 strict F1 column**: add a second metric column for privacy-critical workloads where loose-boundary spans are unacceptable.
- **Latency p50 / p95 on canonical hardware**: bench on 5090 + Mac M-series + Linux x86 CPU, publish p50/p95 alongside F1.
- **DPIA template regeneration**: replace stale v6/v8 placeholder numbers with v11 unified-bench output; add per-class FN/FP rates for high-risk categories (Art. 9 invisibility quantified).
- **Article 9 categorical filter**: pair the v11 router with a sensitive-category content classifier (health / political / religious / etc.) — publishes an explicit "Art. 9 disclaimer dropped if classifier agrees" pipeline. Until v11, document this as user responsibility.

### Bench candidates added 2026-05-04 for v10/v11 comparison

Already wired into `bench_full.py`:

- `fastino/gliner2-{base,large,multi}-v1` — schema-agnostic GLiNER2 (Apache 2.0, span output via `include_spans=True`).
- `knowledgator/gliner-x-{large,base}` — MT5-encoder GLiNER (Apache 2.0, multilingual incl. CJK / Arabic / Hindi).
- `knowledgator/gliner-pii-{large,base}-v1.0` — PII-specialised GLiNER fine-tunes (Apache 2.0, EN-only).
- `knowledgator/modern-gliner-bi-large-v1.0` — ModernBERT bi-encoder (Apache 2.0, 8k context, ~4× faster on long inputs per upstream claim).
- `E3-JSI/gliner-multi-pii-domains-v1` — fine-tune of v10 base, adds Slovenian / Greek / Dutch.

Not yet wired (queued for v11):

- `ai4privacy/llama-ai4privacy-multilingual-categorical-anonymiser-openpii` — ModernBERT-base (~100M), Hindi + Telugu native. Different code path (transformers `AutoModelForTokenClassification`, not GLiNER) — needs a new adapter wrapper.
- `betterdataai/PII_DETECTION_MODEL` — Qwen2-0.5B decoder. Generative output, no native span offsets — would require fuzzy span re-alignment, not Apple-to-apple.

Negative signals (skip):

- `Roblox/roblox-pii-classifier` — binary classifier (`asking_for_pii` / `giving_pii`), no spans, F1 not comparable.
- `Mayank6255/GLiNER-MoE-MultiLingual` — F1 inconsistent (75 WikiNeural, 3.7 HarveyNER), low adoption.
- `numind/NuNER_Zero-span` — pre-2025 cutoff, 12-token entity cap breaks long PII.
- GLiNER v3 / `urchade/gliner_multi_pii-v2` — do NOT exist as of 2026-05-04. The v10 backbone is still the latest from urchade.

## Decision tree

```
Phase 1 LoRA POC
├─ ✅ works: proceed corpus prep → 4 adapter train → bench (Phases 2-4, ~10 days)
└─ ❌ GLiNER backbone not LoRA-compatible: pivot to 4 full per-domain fine-tunes
   (same code as v9, larger storage, regresses dev-paste per domain — known cost)
```

## Phase 1: LoRA POC (3-5h work)

**Goal**: confirm `peft` + GLiNER backbone can inject LoRA adapters, train, save, reload, inference.

Steps:
1. Read `gliner` library source — identify backbone (`deberta-v3-base` derivative?), find injection points (attention `q_proj`, `k_proj`, `v_proj`).
2. `pip install peft accelerate>=1.1.0`.
3. Apply `LoraConfig(r=16, alpha=32, target_modules=...)` to GLiNER's backbone module.
4. Verify trainable params ratio (~0.5-2% target). Print param count before/after.
5. Smoke train 100 steps on 1k samples from `packages/eval/results/train/gliner-v9-balanced/train_filtered.jsonl`. Verify loss decreases.
6. Save adapter (`adapter_model.safetensors` ~50MB).
7. Reload adapter on top of fresh base model. Run forward pass on 5 nullpii-bench samples. Compare predictions against base-only.
8. **Gate decision**: if reload + inference works → Phase 2. If not → fallback path.

## Phase 2: Per-domain corpus mix (~2-3 days, no DUA wait)

Per-domain training corpora (each ~30k samples):

### `devops` adapter
- dev-paste-synth (`packages/eval/datasets/dev-paste-synth-train.jsonl`) — 20k existing
- ai4privacy 0–5k — narrative-leaning subset
- isotonic 0–5k (en/de/fr/it sample) — multilingual code/dev paste
- Mix target: narrative-heavy, secret-pattern coverage

### `legal` adapter
- TAB ECHR train (`/tmp/tab-data/echr_train.json`) — 5k chunks (chunked ≤200 tok)
- ai4privacy 0–5k structured
- Common Crawl legal samples (HuggingFace `c4` filtered for legal vocabulary, e.g. `the Court`, `Article`, `Defendant`) — 20k
- Mix target: PERSON / DATETIME / LOC heavy

### `medical-experimental` adapter
- MEDDOCAN train (`GuiGel/meddocan` HF) — 10k (need integer label → nullpii schema mapping investigation)
- ai4privacy medical-flavored subset (filter for medical terms) — 5k
- Common Crawl medical samples (filter for clinical vocabulary) — 15k
- Mix target: MRN / DATETIME / PERSON / clinical narrative
- ⚠ Stays `-experimental` until i2b2 DUA + bench validates

### `general` adapter
- Balanced subset of all above — 30k
- Used as fallback when domain unknown

### Common Crawl prose negative class
- Sample 25k snippets from `c4` or similar
- Filter for: no PII patterns (regex-grepped), free-form prose
- Used as negative training signal: model should NOT fire spans on plain prose
- Shared across all 4 adapters

## Phase 3: Train 4 adapters (~4-5 days, GPU-bound)

Per adapter:
- LoRA r=16, alpha=32
- 2 epochs
- Mac MPS feasible (~1.5h/epoch on 30k batch 2 grad-accum 8) OR RunPod L40 (~10-15min/epoch, $1-2/hr)
- Save adapter at `packages/eval/results/train/v10/adapters/{devops,legal,medical-experimental,general}/`
- Total storage: ~200-400MB

Class-balanced sampling per batch: ensure each PII class appears in batch.

Curriculum: epoch 1 mixed, epoch 2 with negative-class injection (Common Crawl prose).

## Phase 4: Integrated bench + ship (~half-day)

1. Update `bench_full.py` `nullpii-{profile}` tool defs: load v6 base + adapter on demand.
2. Bench all 4 profiles + v6 baseline + (legacy) v9 across 10 datasets.
3. Compare per-domain F1 vs v9 (single multi-domain model).
4. Goal: each adapter ≥ v6 on its own domain + ≥ v9 on cross-domain.
5. Update README profile table with v10 numbers.
6. Update HF model card if shipping models there.

## Phase 5+: deferred (waiting on external)

- 🔴 **i2b2 2014 deid DUA approval** — application required at portal.dbmi.hms.harvard.edu. Gates upgrading `medical-experimental` to `medical`.
- 🔴 **Held-out routing-eval corpus** (500 docs hand-annotated). See `packages/eval/private/compliance/HELDOUT_ROUTING_EVAL_PLAN.md`. Gates v10 release-candidate go/no-go.
- 🔴 **HF model card update** — publish `lBroth/nullpii-v10-{devops,legal,medical-experimental,general}-lora` adapters to HuggingFace.
- 🔴 **HUDOC, EDGAR-redacted bench** — additional legal corpora to disprove TAB-only memorisation.
- 🔴 **MEDDOCAN bench integration** — needed for `medical-experimental` validation.
- 🔴 **SOC 2 Type II audit** — only relevant for cloud offering, 9–14 months calendar.

## Phase 6: optimisation backlog (post-router)

- 🔴 **Shared-base PEFT `add_adapter`**. Currently each `gliner_lora_predictor` instantiation calls `GLiNER.from_pretrained` and re-loads the 278M backbone. The router pre-loads 4 adapter predictors → 4× backbone in RAM (~1.1GB PT). Refactor to a single-base GLiNER with `peft_model.add_adapter(name)` + `set_adapter(name)` per request. Memory savings: ~840MB. Latency per request: unchanged (set_adapter is O(active LoRA layer count)). Skipped during initial v10 build to reduce scope; the 4× duplication is acceptable for bench but not for production deployment.
- 🔴 **Hybrid ML router** ✅ (in flight; see TRAINING.md 17:30). Replace pure regex `detect_domain` with regex-first + sklearn TF-IDF + LogReg fallback for ambiguous text. See `train_router.py`. Goal: lift `unknown` fraction (currently ~52% on `nullpii-bench`, ~23% on ai4) closer to its true domain → higher router F1.
- 🔴 **Adapter merge + ONNX export** for npm shipment. Once the router design stabilises, merge each LoRA into its base + export to ONNX FP32/INT4 for the npm runtime. The npm lib runs onnxruntime-node, not PT — current adapter format ships only via the Python eval pipeline.

### Adversarial robustness (post-preprocessor backlog)

The v10 router-embedding + xlmr pipelines now ship with `_normalize_for_detection` (NFKC + unidecode + zero-width strip + HTML numeric entity decode + URL `%XX` decode + spaced-PII despace). Empirical lift on adv subsets:

- adv-unicode: 0.466 → **0.936** (+0.470 distiluse) / 0.335 → **0.716** (+0.381 xlmr)
- adv-whitespace: 0.106 → **0.393** (+0.287 distiluse) / 0.129 → **0.519** (+0.390 xlmr)
- adv-encoding: 0.122 → 0.148 (+0.026 marginal — URL `%40` paths only)
- adv-typo / adv-code: unchanged (no preprocessor needed)
- adv-decoys: 0.000 (gold-empty subset; metric framing issue, not adapter)

**Remaining adversarial gaps**:

- 🔴 **HTML entity email recall miss**: model returns `.123@gmail.com` instead of `user.123@gmail.com` when the original is wrapped in an HTML entity sequence. Span remap is correct; model recall on the leading "user" portion is low. Real fix: adversarial training corpus that includes encoded PII forms with realistic prefixes/suffixes ("Detected pattern:", "verify match", etc.). Estimated lift: +0.3-0.5 on adv-encoding email subset.
- 🔴 **Whitespace context contamination**: bare `+493012345678` is recognised as a phone after despace; the SAME phone with a "Detected pattern: …" prefix and "-- verify match." suffix is NOT recognised. Cause: surrounding boilerplate dilutes confidence below the 0.5 threshold. Real fix: adversarial training with the boilerplate-wrapped form. Estimated lift: +0.2-0.3 on adv-whitespace.

**Plan**:

1. Build adversarial training augmentation (~5k samples per LoRA): apply unicode/whitespace/encoding perturbation to a slice of each adapter's existing positive PII records.
2. Retrain devops + general LoRA adapters on (original + augmented) — **devops first, since it's the routing target for most adversarial samples.**
3. Re-bench adv subsets. Goal: adv-whitespace ≥0.6 distiluse / ≥0.7 xlmr; adv-encoding ≥0.4 both.
4. Defer adv-decoys: subset has empty gold spans (decoys ARE not PII), so the metric is degenerate.

Time: ~3h training + 30 min bench. Same pipeline as `train_lora.py`; only the corpus changes.

### v11 corpus design — lessons from Nvidia Nemotron-PII

Nemotron benched lower than v10 distiluse (-0.165 avg) but their training methodology contains transferable techniques:

- 🟡 **Persona-grounded cross-document synthesis** — same individual appears across 4-5 documents in different industry contexts (loan app + medical record + employment + real estate). Build via NeMo Data Designer (open-sourced) or replicate with a small synthesis pipeline. Goal: train model on entity coherence across documents, not isolated patterns.
- 🟡 **Industry coverage expansion** — Nemotron-PII has 30 industries; nullpii v10 has ~5. Add samples from insurance, real estate, manufacturing, transportation, hospitality. ~5-10k extra synthetic per industry.
- 🟡 **Hybrid format augmentation** — train on (a) raw text, (b) tagged-markdown (`[John]first_name`), (c) structured-form variants. Triple representation as regulariser.
- 🟡 **Granular-label training, 8-class production** — train backbone with 55-class labels for richer internal representation, then map to 8-class at inference. Latency tradeoff (55 prompts vs 8) needs measurement.
- 🔴 **Bench `argilla-pii` + `nemotron-pii-test` regularly** as external sanity checks. They're held-out (we never trained on them), so they validate generalisation.
- 🔴 **Multilingual Nemotron risk** — if Nvidia releases a multilingual Nemotron-PII (currently US-only), v10's primary moat (multilingual + adversarial) narrows. Watch the release pipeline; have a multilingual response strategy ready (port persona-grounded synthesis to en/de/fr/es/it).

### Audit residue — items deferred from 2026-05-04 review

Full audit at `docs/v10/AUDIT_2026-05-04.md`. 17 of 25 findings landed on branch `audit-fixes-2026-05-04`. Outstanding work:

- 🔴 **F07 — Bitcoin Legacy base58check verification.** Regex still matches uppercase prose tokens (`Order 1A2B3C4D5E6F7G8H9J1K2L3M4N`). Adding a `_btc_base58check_valid` post-filter requires hooking label-specific validators into `regex_recognizer_predictor` (currently uniform). Estimate 2-3 h including tests on the genesis address + a 100-FP corpus.
- 🔴 **F11 — `multi_ensemble_predictor` strategy default.** Production ensemble at `adapters.py:862` uses `strategy="primary"` which silently drops higher-prior regex spans (CF / IBAN) when the model emits an overlapping `private_person`. Switching to `score_ranked` is a global behaviour change — needs a re-bench across the 21-dataset suite to confirm no regressions before flipping the default.
- 🔴 **F21 — TS `escapePlaceholders` round-trip mutation.** `regex: [\[abc]` typed by a user becomes `regex: [[abc]` after sanitize→restore (loses the backslash). Fix: use a non-bracket sentinel that can't appear in user input (e.g. private-use Unicode codepoint pair).
- 🔴 **F23 / F24 — preprocessor performance.**
  - `_SPACED_PII_RE` in `_normalize_for_detection` is super-linear on whitespace-rich input (100 KB whitespace → ~5 s in CPython). Fix: pre-screen with cheap `text[i].isspace()` check before calling `regex.match(text, i)`, OR use `finditer` once outside the loop.
  - The per-char Python normalisation loop is hot-path quadratic on 50 KB+ ASCII text. Fix: ASCII fast-path that returns identity map when `text.isascii()` and there are no `&#` or `%` sequences.
- 🔴 **F25 — TS library lacks Python's adversarial defences.** No `_normalize_for_detection`, no `_is_never_pii`, thin regex pack vs the 75-pattern Python set. Production npm users get materially weaker detection than benches advertise. Port targets: `_normalize_for_detection` (with offset map), `_is_never_pii`, `DEFAULT_REGEX_PATTERNS`, `url_filter_predictor`. Or document the gap loudly in README under "TS library scope".
- 🟡 **F06 IPv6 validation.** Regex only update partially landed (IPv4 octet-bounded; MAC lookbehind/-ahead). IPv6 still accepts `dead:beef::1::5` (illegal double `::`). Fix: post-match `ipaddress.ip_address(span)` validation, drop on `ValueError`. ~30 min including tests for compressed / mapped / link-local forms.

### Bench speed-ups (single-host, no GPU)

Current bench on Mac is CPU-only and single-process: ~12 samp/s × 5k samples × 6 datasets × N tools ≈ multi-hour. Headroom available:

- 🔴 **MPS backend for inference**. `gliner_lora_predictor` already works on MPS for training. Adding `mps` to `bench_full.py`'s `--backend` choices + plumbing through to `.to("mps")` should give 3-5× speedup at zero memory cost. Quick fix, ~30 min.
- 🔴 **Parallel processes per dataset**. Mac CPU is 76% idle during bench; the bottleneck is single-threaded inference, not memory bandwidth (per-process ~6GB, 47GB total → 2-3 parallel fit). Run multiple `bench_full.py` invocations on disjoint dataset subsets, then merge `matrix.csv`. ~2-3× wall-time speedup. ~20 min wrapper script.
- 🔴 **Batch inference (size > 1)** in `gliner_lora_predictor`. Currently 1 text per `predict_entities` call; collecting batches of 8-16 should cut overhead 2×. Requires API change in the predictor signature plus bench loop chunking. ~1h.
- 🔴 **Merged-LoRA ONNX with onnxruntime-node**. Largest single-host win. Merge each LoRA into a base copy, export to ONNX FP32, run via `onnxruntime` Python (no PT). Expected 5-10× speedup; also unlocks the npm shipment path. 1-2 days.

## Risks

- **GLiNER LoRA incompatibility** (Phase 1 gate). Mitigation: fallback to 4 full fine-tunes.
- **Per-domain corpus quality** (Phase 2). Common Crawl filtering may be noisy; budget 1 extra day for filter tuning.
- **i2b2 DUA delay**. Mitigation: ship `medical-experimental` with explicit non-validation disclosure (already done in `profiles.py`).
- **HF storage cost**. 4 adapters × 50MB each × multilingual variants = bounded; not a concern.

## Sign-off

This plan addresses:
- The compliance review's strategic recommendation: LoRA-per-domain over single-model rebalancing.
- The structural tension between 70k structured + 5k narrative training data observed in v8/v9.
- The explicit non-validation gate for `medical-experimental` until MEDDOCAN + i2b2 run.

Created: 2026-05-03. Reviewed by: __TBD__.
