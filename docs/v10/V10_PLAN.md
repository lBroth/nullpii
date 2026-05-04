# v10 LoRA-per-domain training plan

## Status (2026-05-03)

- ✅ **Phase 1**: LoRA POC on GLiNER backbone — **VERIFIED PASS**. Pure-LoRA architecture (0.3% trainable, ~3.4MB adapter), MEDDOCAN-trained adapter learned new detection (NHC patient ID at 0.647 vs base "missed"), no regression on English dev-paste. See `V10_JOURNAL.md` 14:20.
- 🟡 **Phase 2**: per-domain corpus mix — IN PROGRESS. CC neg 25k sampling running with model filter. MEDDOCAN loader validated (21/21 entity types explicit handling). Corpus overlap fix landed (disjoint partition). Bug fix in `filter_token_len` for cc-negative kept (verification pending end-to-end run).
- 🔴 Phase 3: train 4 adapters — queued (after Phase 2 corpus complete).
- 🔴 Phase 4: integrated bench + ship — queued.
- 🟡 Long-term: i2b2 DUA approval (gating final medical adapter) — application pending.

For detailed step-by-step findings + fixes, see `docs/v10/V10_JOURNAL.md`.

## Release gating (2026-05-04, top priority)

Before any HF push / README rewrite / npm publish, ALL of these must complete in order:

1. 🔴 **Final unified release bench** (single matrix, single code rev, single dataset spec). Tools: `nullpii-v10-router-embedding`, `nullpii-v10-router-xlmr`, plus the bare baselines `presidio`, `gliner-onnx-pii-fp32`, `piiranha`, `deberta`, `scrubadub`, `nemotron-pii-raw`, `openai`, `openai-bioes`, `openai-official`. Datasets (PII-native only, 19 canonical): nullpii-bench + adversarial-{typo,unicode,whitespace,encoding,code} + textattack-{homoglyph,charswap,chardelete,charinsert,charsub} + tab-echr + presidio-synthetic + ai4privacy-{300k,400k,300k-heldout-v10} + isotonic-{en,de,fr,it} + isotonic-{en,de,fr}-heldout-v10 + oasst-dev-planted + argilla-pii + nemotron-pii-test. **Excluded**: `wikiann-{es,zh,ja}` (PER/LOC NER, not native PII — loose mapping breaks F1 comparability), `adversarial-decoys` (zero gold spans → F1 structurally meaningless), `nullpii-adversarial` (composite — already covered by per-subset rows). One `bench_full.py` invocation. Estimated 8-10h GPU on 5090. Output is the SOLE source of truth for release tables.
   - **🌙 Run-overnight reminder**: launch this bench locally on Mac CPU **right before going to sleep** (avoids competing with foreground work). 2-tool nullpii-only run on the 19 datasets at default caps takes ~5-6h on M-series CPU — comfortable overnight slot. Resume via `--out-dir` checkpoints if interrupted. When the user signals they're heading to bed, propose the launch command before they leave the terminal. Command:
     ```
     nohup packages/eval/.venv/bin/python -u packages/eval/scripts/bench_full.py \
       --tools nullpii-v10-router-embedding,nullpii-v10-router-xlmr \
       --datasets all \
       --backend cpu \
       --out-dir packages/eval/results/bench-v10-release-local \
       > /tmp/bench-v10-release-local.log 2>&1 &
     ```
   - **Rule**: no per-tool patching of competitor code. `bench_full.py` already enforces bare-mode for non-nullpii rows after the 2026-05-04 purge — every tool runs as its upstream project intends, with no `boundary_refined`, `never_pii_filter`, `url_filter`, `regex_pack`, or chunking glue from nullpii.
   - **Audit gate**: confirm F09 (anchored phone patterns) + F20 revert (ASCII-only email) are present in `adapters.py` BEFORE launching. Current nullpii-bench cell is the canary — must recover ≥0.72 (vs the 0.726 pre-audit baseline) before the run is considered valid.
2. 🔴 **Decide release pipeline** from the unified matrix. Criteria: F1 mean across 21 datasets, latency, storage. distiluse-router (430 MB) vs xlmr-router (1.4 GB). If F1 delta ≤ 0.02 → ship distiluse (storage wins). If xlmr ≥ 0.05 better on real-PII subset → ship xlmr.
3. 🔴 **README rewrite** — replace iter-v7 numbers (`0.8638`, `iter-v7-final-clean/matrix.json`) with v10 unified-bench numbers. Keep "honest limitations" section + cheat-strip note + opf Viterbi PSA. Add adversarial preprocessor row.
4. 🟡 **HF model cards** — drafts in [`model-cards/`](model-cards/) covering 7 artifacts (2 routers + 5 LoRA adapters). Pre-bench numbers are placeholders (`TBD-BENCH`); regenerate post-bench. Push targets: `lBroth/nullpii-v10-router-{embedding,xlmr}` and `lBroth/nullpii-v10-{devops,legal,medical-experimental,narrative,enterprise}-lora`. Cards satisfy EU AI Act Art. 53 transparency obligations + NIST AI RMF Govern 4.1 / Map 5.2 documentation requirements (training data composition, train-vs-eval overlap matrix, intended use, out-of-scope use, evaluation methodology, limitations, ethical considerations including Art. 9 invisibility disclosure).
5. 🔴 **npm shipping path** — merged-LoRA ONNX export. Each adapter: merge into base copy → ONNX FP32 → bundle for `onnxruntime-node`. Without this, npm cannot consume the v10 routers. Estimated 1-2 days. See Phase 6 backlog.

### What is NOT in scope for v10 release

- Cloud-API rows (`aws-comprehend`, `gcp-dlp`, `azure-pii`) — paid + lock-in. Available in `bench_full.py` via opt-in `--tools` but excluded from the canonical release matrix.
- Per-domain adapter rows — internal building blocks for the routers, not a user-facing tool. Only `nullpii-v10-router-embedding` and `nullpii-v10-router-xlmr` ship.
- Older nullpii variants (`nullpii`, `nullpii-v8`, `nullpii-v9`, `nullpii-ensemble-*`, `nullpii-ablation-*`, `nullpii-runtime`, `nullpii-v10-router-{hybrid,hybrid-v2,embedding-expanded}`, `regex`-only, wrapped `gliner+regex` etc.) — purged from `bench_full.py` on 2026-05-04. Not part of the release surface.

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
- 🔴 **Held-out routing-eval corpus** (500 docs hand-annotated). See `docs/compliance/HELDOUT_ROUTING_EVAL_PLAN.md`. Gates v10 release-candidate go/no-go.
- 🔴 **HF model card update** — publish `lBroth/nullpii-v10-{devops,legal,medical-experimental,general}-lora` adapters to HuggingFace.
- 🔴 **HUDOC, EDGAR-redacted bench** — additional legal corpora to disprove TAB-only memorisation.
- 🔴 **MEDDOCAN bench integration** — needed for `medical-experimental` validation.
- 🔴 **SOC 2 Type II audit** — only relevant for cloud offering, 9–14 months calendar.

## Phase 6: optimisation backlog (post-router)

- 🔴 **Shared-base PEFT `add_adapter`**. Currently each `gliner_lora_predictor` instantiation calls `GLiNER.from_pretrained` and re-loads the 278M backbone. The router pre-loads 4 adapter predictors → 4× backbone in RAM (~1.1GB PT). Refactor to a single-base GLiNER with `peft_model.add_adapter(name)` + `set_adapter(name)` per request. Memory savings: ~840MB. Latency per request: unchanged (set_adapter is O(active LoRA layer count)). Skipped during initial v10 build to reduce scope; the 4× duplication is acceptable for bench but not for production deployment.
- 🔴 **Hybrid ML router** ✅ (in flight; see V10_JOURNAL.md 17:30). Replace pure regex `detect_domain` with regex-first + sklearn TF-IDF + LogReg fallback for ambiguous text. See `train_router.py`. Goal: lift `unknown` fraction (currently ~52% on `nullpii-bench`, ~23% on ai4) closer to its true domain → higher router F1.
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
