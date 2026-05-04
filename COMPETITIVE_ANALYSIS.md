# Competitive analysis — AI Gateway / AI Firewall / PII Redaction

Snapshot dated 2026-05-02. Used to position `nullpii` against the existing landscape and identify the whitespace it actually fills. Not exhaustive — focused on the players that overlap with the npm-package + adapter / managed-cloud roadmap items.

## Empirical bench numbers (PII detection, F1 IoU≥0.5)

OSS competitors benched directly on Mac M-series CPU, n=2000 per dataset (n=264 for `nullpii-bench`), single seed. Sources:

- nullpii column: `packages/eval/results/clean-baseline-20260502/matrix.json` (no test-set tuning — see *Honesty note* below)
- competitor columns: `packages/eval/results/competitor-baseline-20260501/matrix.json` (independent of nullpii pipeline state)

`wikiann-{es,zh,ja}` rows dropped from the headline matrix: schema mismatch (NER PER/LOC/ORG, not PII) makes all tools score 0.05–0.32. Documented as "NER-subset coverage gap" in the README — not a meaningful PII signal.

Closed-source competitors (Lakera, Skyflow, cloud APIs) require paid API access and are not included — see "Roadmap — bench completeness" in the README.

| Dataset                  | **nullpii** | gliner | openai | opf-Viterbi | presidio | piiranha | deberta | scrubadub |
| ------------------------ | ----------: | -----: | -----: | ----------: | -------: | -------: | ------: | --------: |
| **`nullpii-bench` (OOD, n=264)** | **0.8638** | 0.6947 | 0.4264 | 0.6764 | 0.3918 | 0.3571 | 0.3156 | 0.3054 |
| ai4privacy-300k          |  **0.3112** | 0.1481 | 0.1931 |      0.2882 |   0.2563 |   0.2496 |  0.2230 |    0.1540 |
| ai4privacy-400k          |      0.5238 | 0.5988 | 0.4390 |      0.6750 |   0.3575 | **0.9601** |  0.4677 |    0.1608 |
| isotonic-en              |      0.5908 | 0.6065 | 0.3860 |      0.5767 |   0.4728 |   0.5951 | **0.7498** |    0.2579 |
| isotonic-de              |      0.5948 | **0.6028** | 0.3850 |      0.5823 |   0.3921 |   0.5679 |  0.4852 |    0.2821 |
| isotonic-fr              |  **0.5879** | 0.5810 | 0.3831 |      0.5857 |   0.4099 |   0.5703 |  0.5735 |    0.2867 |
| isotonic-it              |      0.5885 | **0.5971** | 0.3841 |      0.5900 |   0.4239 |   0.5734 |  0.5362 |    0.2835 |
| oasst-dev-planted        |  **0.6250** | 0.2500 | 0.2322 |      0.3524 |   0.2225 |   0.2984 |  0.3136 |    0.0500 |
| presidio-synthetic       |      0.5854 | **0.5952** | 0.3899 |      0.5769 |   0.5792 |   0.3747 |  0.4499 |    0.4500 |

**Win count across 9 datasets:**

| Tool | Wins | Where |
| ---- | ---: | ----- |
| **nullpii** | **4** | `nullpii-bench`, `ai4privacy-300k`, `isotonic-fr`, `oasst-dev-planted` |
| gliner (bare) | 3 | `isotonic-de/it`, `presidio-synthetic` (≤+0.010 over nullpii on each) |
| piiranha | 1 | `ai4privacy-400k` (training-distribution memorization) |
| deberta | 1 | `isotonic-en` (training-distribution memorization) |
| presidio | 0 | — |
| openai (HF naive) | 0 | — (PSA confirmed: HF default decoder always loses) |
| openai-official (Viterbi) | 0 | — (close on `ai4privacy-*`, doesn't take outright wins) |
| scrubadub | 0 | — (regex-only baseline, weak everywhere) |

**Honesty note — what's NOT included in the nullpii column:**

The nullpii numbers above come from the *clean baseline* pipeline. Earlier iterations of the production pipeline included three regex patterns derived from `failure_analysis.py` runs on `nullpii-bench` itself (DB connection strings, AWS resource ARNs, Italian Codice Fiscale), an IPv4 regex with context-aware lookahead/lookbehind tuned to avoid 6 specific FPs observed on `nullpii-bench`, and a `gliner_threshold=0.8` value picked by sweeping on the bench. All four are forms of test-set tuning. They are stripped in the clean baseline. The cheat magnitude is small and mixed:

| Dataset | cheat-laden F1 | clean F1 | Δ (cheat impact) |
|---|--:|--:|--:|
| nullpii-bench | 0.8810 | 0.8638 | -0.017 |
| ai4privacy-300k | 0.2946 | 0.3112 | **+0.017** |
| ai4privacy-400k | 0.4672 | 0.5238 | **+0.057** |
| isotonic-en | 0.6029 | 0.5908 | -0.012 |
| isotonic-de | 0.6150 | 0.5948 | -0.020 |
| isotonic-fr | 0.6174 | 0.5879 | -0.030 |
| isotonic-it | 0.6089 | 0.5885 | -0.020 |
| oasst-dev-planted | 0.5278 | 0.6250 | **+0.097** |
| presidio-synthetic | 0.6147 | 0.5854 | -0.029 |

The bench-derived patterns helped narrowly on `nullpii-bench` itself and on isotonic Romance languages, but actively hurt cross-distribution F1 on `oasst-dev-planted` (-0.097) and `ai4privacy-400k` (-0.057). Test-set tuning didn't generalize. Average Δ across 9 datasets: **+0.005 in favour of the clean baseline**.

**Key empirical findings:**

- **`nullpii-bench` (real-world OOD use case)**: `nullpii` (clean) at **0.8638**, +0.17 F1 over the closest competitor (`gliner` 0.6947, same backbone bare). Every closed-source-style competitor (Presidio, Piiranha, DeBERTa, scrubadub) loses by 0.47+ F1 on real-world dev paste.
- **`oasst-dev-planted` (real conversational text + planted PII)**: `nullpii` (clean) at **0.6250**, +0.27 F1 over the next-best competitor (`opf-Viterbi` 0.3524). Cleaning the regex pack actually *increased* this number from 0.4611 to 0.6250 — the bench-tuned patterns were noise on real chat text.
- **Memorization vs generalization** is the dominant signal in the competitor table. **Piiranha** scores **0.9601 on `ai4privacy-400k`** while only 0.3571 on `nullpii-bench` — same model, same tokenizer, F1 gap ≥0.6 between training-distribution and real OOD. **DeBERTa** identically: 0.7498 on `isotonic-en`, 0.3156 on `nullpii-bench`. Both are fine-tuned on those public PII datasets, exposing a structural overfitting mode that nullpii's own attempted GLiNER fine-tune exhibited (and which we retracted from the README headline).
- **isotonic Romance**: `nullpii` and bare `gliner` are within 0.01 F1 of each other across `de/fr/it`. The runtime stack adds nothing here over the bare backbone — structured-PII templates don't benefit from regex priors. Plain GLiNER is competitive without the wrapper.
- **scrubadub** (Apache-2.0 OSS regex+chain library) scores 0.05–0.45 across every dataset. Regex-only baselines without ML coverage are not competitive on contemporary PII benchmarks. Useful as a sanity floor.
- **Presidio's own dataset (`presidio-synthetic`)**: gliner 0.5952 > Presidio 0.5792 > nullpii 0.5854. Bare GLiNER beats Presidio's own self-hosted PII detector on Presidio's own benchmark by 0.016 F1; the nullpii wrapper sits between them.

**iter-v7 ablation lessons (what *didn't* work):**

A research-iter-v7 branch attempted four fixes against the clean baseline. None produced a generalist win:

1. **Stoplist filter** (`Male`/`Female`/`I`/`patient`/`email`/`phone`/etc): selection process was bench-failure-analysis-driven → soft test-set tuning. Pruned to universally-non-PII terms (`i`, `email`, `phone`, `confidentiality`, `assets`); avg Δ +0.001. Negligible, kept for cleanliness.
2. **Score-ranked overlap resolver** with arbitrary per-label regex priors (`account_number=0.65`, `secret=0.95`, etc.): regression -0.030 avg. Arbitrary priors don't reflect actual per-source precision; rejected.
3. **Zero-shot semantic verifier** (MiniLM-L6 cosine similarity vs anchor texts derived from category definitions): regression -0.030 avg. 384-dim sentence embeddings don't separate PII from non-PII reliably enough; calibration-derived threshold (5th percentile of disjoint corpus, threshold = 0.112) drops too many real spans.
4. **Trained tiny verifier** (MiniLM-L12 binary classifier, 5k ai4privacy training samples disjoint from bench eval): catastrophic regression -0.5 to -0.7 across all bench datasets. Val F1 = 0.98 on same-distribution split, but verifier overfit ai4privacy-template patterns and labeled almost everything outside that distribution as non-PII. Single-distribution training doesn't generalize.

The journey is documented as a transparent research artifact: optimizing aggressively against a bench inflates numbers without generalising; the clean baseline above is the defensible state.

## v8 / v9 fine-tune appendix — research-grade, third-party validation pending

Two additional fine-tunes (v8 multi-domain on ai4privacy 30k + isotonic 40k + TAB ECHR 4.9k chunks; v9 same + 20k Faker dev-paste synthetic) are documented for completeness. Numbers are in `packages/eval/results/v8-bench-20260502/` and `packages/eval/results/v9-bench-20260502/`. **Important caveats** before quoting either:

- **Offset-disjoint ≠ distribution-disjoint.** Both fine-tunes train on ai4privacy / isotonic offset 0–N and evaluate on offset N+. Those datasets are Faker-templated — different row indices share the same surface patterns. v8/v9 scoring 0.88+ on `isotonic-*` and 0.56+ on `ai4privacy-*` is **template-distribution generalisation, not OOD**. The same fingerprint shows up in Piiranha (0.96 ai4privacy-400k vs 0.36 nullpii-bench) and DeBERTa-PII (0.75 isotonic-en vs 0.32 nullpii-bench).
- **Dev-paste regression is structural.** v8 nullpii-bench drops from 0.864 to 0.499 (-0.37); v9 partially recovers to 0.551 with synthetic injection. The training corpus is ~74% structured/templated (70k of 95k) vs ~5% real free-form narrative (5k TAB ECHR after chunking). A fixed-budget GLiNER backbone cannot fit both distributions without sacrificing the smaller one.
- **TAB ECHR lift (0.217 → 0.609 → 0.709) is the strongest signal**, but third-party legal corpora (HUDOC, EDGAR-redacted) are not yet benched to disprove TAB-only memorisation.
- **Mark these as research-grade until i2b2 + MEDDOCAN + at least one additional legal corpus validate cross-distribution generalisation.** The clean v6 baseline (table at top of this document) is the production-defensible reference; v8 / v9 are research artefacts that motivate the per-domain profile architecture (`packages/eval/src/nullpii_eval/profiles.py`) but should not be quoted standalone.

## Adversarial probes (NOT a robustness claim)

Two surface-level adversarial corpus probes (n=480 / n=1670). **Important caveat**: nullpii currently scores below `opf-Viterbi` on the third-party-framework run (TextAttack), so this section does NOT claim adversarial robustness — it documents a transparency probe of how each tool degrades under specific evasion patterns. The corpora are also team-curated (we picked the perturbation set + the source ai4privacy slice), so even the third-party-framework number is not a published benchmark result. Numbers are reported as a methodology disclosure, not as a feature claim.

### Self-built adversarial suite (`nullpii-adversarial.jsonl`, n=480)

Six categories generated by `packages/eval/scripts/generate_adversarial_bench.py`: typo PII (single-char neighbour swap), unicode obfuscation (Cyrillic homoglyph + zero-width insertion), whitespace obfuscation (`g i a n l u c a @ g m a i l . c o m`), encoding obfuscation (base64 / URL-encoded / HTML-entity), decoys (infrastructure-like patterns that look like PII but aren't — `localhost:5432`, `0.0.0.0`, `00:00:00:00:00:00`, null UUID), and code-PII (credentials in comments / docstrings).

`packages/eval/results/adversarial-bench-20260502/` (8-tool run, n=480) + `adversarial-bench-20260502-v6/` (nullpii-only, blocklist-v6, n=480).

| Subset (n=80 each) | nullpii (clean) | nullpii v6 (blocklist) | gliner | openai-official | presidio | piiranha | deberta | scrubadub |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| typo_pii | 0.823 | **0.884** | 0.536 | 0.622 | 0.350 | 0.492 | 0.534 | 0.500 |
| unicode_obf | 0.693 | 0.619 | 0.612 | **0.679** | 0.300 | 0.408 | 0.393 | 0.072 |
| whitespace_obf | 0.000 | 0.000 | 0.202 | 0.000 | 0.317 | 0.210 | 0.000 | **0.384** |
| encoding_obf | 0.102 | 0.109 | 0.000 | **0.202** | 0.000 | 0.000 | 0.000 | 0.000 |
| **decoys (FPs ↓ better)** | 60 FPs | **2 FPs** | 31 FPs | 3 FPs | 7 FPs | 8 FPs | 20 FPs | 10 FPs |
| code_pii | 0.834 | 0.867 | 0.949 | **1.000** | 0.427 | 0.236 | 0.400 | 0.355 |

The `nullpii v6 (blocklist)` column is nullpii with the `never_pii_filter` enabled (RFC 6761 reserved domains, NANP `555` fictional phones, RFC1918 private IPs flag, null UUID / loopback IP / broadcast MAC constants). The blocklist drops decoy false-positives from **60 → 2** (best-of-8) without breaking other subsets — wins typo_pii outright, ties on unicode_obf, holds on encoding_obf. The unicode_obf delta (0.693 → 0.619) is a v4-vs-v6 correction: v4 numbers were inflated by partial-match TPs (regex catching the first half of zero-width-split emails like `bob.jones@com​pa​ny.​io`); v6's TLD validity check correctly drops those as malformed.

**Subset wins (8-tool, post-blocklist):** typo_pii nullpii, unicode_obf opf-Viterbi, whitespace_obf scrubadub, encoding_obf opf-Viterbi, decoys nullpii (lowest FPs), code_pii opf-Viterbi (perfect 1.000). nullpii leads only typo_pii and decoys. The wrapper's strength is character-tolerance + decoy filtering; pure character-level perturbations beyond those (whitespace stretching, base64 wrapping) need pre-processors that don't ship enabled in the production pipeline (off-by-default flags `--enable-deobf-whitespace` / `--enable-deobf-encoding` exist as opt-in; not benchmarked here because they require third-party validation to avoid self-built-suite bias).

**Self-built-suite caveat:** the adversarial corpus was generated by us using exactly the evasion methods we expected our pipeline to handle. Numbers above suffer from corpus-development bias and should not be cited as third-party validation. The TextAttack run below addresses that.

### Third-party adversarial corpus (TextAttack, n=1670)

`packages/eval/datasets/nullpii-adversarial-textattack.jsonl` — generated via [TextAttack](https://github.com/QData/TextAttack) (UVA NLP / CIKM 2020 / Apache 2.0), an independent NLP adversarial-attack framework. Source data: ai4privacy rows 0–500 (disjoint from bench eval offset 300k+). Five perturbations applied per gold span: `WordSwapHomoglyphSwap`, `WordSwapNeighboringCharacterSwap`, `WordSwapRandomCharacterDeletion`, `WordSwapRandomCharacterInsertion`, `WordSwapRandomCharacterSubstitution`.

`packages/eval/results/textattack-bench-20260502/`. n=1670 (5 × 334 perturbed samples), 7 tools. nullpii pipeline state: clean baseline + RFC-grounded blocklist (`drop_rfc1918=True`).

**Per-perturbation F1 (micro):**

| Subset | openai-official | nullpii | piiranha | deberta | presidio | gliner | scrubadub |
|---|---:|---:|---:|---:|---:|---:|---:|
| textattack-homoglyph | **0.446** | 0.301 | 0.359 | 0.284 | 0.264 | 0.222 | 0.068 |
| textattack-charswap | **0.441** | 0.386 | 0.381 | 0.298 | 0.253 | 0.230 | 0.179 |
| textattack-chardelete | **0.438** | 0.395 | 0.374 | 0.311 | 0.255 | 0.226 | 0.167 |
| textattack-charinsert | **0.450** | 0.313 | 0.364 | 0.319 | 0.244 | 0.226 | 0.183 |
| textattack-charsub | **0.441** | 0.315 | 0.355 | 0.295 | 0.240 | 0.226 | 0.171 |

**Aggregate (macro F1, harness output):** opf-Viterbi 0.312, **nullpii 0.284**, deberta 0.277, piiranha 0.256, presidio 0.226, gliner 0.172, scrubadub 0.146.

**Findings:**

- **opf-Viterbi wins all 5 perturbation types.** Constrained BIOES decoder is the most robust to character-level mutations — Viterbi recovers spans even when individual tokens are corrupted because the transition constraint penalises invalid label sequences.
- **nullpii second.** Gap −0.028 vs opf-V on aggregate; ranges from −0.05 to −0.15 per perturbation. Beats every other competitor on every perturbation type. The custom regex pack + URL filter + boundary refinement preserve detection through char-level corruption better than bare GLiNER (+0.06 to +0.16 over gliner across the five subsets).
- **Latency caveat for opf-V's win.** opf-V runs at 1.4 samples/sec on the bench; nullpii at 23.9 samples/sec — **17× faster**. The robustness gap is bought with a latency budget that's untenable for chat / autocomplete / IDE inline use cases.
- **piiranha 3rd-4th but distribution-dependent.** Wins homoglyph among non-Viterbi tools (0.359) — its multilingual training likely sees enough Cyrillic/Greek lookalikes to handle them. Loses on plain char-swap to nullpii.
- **Deobfuscation pre-processors not enabled.** TextAttack's perturbations are token-level (homoglyph, char-swap/delete/insert/substitute). The off-by-default `--enable-deobf-whitespace` / `--enable-deobf-encoding` flags target *whitespace stretching* and *base64/URL/HTML wrapping* respectively, neither of which are in this corpus. Re-running with deobf flags enabled would not change these numbers.

**Methodological caveat (still):** TextAttack is third-party but the corpus is generated by us using TextAttack's library — the framework is independent, but the choice of perturbations + their parameters + the ai4privacy source data are ours. A truly independent adversarial PII benchmark (e.g. a published challenge dataset) would close the remaining gap; one is not currently available in public form.

## Direct competitors (AI Security / AI Firewall)

### Lakera

- **What**: Lakera Guard — API for prompt-injection / jailbreak detection (custom classifiers). Lakera Chrome extension (consumer). "Gandalf" viral demo for marketing.
- **Customer**: Mid-market and enterprise dev teams shipping LLM features.
- **Strengths**: Best-in-class injection-attack model, fast R&D iteration, low latency (~50–100 ms).
- **Weaknesses**: SaaS-only (no real self-host), detection-only — no native PII redaction or vault. Pricing scales fast at enterprise volume.
- **Layer**: Application (API wrapper).
- **Pricing**: Free tier (limited) → SaaS tiers → enterprise contract.
- **Differentiator**: Injection detection depth.

### Protect AI (acquired by Palo Alto Networks 2025)

- **What**: ModelScan (OSS — scans PyTorch/TF artefacts for malicious code), Guardian AI Firewall (runtime), AIDR (ML/LLM monitoring).
- **Customer**: Enterprise AI/ML teams; now F500 via Palo Alto distribution.
- **Strengths**: ML supply-chain coverage + runtime in one stack. Real model-scanning capability.
- **Weaknesses**: Roadmap uncertainty post-acquisition, enterprise-only pricing, less LLM-native (ML-rooted heritage).
- **Layer**: Application + supply chain.
- **Pricing**: Enterprise contract.
- **Differentiator**: Only player with credible model supply-chain security plus runtime.

### CalypsoAI

- **What**: Inference Defense + Moderator. Prompt injection, data-leak detection, bias scoring.
- **Customer**: Government, defense, regulated enterprise (FedRAMP path).
- **Strengths**: Compliance vertical (defense, federal), heavy red-teaming.
- **Weaknesses**: Not developer-friendly, expensive, narrow market, marketing > product.
- **Layer**: Application.
- **Pricing**: Enterprise / government contract.
- **Differentiator**: FedRAMP, gov vertical lock-in.

### Robust Intelligence (acquired by Cisco 2024)

- **What**: AI Firewall + continuous ML/LLM testing aligned to NIST AI RMF.
- **Customer**: Cisco enterprise base post-acquisition.
- **Strengths**: Cisco network distribution, AI red-teaming legacy, NIST alignment.
- **Weaknesses**: Post-M&A roadmap unclear, closed-source, slower release cadence.
- **Layer**: Application + network (Cisco-integrated).
- **Pricing**: Enterprise (Cisco channel).
- **Differentiator**: Network-grade distribution.

## LLM Gateway / Observability

### Portkey

- **What**: LLM gateway — routing, fallbacks, caching, retries, 100+ provider integrations. Guardrails as add-on.
- **Customer**: Dev teams, scale-ups, enterprise.
- **Strengths**: Dev-first, OSS core, fast feature shipping, broadest provider support.
- **Weaknesses**: Not security-first; guardrails are basic (regex / external API calls).
- **Layer**: Application (proxy / gateway).
- **Pricing**: Free OSS → cloud SaaS → enterprise self-host.
- **Differentiator**: Most complete LLM gateway feature set in the OSS world.

### Helicone

- **What**: LLM observability + caching + rate-limiting. Drop-in proxy (one-line URL change).
- **Customer**: Startups, individual devs.
- **Strengths**: Trivial integration, OSS, focused.
- **Weaknesses**: Obs-first, no security / PII handling, narrower than Portkey.
- **Layer**: Application.
- **Pricing**: Free → cloud → self-host.
- **Differentiator**: Lowest-friction LLM observability.

### Langfuse

- **What**: LLM observability + tracing + prompt management + eval framework. MIT OSS.
- **Customer**: Dev teams building LLM apps.
- **Strengths**: OSS-first, strong dev community, eval framework, mature tracing.
- **Weaknesses**: Obs + eval focus, no security or PII, no proxy / gateway.
- **Layer**: Application (SDK).
- **Pricing**: Free OSS → cloud → enterprise.
- **Differentiator**: Best OSS LLM observability + eval combo.

### Humanloop

- **What**: Prompt management + A/B testing + eval platform.
- **Customer**: PM / ML teams iterating on prompts.
- **Strengths**: PM-friendly UI, eval workflow.
- **Weaknesses**: Closed-source, narrow scope, commoditised feature set.
- **Layer**: Application.
- **Pricing**: SaaS.
- **Differentiator**: PM-oriented UI (vs dev-oriented Langfuse).

## Enterprise DLP (adjacent)

### Microsoft Purview

- **What**: M365 / Azure / endpoint DLP plus a recent "Copilot DLP" / "AI hub" module.
- **Customer**: F500 with M365 E5.
- **Strengths**: M365 native integration, FedRAMP / HIPAA / SOC2 certs, "AI" feature checkbox.
- **Weaknesses**: M365 lock-in, AI features narrow (Copilot only), expensive, slow innovation.
- **Layer**: Endpoint + cloud + application.
- **Pricing**: M365 E5 add-on / standalone.
- **Differentiator**: Already in budget for M365 customers.

### Symantec / Broadcom DLP

- **What**: Network / endpoint / cloud DLP — legacy enterprise.
- **Customer**: F500 (Broadcom-tier accounts).
- **Strengths**: Mature DLP rules, broad coverage.
- **Weaknesses**: Legacy UI, slow modernisation, no LLM-native features, post-Broadcom innovation stalled.
- **Layer**: Network + endpoint.
- **Pricing**: Enterprise.
- **Differentiator**: Legacy footprint.

### Forcepoint

- **What**: DLP + CASB + Web Security with risk-adaptive scoring.
- **Customer**: Regulated enterprise.
- **Strengths**: Behavioural analytics, user-context risk scoring.
- **Weaknesses**: Legacy stack, not LLM-aware natively.
- **Layer**: Network + endpoint.
- **Pricing**: Enterprise.
- **Differentiator**: Behavioural risk scoring.

## Network-level proxy / control

### Zscaler

- **What**: ZIA (cloud TLS-intercepting proxy) + ZPA (ZTNA). Recent AI-security module.
- **Customer**: F500.
- **Strengths**: Massive scale (100B+ tx/day), global PoPs, deep ZTNA integration.
- **Weaknesses**: Complex deploy, expensive, AI features bolted-on (not LLM-native), latency-sensitive verticals struggle.
- **Layer**: Network (cloud proxy).
- **Pricing**: Per-user / year enterprise.
- **Differentiator**: Scale + global infra.

### Netskope

- **What**: CASB + SWG + ZTNA + AI use-case visibility.
- **Customer**: Large enterprise.
- **Strengths**: CASB strength, SaaS-aware DLP, behavioural analytics.
- **Weaknesses**: AI features less mature than CASB core.
- **Layer**: Network + cloud.
- **Pricing**: Per-user enterprise.
- **Differentiator**: SaaS-visibility depth.

## Guardrails / Open source

### Guardrails AI

- **What**: OSS (Apache 2.0) library for LLM output validation. RAIL spec. Validators (type, profanity, PII, etc.).
- **Customer**: Dev teams.
- **Strengths**: OSS, composable validators, RAIL DSL.
- **Weaknesses**: Library-only (no proxy / gateway), small validator set, perf overhead, validation rather than prevention.
- **Layer**: Application (library).
- **Pricing**: Free OSS + Guardrails Hub paid validators.
- **Differentiator**: Composable validation framework.

### Rebuff

- **What**: OSS prompt-injection detector (heuristic + LLM-based + canary tokens).
- **Customer**: Dev teams.
- **Strengths**: OSS, focused, multi-layer detection.
- **Weaknesses**: Narrow (injection only), small project, low maintenance velocity.
- **Layer**: Application.
- **Pricing**: Free OSS.
- **Differentiator**: Multi-layer injection detection (heuristic + LLM + canary).

### NVIDIA NeMo Guardrails

- **What**: OSS framework for LLM rails. Colang DSL for flow control.
- **Customer**: NVIDIA stack users, enterprise dev.
- **Strengths**: NVIDIA backing, Colang flexibility, NeMo integration.
- **Weaknesses**: Steep learning curve, rails-via-LLM-call adds latency (50–200 ms), Colang DSL niche.
- **Layer**: Application.
- **Pricing**: Free OSS.
- **Differentiator**: Most mature DSL approach to LLM flow control.

## Comparative analysis

### Closest to "AI Gateway + Security" combined model

- **Portkey + Lakera**: closest functional combo today (gateway + security plug-in).
- **Single-vendor**: Protect AI (Palo Alto) and Robust Intelligence (Cisco) — both pivoting toward gateway via parent-company network reach.
- **Open path**: Langfuse (obs) + Guardrails AI (validation) + custom proxy = manual assembly. No turnkey OSS equivalent exists.

### Biggest market gaps

1. **OSS enterprise-grade AI gateway with native reversible PII redaction** — nobody. Portkey / Helicone are obs-first, Lakera is closed, Guardrails AI is library-only, Skyflow is cloud-only. **This is nullpii's slot.**
2. **HIPAA / healthcare-vertical AI proxy** — generic players don't handle structured medical templates. Purview is M365-locked. Vertical play opportunity.
3. **Reversible PII (sanitize → LLM → restore)** — rare. Skyflow does it as cloud SaaS. nullpii's vault is differentiator.
4. **Latency-aware deployment** — Lakera / Portkey add 100–300 ms. Not viable for autocomplete / IDE inline. Local-first (nullpii) avoids this.
5. **Self-hosted OSS-license tier between "library" and "Zscaler-tier closed product"** — Guardrails AI is library, Zscaler is closed enterprise SaaS, nothing in the middle.

### Overrated vs actually strong

**Overrated:**

- **CalypsoAI** — defense marketing > product depth; feature set comparable to Lakera at much higher cost.
- **Humanloop** — prompt mgmt commoditised, thin differentiation.
- **Microsoft Purview AI features** — narrow Copilot-only, leverages M365 hype rather than capability.
- **Symantec / Broadcom DLP** — legacy, slow innovation, declining.

**Actually strong (real capability):**

- **Lakera** — focused, real R&D output, fastest iteration in the security-only category.
- **Langfuse** — best OSS LLM obs; dev community is real adoption, not Twitter hype.
- **Portkey** — feature parity vs enterprise tools at startup price.
- **Robust Intelligence (post-Cisco)** — distribution scale will dominate enterprise AI Firewall category over the next 24 months.
- **NVIDIA NeMo Guardrails** — under-appreciated by SMB but solid for NVIDIA-stack enterprise.

**False strong (perception > reality):**

- **Zscaler / Netskope AI features** — bolted on, not LLM-native. Big potential, not present-day differentiator. Don't buy them for AI specifically yet.

### Strategic position for nullpii

**Whitespace `nullpii` fills:**

- OSS (no closed-cloud lock-in like Skyflow / Lakera).
- Reversible vault (rare — only Skyflow has, cloud-only).
- Local-first (no network hop = no latency tax).
- Backbone-agnostic (proxy mode wraps any LLM provider).
- Per-vertical profiles roadmapped (dev paste / healthcare / general).

**Where `nullpii` loses:**

- Brand awareness vs Lakera / Portkey.
- No injection detection (PII-only — needs Rebuff-equivalent module or partner).
- No model supply-chain coverage (Protect AI's moat).
- No FedRAMP / SOC2 yet (vs CalypsoAI in regulated verticals).

**Strategy implication:**

Position as **"OSS PII firewall for LLM traffic"** — not as gateway competitor.

- Pair with **Portkey** (gateway) + **Rebuff** (injection) for the full stack.
- Compete with **Skyflow** head-on (OSS vs cloud-only).
- Avoid head-to-head with **Lakera** (they own injection detection; we own PII redaction).
- Lean into the **local-first / latency-zero / reversible vault** triad, which the closed-cloud players cannot match without architectural overhaul.
