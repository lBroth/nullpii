# v10 LoRA-per-domain training plan

## Status (2026-05-03)

- ✅ **Phase 1**: LoRA POC on GLiNER backbone — **VERIFIED PASS**. Pure-LoRA architecture (0.3% trainable, ~3.4MB adapter), MEDDOCAN-trained adapter learned new detection (NHC patient ID at 0.647 vs base "missed"), no regression on English dev-paste.
- 🟡 **Phase 2**: per-domain corpus mix — IN PROGRESS. CC neg 25k sampling running with model filter. MEDDOCAN loader validated (21/21 entity types explicit handling). Corpus overlap fix landed (disjoint partition). Bug fix in `filter_token_len` for cc-negative kept (verification pending end-to-end run).
- 🔴 Phase 3: train 4 adapters — queued (after Phase 2 corpus complete).
- 🔴 Phase 4: integrated bench + ship — queued.
- 🟡 Long-term: i2b2 DUA approval (gating final medical adapter) — application pending.

For the public training procedure summary (Art. 53 transparency), see `docs/v10/TRAINING.md`. The full step-by-step engineering journal is internal (`packages/eval/private/v10/V10_JOURNAL.md`).

## Strategic assessment — current state (2026-05-04)

Independent strategist review (general-purpose subagent) ranks nullpii at **C+** as of 2026-05-04. Above Presidio on UX + modern ML; below Skyflow on production-readiness; orthogonal to Lakera (different problem). Three reasons grade is below B-tier:

1. **Shipping path incoherent**. npm currently downloads `openai/privacy-filter` (`src/defaults.ts:52`), NOT the v10 LoRA stack. Audit F25: TS library lacks Python pipeline's adversarial defenses + never-PII filter + full regex pack. Production npm users get materially weaker detection than the bench claims advertise.
2. **Canonical bench was a placeholder** (closed 2026-05-05): unified release bench landed at `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`. nullpii router-embedding 0.7172 / router-xlmr 0.7076 across 27 datasets. README + 8 model cards refreshed with concrete numbers. Bare-mode competitor matrix still pending 5090 GPU pass.
3. **Active critical audit findings** — ALL CLOSED 2026-05-05: F10 (`_remap_span` strict min/max clamp), F13 (`_has_high_precision_signal` legal/medical hit count override), F22 (all secret patterns bounded `{N,255}` or `{N,2048}` + 1 MB input length cap on `regex_recognizer_predictor`), F25 (TS port complete: `src/normalize.ts` mirrors Python `_normalize_for_detection` end-to-end via `any-ascii`; `DEFAULT_RECOGNIZERS` expanded 10 → 74 patterns at parity with Python `DEFAULT_REGEX_PATTERNS`; `filterNeverPii` post-pass).

**Load-bearing differentiator**: the reversible in-memory vault primitive (sanitize → placeholder → LLM → restore). Skyflow has it but cloud-only; Presidio has weak de-anonymisation; HF GLiNER models have detection but no vault. nullpii uniquely contributes OSS + reversible vault + multilingual local detection in a single npm install.

LoRA-per-domain routing is research artifact pending held-out validation — the 0.10 enterprise gate is currently tuned on `nullpii-bench` itself (test-set leakage per audit F13). Honest framing: if a held-out routing eval shows the LoRAs don't beat a chunked `urchade/gliner_multi_pii-v1` baseline by ≥0.03 F1, ship the embedding-router + single best adapter and drop the per-domain story.

Full report (with priority list, A/B paths to grade A, publishability assessment per venue): `packages/eval/private/v10/STRATEGIC_ASSESSMENT_2026-05-04.md` (internal-only — contains critical audit references not safe for public publication until closed).

## Top compound-leverage moves (path to A)

Three deliverables that unlock multiple downstream wins. Execute in this order.

| # | Deliverable | Date | Unlocks |
|---|---|---|---|
| 1 | **Unified release bench**, `matrix.json` + `confusion.json` | ✅ done 2026-05-05 | nullpii-v10-router-embedding 0.7172 / xlmr 0.7076 across 27 datasets; bare-mode competitor matrix pending 5090 GPU pass |
| 2 | **Close all 25 audit findings** (Critical + High + Medium) | ✅ done 2026-05-05 | F01–F25 all closed in code on this branch (`bench-full-2026-05-05`). 171 tests pass |
| 3 | **Held-out routing-eval corpus** (500 docs hand-annotated, 5 domains × 100) | 🔴 OPEN | Honest router F1 (no test-set tuning) + DPIA buyer-facing numbers + Path A/B/C decision gate |
| 4 | **Merged-LoRA ONNX export** → makes npm runtime consume v10 LoRA stack | 🔴 OPEN | Closes the README-claim-vs-shipping-runtime gap. ~1-2 days |

Steps 1-2 are the prerequisites for step 3. Step 4 is the work that makes v10 "exist" on the npm side.

After top 4 land:

5. Multi-seed (3) bench runs with bootstrap 95% CIs on canonical matrix. Required for any paper. By 2026-06-30.
6. Latency p50/p95 on 5090 + Mac M-series + Linux x86 → CSV alongside matrix.json. Required for procurement.
7. Portkey + LiteLLM integration (PR to each repo: nullpii as a guardrail provider). Distribution multiplier.
8. HN "Show HN: nullpii — local, reversible PII vault for LLM apps" with a 90s demo video. Lead with the vault, not the LoRAs.
9. Workshop paper for PrivateNLP / EMNLP industry track: "Domain-routed LoRA adapters for multilingual PII detection: a held-out evaluation."
10. SOC 2 Type II readiness — only when revenue justifies the 9-14 month calendar.

Publishability today (per strategist agent):

| venue | ready? | strongest framing |
|---|---|---|
| HN / Lobsters / r/ML | ❌ NO (need bare-mode competitor head-to-head numbers + npm runtime running v10) | "OSS, local, reversible PII vault for npm — beats Presidio +X F1, beats Nemotron-PII +0.16 multilingually" |
| Technical blog | ⚠ partial | **Adversarial preprocessor lift** as standalone finding (adv-unicode 0.466→0.936; adv-whitespace 0.106→0.393). Travels furthest as isolated insight |
| Academic paper / arxiv | ❌ NO | Missing for NeurIPS / ACL: held-out routing eval, multi-seed runs, statistical significance, full ablations, ethics statement covering Art. 9 invisibility. Workshop track realistic in 2-3 months focused work |

## v10 work plan — current state on `bench-full-2026-05-05`

No release tag, no main merge, no npm publish on the table. Work continues on this branch and decisions land later. The list below tracks code work only.

### Sprint outcomes (2026-05-04 → 2026-05-05)

1. ✅ **Unified bench complete** (2026-05-05) — `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`. nullpii-v10-router-embedding **0.7172** / xlmr **0.7076** macro F1 across 27 datasets. distiluse wins `nullpii-bench` OOD (+0.118) and adversarial subset (+0.062). Datasets: nullpii-bench + adversarial-{typo,unicode,whitespace,encoding,code} + textattack-{homoglyph,charswap,chardelete,charinsert,charsub} + tab-echr + presidio-synthetic + ai4privacy-{300k,400k,300k-heldout-v10} + isotonic-{en,de,fr,it} + isotonic-{en,de,fr}-heldout-v10 + oasst-dev-planted + argilla-pii + nemotron-pii-test. Excluded: `wikiann-{es,zh,ja}` (PER/LOC NER), `adversarial-decoys` (no gold spans), `nullpii-adversarial` (composite). Bare-mode third-party competitor matrix (Presidio, GLiNER-base, piiranha, deberta, scrubadub, nemotron-pii-raw, openai naive/BIOES/Viterbi) pending 5090 GPU pass — out of local-Mac-CPU scope.
2. ✅ **Pipeline decision** — ship `nullpii-v10-router-embedding` (distiluse, ~430 MB). Storage tiebreaker per ≤0.02 delta band; xlmr alt path documented for users that want max F1 on structured PII (1.4 GB cost not justified for default).
3. ✅ **README rewrite** — v10 numbers in place; iter-v7 placeholders removed; adversarial preprocessor lift documented.
4. ✅ **HF model cards** — 8 cards in [`model-cards/`](model-cards/) covering 2 routers + 5 LoRA adapters + index, with concrete F1 numbers from the unified bench. Cards satisfy EU AI Act Art. 53 transparency + NIST AI RMF Govern 4.1 / Map 5.2 documentation requirements (training data composition, train-vs-eval overlap matrix, intended use, out-of-scope use, evaluation methodology, limitations, ethical considerations including Art. 9 invisibility disclosure). HuggingFace push itself is not on the work list right now.
5. ✅ **All 25 audit findings closed** — F01–F25 (Critical + High + Medium). Test suite 171 pass / 8 skipped. Highlights:
   - F07 BTC base58check validator (Python `_base58check_valid` + TS `base58CheckValid`)
   - F11 ensemble strategy investigated, recommendation rejected — `score_ranked` regressed adversarial-typo by 0.30 F1 vs `primary` (kept primary)
   - F21 TS placeholder escape PUA sentinel pair (was `[\\[`, corrupted `[\[abc]` round-trip)
   - F22 secret-pattern bounds + 1MB regex pack input cap
   - F23 / F24 Python normalize 1MB cap + ASCII fast-path (mirrors TS port)
   - F25 TS port complete (`src/normalize.ts`, 74-pattern recognizer pack at parity with Python, `filterNeverPii` post-pass)
   All audit fixes verified F1-stable on the canonical bench (nullpii-bench 0.7280, adversarial-typo 0.9400, etc.). See [`AUDIT_2026-05-04.md`](AUDIT_2026-05-04.md) for the per-finding closure log.

### Open work (focused: complete core + final bench data)

User direction (2026-05-05): focus on what's needed to have final benchmark data + a complete core. HF push, merged-LoRA ONNX export, held-out routing-eval corpus, and Portkey/LiteLLM shims are explicitly deferred — see "What is NOT on the work list right now" below.

| # | Item | Local? | Effort | Status |
|---|---|---|---|---|
| 1 | **TS validators** (Luhn, IBAN-97, CPF, CF) wired into recognizers | ✅ local | 3-4 h | ✅ done 2026-05-05 (commit `d2dc4e6`) |
| 2 | **Per-class confusion publisher** (`packages/eval/scripts/confusion_report.py`) | ✅ local | 2 h | ✅ done 2026-05-05 (commit `6e48f3e`) |
| 3 | ~~Multi-seed bench wrapper~~ | — | — | **DROPPED** — single-version shipping; CIs not load-bearing for product positioning. Re-evaluate if a workshop paper is in scope |
| 4 | **Latency p50/p95** Mac M-series via updated `bench_latency.py` (v10 router profiles) | ✅ local | 4 h | ✅ done 2026-05-05 (commit `8eaaa9f`) |
| 4b | **Latency Linux x86 + 5090 GPU** rows | ☁ cloud GPU | 30 min GPU | 🔴 cloud sprint |
| 5 | **DPIA template regen** (`docs/compliance/DPIA_TEMPLATE.md`) — gated on cloud sprint output (needs competitor F1 + GPU latency) | ✅ local once 4b+6 land | 2 h | 🔴 post-cloud |
| 6 | **Bare-mode competitor matrix** on 5090 GPU (Presidio + GLiNER-base + piiranha + deberta + scrubadub + nemotron-pii-raw + openai naive/BIOES/Viterbi) | ☁ cloud GPU | 6-8 h GPU + setup | 🔴 cloud sprint |

### Pre-release red-team audit findings (2026-05-05) — must address before publishing

Independent red-team auditor review (general-purpose subagent, 2026-05-05) surfaced 20 mechanisms by which the published numbers could be artificially inflated. Full report stored privately at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`. Top 5 are **not publishable** until fixed:

| ID | Finding | Severity | Fix path |
|---|---|---|---|
| **LEAK-TAB-LEGAL-01** | TAB ECHR test docs share 50-char shingles with **127/127** legal training chunks (60/127 verbatim 200-char windows). `tab-echr` row is in-distribution generalisation, not OOD. F1 0.886 likely 0.55-0.70 OOD | **Critical** | Strip `tab-echr` from headline 27-row macro → mark `tab-echr-INDIST`. OR retrain `legal` adapter on non-TAB corpus (HUDOC/EDGAR-redacted) |
| **LEAK-NEMO-ENTERPRISE-01** | `enterprise` adapter trained on `nvidia/Nemotron-PII` train; benched on `nvidia/Nemotron-PII` test. Already disclosed in model card but still in headline macro F1 | **Critical** | Strip `nemotron-pii-test` from headline macro → mark `*-INDIST`, keep as in-distribution diagnostic |
| **TUNE-ENTGATE-01** | `router.py:517-531` source comment admits 0.10 enterprise-gate margin chosen to maximise `nullpii-bench` F1. At margin=0.05, F1 drops 0.11. Entire +0.118 distiluse-vs-xlmr advantage on `nullpii-bench` is largely test-set-tuning artifact | **Critical** | Re-run with `gated_routes={"enterprise": x}` for `x ∈ {0.0, 0.05, 0.10, 0.15}`; publish range. Tune for real on a held-out routing-eval corpus when built |
| **CONFIG-SHIPPED-01** | `src/defaults.ts:59` `DEFAULT_MODEL_REPO = 'openai/privacy-filter'`. The bench measures the v10 LoRA stack with router + LoRA adapters + regex pack. Users running `npm i nullpii` get a different system | **Critical** | Add a "default-config" column to README headline (run `bench_full.py --tools openai-bioes`) so users see what they actually get; OR ship merged-LoRA ONNX + flip `DEFAULT_MODEL_REPO` |
| **LEAK-DEVPASTE-TEMPL-01** | `nullpii-bench` and `dev-paste-synth-train` share template family by construction (`*-templates.txt` source). Bench is in-template-family, not OOD | **Critical** | Reclassify `nullpii-bench` from "OOD gold standard" to "in-template-family but disjoint instances". Build a hand-curated OOD set from real LLM logs (with consent) for true OOD claims |

High-severity findings (10 more — see private red-team report):

- **LEAK-AI4-OFFSET-01** — `ai4privacy-300k` (offset 0) bench rows in train pool → drop, keep only heldout-v10 row.
- **LEAK-TAB-GENERAL-01** — TAB train chunks also feed `general/` adapter (fallback); same leakage applies to all routes.
- **LEAK-ISO-OFFSET0-01** — `isotonic-{en,de,fr,it}` offset-0 overlaps train pool (small Δ but disclose).
- **ASYM-NORM-01** — `_normalize_for_detection` wrapped on v10 routers but NOT on bare baselines. Adversarial subset lift (~+0.47 on adv-unicode) is preprocessor, not model. Add `gliner-onnx-pii-fp32+norm` parallel rows so the lift is attributable.
- **HARNESS-PARTIAL-IOU-01** — IoU ≥ 0.5 partial-match default; no strict-equality column. Macro 0.7172 → ~0.65 strict. Publish both columns.
- **LANG-MACRO-MISLABEL-01** — `nullpii-bench` mixes en/it/de/fr/es into a single F1; per-locale gap hidden. Emit per-locale rows.
- **LANG-CJK-OMITTED-01** — wikiann-{es,zh,ja} dropped without precision-only diagnostic surfaced in README.
- **RECALL-HEADLINE-01** — macro F1 hides `private_address` recall 0.30, `secret` recall 0.07 (xlmr/nemotron). Add "worst-class recall" alongside macro F1 in README.
- **TUNE-F11-NULLPII-BENCH** — F11 decision matrix in `AUDIT_2026-05-04.md:264-275` used `nullpii-bench` itself as one of 9 datasets; redo on a held-out set when the 500-doc routing-eval corpus exists.
- **REPRO-RUNTIME-01 / SEED-VARIANCE-01** — no env-lock, no seed in `matrix.json`, no hardware fingerprint. Ship `pip freeze` + Python version + run 3 seeds for variance bound.

Medium / Low (4):
- **HARNESS-EMPTYDOC-01** — empty-gold docs + `adversarial-decoys` exclusion compound to hide FP rate; re-include decoys as precision-only diagnostic.
- **LATENCY-COLDSTART-01** — `bench_latency.py:255-261` warm-only after one warmup pass; cold-start (~3-10 s) excluded. Add `cold_start_ms` field including adapter load.
- **LATENCY-WALLS-01** — `bench_full.py:604-635` writes bogus `wall_s` / `samples_per_s` on full-resume cells (timer overhead only). Set to None when `done_idx + 1 == len(samples)` at start.
- **LMSYS-ENRON-OMIT-01** — 4/31 datasets dropped silently (gated HF). The dropped 4 are the real-world long-text ones (Enron, lmsys, stackoverflow, thestack); replacement or HF-token CI required.

#### Honest-numbers patch order (after cloud sprint produces competitor + GPU latency)

1. Re-bench with `gated_routes={"enterprise": 0.0}` — publish margin sensitivity range.
2. Strip `tab-echr` and `nemotron-pii-test` from headline 27-row macro; recompute `*-INDIST` columns.
3. Add `--policy {partial,exact}` flag to `bench_full.py`; emit both columns in `matrix.csv`.
4. Add per-locale split for `nullpii-bench` (en/it/de/fr/es).
5. Add `cold_start_ms` to `bench_latency.py`.
6. Fix `wall_s` / `samples_per_s` on resume in `bench_full.py:604-635`.
7. Add `gliner-onnx-pii-fp32+norm` row so preprocessor lift is attributable.
8. Add `default-config` row (`openai-bioes`) for what `npm i nullpii` ships today.
9. README: add "worst-class recall" + "default-config F1" + "strict-match F1" columns alongside macro F1.
10. Ship `pip freeze` + Python version + hardware fingerprint in the bench output dir.
11. README: reclassify `nullpii-bench` as "in-template-family", not "OOD gold standard".

Order of remaining work: **cloud sprint (4b + 6)** → **honest-numbers patch (above 11 steps)** → **DPIA regen (#5)** → **README + COMPETITIVE_ANALYSIS final refresh**.

### What is NOT on the work list right now

- **HuggingFace push** of model artifacts (`lBroth/nullpii-v10-router-{embedding,xlmr}` + 5 LoRA adapters). Cards exist in [`model-cards/`](model-cards/); the push itself is deferred. Re-add when the user chooses.
- **Merged-LoRA ONNX export** for the npm shipping path. Closes the README-claim-vs-runtime gap but is not required for completing the bench data + core. ~1-2 days when it lands.
- **Held-out routing-eval corpus** (500 docs hand-annotated, 5 domains × 100). Required to honestly close the 0.10 enterprise-gate test-set-tuning issue and to gate the v11 Path A/B/C decision; not required for the v10 bench/core completion.
- **Portkey + LiteLLM integration shims**. Distribution multiplier — work for after the npm runtime consumes v10.
- **npm publish** / version bump / release tag.
- **Branch merge to `main`**. We work on `bench-full-2026-05-05` and decide later.

### Permanent exclusions

- Cloud-API rows (`aws-comprehend`, `gcp-dlp`, `azure-pii`) — paid + lock-in. Available in `bench_full.py` via opt-in `--tools` but excluded from the canonical bench matrix.
- Per-domain adapter rows as user-facing tools — internal building blocks for the routers only. Only `nullpii-v10-router-embedding` and `nullpii-v10-router-xlmr` are surfaced.
- Older nullpii variants (`nullpii`, `nullpii-v8`, `nullpii-v9`, `nullpii-ensemble-*`, `nullpii-ablation-*`, `nullpii-runtime`, `nullpii-v10-router-{hybrid,hybrid-v2,embedding-expanded}`, `regex`-only, wrapped `gliner+regex` etc.) — purged from `bench_full.py` on 2026-05-04.

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
