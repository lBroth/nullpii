# Competitive analysis — AI Gateway / AI Firewall / PII Redaction

Snapshot 2026-05-04. Used to position `nullpii` against the existing landscape and identify the whitespace it fills. Not exhaustive — focused on players that overlap with the npm-package + adapter / managed-cloud roadmap.

**Related**: [`README.md`](README.md) (TL;DR + install + bench table) · HF model card: [`lBroth/nullpii-v10-router-embedding`](https://huggingface.co/lBroth/nullpii-v10-router-embedding).

## Empirical bench numbers

> **Status**: first release. Local Mac CPU bench complete; numerical results at `packages/eval/published-bench/matrix.{json,csv}`. Methodology + bench surface documented below.

> **Active caveats on the published bench cells**: 3 of the 10 rows (`nullpii-bench`, `tab-echr`, `nemotron-pii-test`) are in-distribution diagnostic — adapters trained on slices of those datasets, so F1 is memorisation, not OOD generalisation. Per-row ⚠ flags in the per-dataset table; held-out OOD F1 (4 rows) reported separately as 0.7378 in the README headline.

### Bench surface (`packages/eval/scripts/bench_full.py`)

8 tools, single matrix, single code revision, IoU ≥ 0.5 macro F1.

| Tool | Wrapping |
|---|---|
| `nullpii` | local npm CLI (`node bin/nullpii.mjs scan --ndjson`) — canonical user-facing row, full router stack |
| `nullpii-v10-router-embedding` | Python re-impl of the same pipeline — distiluse + 5 LoRA adapters over `urchade/gliner_multi_pii-v1`. Used for delta-vs-subprocess sanity check |
| `presidio` | **Microsoft Presidio Analyzer** — bare upstream defaults |
| `gliner-onnx-pii-fp32` | bare HF inference of `urchade/gliner_multi_pii-v1` (GLiNER, Zaratiana et al., NAACL 2024) |
| `piiranha` | `iiiorg/piiranha-v1-detect-personal-information` — bare upstream defaults |
| `deberta` | `lakshyakh93/deberta_finetuned_pii` — community fine-tune of **Microsoft DeBERTa-v3** |
| `nemotron-pii-raw` | **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`) — bare upstream + 55→8 label remap |
| `gliner-pii-large-v1` | `knowledgator/gliner-pii-large-v1.0` — bare HF |

**Strict bare-mode contract**: no competitor row wraps `boundary_refined`, `never_pii_filter`, `url_filter`, `regex_pack`, or `_normalize_for_detection` (NFKC + unidecode + zero-width strip + HTML entity decode + URL %XX decode + spaced-PII despace). Each tool runs as its upstream project intends. The only adapter glue applied uniformly is the chunking 1400/200 stride (so long-doc handling is fair across all GLiNER-family bare baselines and `nemotron-pii-raw`) plus per-tool label remap to the 8-class schema (presidio, deberta, nemotron-pii — the bench bridge needed for F1 comparability, common to any cross-schema NER eval).

### Datasets in scope (10 PII-native)

`nullpii-bench` (project-bundled), `tab-echr`, `nemotron-pii-test`, `presidio-synthetic`, `ai4privacy-300k-heldout-v10` (offset 100k+), `isotonic-{en,de}-heldout-v10` (offset 200k+), `adversarial-{typo,unicode,code}` (synthetic perturbations).

**Why not the previous broader 27-dataset surface?** Cleaned to the canonical hobby-bench surface — kept the rows where nullpii has either an adversarial-preprocessor signal (typo/unicode/code) or a strong baseline reference (Presidio/Nemotron own data), plus held-out evaluation rows. Whitespace + encoding adversarial rows (where preprocessor regresses) and TextAttack 5-perturbation breakdowns dropped — covered conceptually by `adversarial-typo` + `adversarial-unicode`. Wikiann (PER/LOC NER, loose mapping) and adversarial-decoys (zero gold spans) permanently excluded.

## Direct competitors (AI Security / AI Firewall)

### Lakera

- **What**: Lakera Guard — API for prompt-injection / jailbreak detection. Lakera Chrome extension (consumer). "Gandalf" viral demo.
- **Customer**: Mid-market and enterprise dev teams shipping LLM features.
- **Strengths**: Best-in-class injection-attack model, fast R&D iteration, low latency (~50–100 ms).
- **Weaknesses**: SaaS-only (no real self-host), detection-only — no native PII redaction or vault. Pricing scales fast at enterprise volume.
- **Differentiator**: Injection detection depth.

### Protect AI (acquired by Palo Alto Networks 2025)

- **What**: ModelScan (OSS — scans PyTorch/TF artefacts), Guardian AI Firewall (runtime), AIDR (ML/LLM monitoring).
- **Customer**: Enterprise AI/ML teams; F500 via Palo Alto distribution.
- **Strengths**: ML supply-chain coverage + runtime in one stack. Real model-scanning capability.
- **Weaknesses**: Roadmap uncertainty post-acquisition, enterprise-only pricing, less LLM-native.
- **Differentiator**: Only player with credible model supply-chain security plus runtime.

### CalypsoAI

- **What**: Inference Defense + Moderator. Prompt injection, data-leak detection, bias scoring.
- **Customer**: Government, defense, regulated enterprise (FedRAMP path).
- **Strengths**: Compliance vertical, heavy red-teaming.
- **Weaknesses**: Not developer-friendly, expensive, narrow market.
- **Differentiator**: FedRAMP, gov vertical lock-in.

### Robust Intelligence (acquired by Cisco 2024)

- **What**: AI Firewall + continuous ML/LLM testing aligned to NIST AI RMF.
- **Customer**: Cisco enterprise base post-acquisition.
- **Strengths**: Cisco network distribution, AI red-teaming legacy, NIST alignment.
- **Weaknesses**: Post-M&A roadmap unclear, closed-source, slower release cadence.
- **Differentiator**: Network-grade distribution.

## LLM Gateway / Observability

### Portkey

- **What**: LLM gateway — routing, fallbacks, caching, retries, 100+ provider integrations. Guardrails as add-on.
- **Strengths**: Dev-first, OSS core, fast feature shipping, broadest provider support.
- **Weaknesses**: Not security-first; guardrails are basic (regex / external API calls).
- **Differentiator**: Most complete LLM gateway feature set in the OSS world.

### Helicone

- **What**: LLM observability + caching + rate-limiting. Drop-in proxy.
- **Strengths**: Trivial integration, OSS, focused.
- **Weaknesses**: Obs-first, no security / PII handling, narrower than Portkey.

### Langfuse

- **What**: LLM observability + tracing + prompt management + eval framework. MIT OSS.
- **Strengths**: OSS-first, strong dev community, eval framework, mature tracing.
- **Weaknesses**: Obs + eval focus, no security or PII, no proxy / gateway.

### Humanloop

- **What**: Prompt management + A/B testing + eval platform.
- **Strengths**: PM-friendly UI, eval workflow.
- **Weaknesses**: Closed-source, narrow scope, commoditised.

## Enterprise DLP (adjacent)

### Microsoft Purview

- **What**: M365 / Azure / endpoint DLP plus a "Copilot DLP" / "AI hub" module.
- **Strengths**: M365 native integration, FedRAMP / HIPAA / SOC2 certs.
- **Weaknesses**: M365 lock-in, AI features narrow (Copilot only), expensive, slow innovation.

### Symantec / Broadcom DLP

- **What**: Network / endpoint / cloud DLP — legacy enterprise.
- **Strengths**: Mature DLP rules, broad coverage.
- **Weaknesses**: Legacy UI, slow modernisation, no LLM-native features.

### Forcepoint

- **What**: DLP + CASB + Web Security with risk-adaptive scoring.
- **Strengths**: Behavioural analytics, user-context risk scoring.
- **Weaknesses**: Legacy stack, not LLM-aware natively.

## Network-level proxy / control

### Zscaler

- **What**: ZIA (cloud TLS-intercepting proxy) + ZPA (ZTNA). AI-security module bolted on.
- **Strengths**: Massive scale (100B+ tx/day), global PoPs, deep ZTNA integration.
- **Weaknesses**: Complex deploy, expensive, AI features bolted-on.

### Netskope

- **What**: CASB + SWG + ZTNA + AI use-case visibility.
- **Strengths**: CASB strength, SaaS-aware DLP, behavioural analytics.
- **Weaknesses**: AI features less mature than CASB core.

## Guardrails / Open source

### Guardrails AI

- **What**: OSS (Apache 2.0) library for LLM output validation. RAIL spec.
- **Strengths**: OSS, composable validators, RAIL DSL.
- **Weaknesses**: Library-only (no proxy / gateway), small validator set.

### Rebuff

- **What**: OSS prompt-injection detector (heuristic + LLM-based + canary tokens).
- **Strengths**: OSS, focused, multi-layer detection.
- **Weaknesses**: Narrow (injection only), small project.

### NVIDIA NeMo Guardrails

- **What**: OSS framework for LLM rails. Colang DSL.
- **Strengths**: NVIDIA backing, Colang flexibility, NeMo integration.
- **Weaknesses**: Steep learning curve, latency overhead, Colang DSL niche.

### Skyflow (PII vault, cloud-only)

- **What**: Tokenisation + reversible PII vault as a managed service.
- **Strengths**: Mature tokenisation, healthcare/finance verticals, reversibility.
- **Weaknesses**: Cloud-only (network hop on every request), closed-source, no local mode.

## Strategic position for nullpii

**Whitespace `nullpii` fills**:

- OSS (no closed-cloud lock-in like Skyflow / Lakera).
- Reversible vault (rare — only Skyflow has, cloud-only).
- Local-first (no network hop = no latency tax).
- Domain-routed adapters (devops / legal / medical / narrative / enterprise) per-vertical out-of-box.
- Multilingual via embedding-based router (50+ languages via distiluse).

**Where `nullpii` loses**:

- Brand awareness vs Lakera / Portkey.
- No injection detection (PII-only — needs Rebuff-equivalent or partner).
- No model supply-chain coverage (Protect AI's moat).
- No FedRAMP / SOC2 yet.

**Positioning**: "OSS local-first PII redaction for LLM traffic." Pairs with Portkey (gateway) + Rebuff (injection) for full stack. Competes with Skyflow head-on (OSS vs cloud-only). Avoids head-to-head with Lakera (they own injection; we own PII).
