# Competitive analysis — AI Gateway / AI Firewall / PII Redaction

Snapshot dated 2026-05-01. Used to position `nullpii` against the existing landscape and identify the whitespace it actually fills. Not exhaustive — focused on the players that overlap with the npm-package + enterprise-proxy roadmap items.

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
