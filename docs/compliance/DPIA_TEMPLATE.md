# Data Protection Impact Assessment (DPIA) — `nullpii` deployment

**Template under GDPR Art. 35**. Fill in per deployment. Required when nullpii is used to process personal data at scale, especially in EU jurisdictions.

> **Disclaimer.** This template is provided as a research artefact. It is not legal advice. Have qualified counsel (DPO + privacy lawyer in your jurisdiction) review before signing off.

---

## 1. Description of the processing operation

### 1.1 Nature of the processing
- **Tool**: `nullpii` v__VERSION__ (npm) / HF model `lBroth/nullpii` (if used)
- **Profile selected**: `devops` | `legal` | `medical` | `general`
- **Backend**: CPU | MPS | CUDA | ROCm
- **Deployment shape**: in-process npm library | CLI batch | HTTPS proxy | edge worker
- **Data flow**:
  1. Source system (e.g. internal Slack export, customer-support ticket queue, code repository) emits text containing personal data.
  2. Text is passed to nullpii's `sanitize()` — runs ML detection + regex + (optional) post-processing locally, in the same process.
  3. Vault (in-memory only, never persisted) stores `(placeholder, original_value)` pairs scoped to the request.
  4. Sanitised text passes to downstream system (LLM, log store, analytics).
  5. On response, vault is consulted to restore placeholders; vault is cleared at end-of-request.

### 1.2 Scope of the processing
- **Categories of data subjects**: employees | customers | court parties | patients | platform users | __OTHER__
- **Categories of personal data**:
  - Identification: names, emails, phone numbers, postal addresses
  - Online identifiers: IP addresses, MAC addresses, URLs, UUIDs, session IDs
  - Financial: IBAN, credit card, account numbers, tax IDs
  - Authentication: API keys, OAuth tokens, password fragments, JWT tokens
  - Demographic / quasi-identifiers: dates, ZIP codes, gender (if mentioned)
  - **Special-category data (Art. 9)**: ⚠️ **see §3.2 — nullpii does NOT detect Art. 9 categories per its 8-class schema. Do not rely on nullpii alone for Art. 9 redaction.**
- **Volume / frequency**: __EST_REQUESTS_PER_DAY__ requests/day, __EST_AVG_TEXT_LENGTH__ chars/request
- **Retention**: in-memory vault is cleared at end-of-request. The sanitised text retention is governed by the downstream system, not by nullpii.

### 1.3 Purpose
Enumerate why processing occurs:
- LLM-prompt sanitisation (prevent personal data leaking to OpenAI / Anthropic / Gemini)
- Log redaction
- Customer-support ticket pre-processing
- Court-record / contract anonymisation (`legal` profile)
- Other: __SPECIFY__

---

## 2. Necessity and proportionality

### 2.1 Lawful basis (Art. 6)
Pick one and justify:
- (a) Consent — covered by the user agreement at __URL__
- (b) Performance of contract
- (c) Legal obligation
- (d) Vital interests
- (e) Public task
- (f) Legitimate interest — interest balancing test in §6

### 2.2 Special-category lawful basis (Art. 9), if applicable
- N/A — Art. 9 categories not processed (the input is filtered upstream of nullpii).
- (a) Explicit consent
- (b) Employment / social-security obligation
- (h) Healthcare provision (HIPAA-equivalent jurisdiction)
- (i) Public health
- (j) Archiving / scientific research

⚠️ **If Art. 9 categories are present in input text, document the upstream filter that catches them — nullpii's schema does not include them.**

### 2.3 Data minimisation
- Inputs to nullpii are texts that already need processing for downstream purpose; nullpii adds redaction, not collection.
- Vault is in-memory, scoped to request, never persisted.
- `nullpii` does not phone home, does not log payload.

### 2.4 Storage limitation
- nullpii itself: zero-retention by design (vault discarded end-of-request).
- Sanitised output text is governed by the downstream system's retention policy. **Document that policy here**: __DOWNSTREAM_RETENTION__

---

## 3. Risks to data subjects

### 3.1 Detection-level risks (false negatives)

False negatives = personal data NOT redacted = leaks downstream.

Headline F1 numbers (single-seed, IoU≥0.5, see `COMPETITIVE_ANALYSIS.md`):

| Profile | nullpii-bench | tab-echr | oasst-dev | ai4privacy-300k | isotonic-en |
|---|---:|---:|---:|---:|---:|
| `devops` (v6) | 0.86 | 0.22 | 0.62 | 0.31 | 0.59 |
| `legal` (v8) | 0.55 | 0.71 | 0.47 | 0.56 | 0.89 |
| `medical` | 0.55 | 0.71 | 0.47 | 0.56 | 0.89 |
| `general` (ensemble) | 0.63 | 0.46 | 0.57 | 0.49 | 0.73 |

**Interpretation**: at F1 0.86 on dev-paste, ~14% of personal data items are not redacted. Per-class precision/recall available in `packages/eval/results/<bench-id>/confusion.json` — high-stakes deployments should review per-class numbers, not aggregate F1.

**Mitigation**:
- Pair with a downstream review step (human-in-the-loop) for high-risk workloads.
- Pair with `general` profile (ensemble) when uncertain about input domain.
- Run a known-good test corpus pre-deployment + monthly regression checks.

### 3.2 Schema-level risks (Art. 9 invisibility)

⚠️ **nullpii's 8-class schema does not include health, biometric, political, religious, sexual-orientation, trade-union, ethnic-origin, or criminal data.** A Slack thread mentioning sick leave, an HR file flagging political affiliation, a contract referring to ethnic origin — these are passed through with the *names and dates* redacted but the *categorical fact itself* unmodified.

**Mitigation (mandatory if Art. 9 categories are plausibly present)**:
- Upstream classifier that flags Art. 9 categorical content and routes to a separate review path.
- Explicit deny-list of Art. 9 vocabulary per language (not provided by nullpii).
- DPO sign-off on the upstream filter design before production traffic.

### 3.3 Re-identification risks (quasi-identifiers)

Even after nullpii redacts direct identifiers, combinations of quasi-identifiers (gender + ZIP + DOB; rare-disease name + city; specific job title + company) can re-identify per k-anonymity research. nullpii does **not** perform k-anonymity calculations.

**Mitigation**: pair with a dedicated anonymisation tool (e.g. ARX, Microsoft Presidio's anonymisation engine) for k-anonymity / l-diversity / t-closeness on the sanitised output, if the downstream system is published or shared widely.

### 3.4 Adversarial / evasion risks
nullpii's adversarial behaviour is documented as a transparency probe, not a robustness claim. On the TextAttack run nullpii scores 0.28 (vs opf-Viterbi 0.31). Users actively trying to evade detection (homoglyph, whitespace stretching, base64 wrapping) may bypass nullpii. **For workloads where evasion is plausible (marketplace chat blocking direct contact, content-moderation pipelines), enable** `--enable-deobf-whitespace` / `--enable-deobf-encoding` flags **and budget for additional review**.

### 3.5 Latency / availability risks
- See §4 SLA.
- Failure mode: if the model fails to load (e.g. corrupted weights, OOM), `sanitize()` raises. Downstream system must handle the exception, NOT silently pass unsanitised text. Document the failure-mode handling here: __FAILURE_HANDLING__

---

## 4. Latency / SLA per profile × hardware

(Placeholder; populate from `packages/eval/results/latency-bench-<id>/` when produced.)

| Profile | Hardware | p50 | p95 | p99 | Notes |
|---|---|---:|---:|---:|---|
| `devops` | Mac M-series CPU | __ms | __ms | __ms | |
| `devops` | Linux x86 CPU | __ms | __ms | __ms | |
| `devops` | CUDA L40 | __ms | __ms | __ms | |
| `legal` | Mac M-series CPU | __ms | __ms | __ms | v8 model heavier |
| `general` | Mac M-series CPU | __ms | __ms | __ms | 2× backbone latency |

---

## 5. Subject rights (Art. 12-22)

How does the deployment satisfy:
- **Right of access** (Art. 15): downstream system tracks the original-text-to-sanitised-text mapping in its retention store; user can request a copy.
- **Right to rectification** (Art. 16): correction request flows back to upstream system; nullpii does not store data.
- **Right to erasure** (Art. 17): nullpii's vault is auto-discarded; downstream system handles erasure on its retained data.
- **Right to data portability** (Art. 20): downstream system handles export; nullpii is invisible in the data layer.

---

## 6. Legitimate interest balancing test (if Art. 6(1)(f) is the basis)

| Step | Argument |
|---|---|
| Identify the legitimate interest pursued | Sanitising LLM prompts to prevent personal-data leaks to third-party API providers |
| Show necessity | LLM API providers do not contractually guarantee non-retention of prompts; sanitisation is the only effective control at the application layer |
| Balance against subject rights | Subject is not present at processing time (the data is already in transit to the LLM); sanitisation reduces, not increases, the risk to the subject |
| Outcome | Legitimate interest justified IF the upstream system has a separate Art. 6 basis for collecting the data in the first place. nullpii does NOT establish a basis on its own. |

---

## 7. Sub-processors / vendor disclosures

| Component | Vendor | Role | Location |
|---|---|---|---|
| GLiNER backbone weights | HuggingFace (URL: https://huggingface.co/onnx-community/gliner_multi_pii-v1) | one-time download at install/CI | downloaded once, ran locally |
| `onnxruntime-node` | Microsoft (Apache 2.0) | inference runtime | local |
| nullpii npm package | Anthropic-aligned OSS author (lBroth) | sanitisation engine | local |
| Downstream LLM provider | OpenAI / Anthropic / Gemini / Mistral / __OTHER__ | receives sanitised text | __PROVIDER_REGION__ — document SCC + adequacy under Schrems II |

⚠️ **Schrems II**: if the downstream LLM provider transfers EU personal data to the US, document the transfer impact assessment + supplementary measures (sanitisation here is one such measure, not a complete replacement for SCC + TIA).

---

## 8. Sign-off

| Role | Name | Date | Notes |
|---|---|---|---|
| DPO | | | |
| Engineering owner | | | |
| Privacy counsel | | | |
| Security review | | | |

**Re-DPIA trigger**: bump nullpii major version, add new profile, add new downstream provider, add new data category, EU AI Act enforcement milestones.
