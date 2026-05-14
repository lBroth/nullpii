<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with reversible in-memory vault. ML span detection swaps PII with placeholders; pass the sanitized text anywhere (LLM, log, third-party API), then restore original values from the response.

## Why this exists

Honest framing: this is a **night-hobby project**, not a production-ready PII tool, not a research paper, not a commercial product.

Since I started using Claude Code I stopped playing video games — it became my night toy. nullpii is what fell out of those nights: a chance to learn the GLiNER + LoRA stack end-to-end, run it under a strict bench harness, write the honest audit on what works and what doesn't, and ship something that does the round-trip cleanly. v0.1 shipped a 5-shard routed stack; v0.2 collapses it into a single unified model trained on a permissive-only corpus.

What's interesting here is the engineering rigor + adversarial preprocessor, not state-of-the-art F1.

> **Status (2026-05-13)** — `v0.2` track. Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, ~278M params). Shipping pipeline: a **unified** LoRA adapter merged into the GLiNER backbone (`~1.2 GB FP32` total artifacts, ~350 MB int8). Recognizer pack + adversarial preprocessor + base64 decoder run client-side in the npm runtime.

## Bench at a glance

MacBook Pro M5 Pro CPU, 7-dataset canonical surface (macro), macro F1 at IoU ≥ 0.5 (partial-match span scoring), `--parallel-tools 1` fair-serial, cap=5000 per dataset. `nullpii` = npm subprocess (what `npm i nullpii` runs — unified merged-LoRA GLiNER + recognizer pack + adversarial preprocessor + base64 decoder + never-PII filter); other columns = bare third-party baselines (no nullpii post-processing). Full matrix (16 datasets): [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv). Run: `results/overnight-local-20260514/` (2026-05-14, 11h, zero failure).

`nullpii-bench` is the unified project corpus (2,421 rows of multilingual prompts with hand-curated PII spans) — single F1 number summarises behaviour on the project's adversarial-input surface. Multilingual coverage via held-out isotonic in en + de + fr + it.

| Dataset | n | **`nullpii`** | `nemotron-pii-raw` | `gliner-pii-large-v1` | `deberta` | `piiranha` | `presidio` |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `presidio-synthetic` | 5 000 | **0.9184** | 0.6182 | 0.6319 | 0.4451 | 0.3828 | 0.5746 § |
| `isotonic-en-heldout` | 5 000 | **0.7660** | 0.7276 | 0.5838 | 0.7512 | 0.5659 | 0.4726 |
| `isotonic-it-heldout` | 5 000 | **0.7605** | 0.6922 | 0.5720 | 0.5367 | 0.5658 | 0.4133 |
| `isotonic-fr-heldout` | 5 000 | **0.7594** | 0.6968 | 0.5677 | 0.5738 | 0.5694 | 0.4129 |
| `isotonic-de-heldout` | 5 000 | **0.7490** | 0.7037 | 0.5827 | 0.4934 | 0.5642 | 0.4047 |
| `tab-echr` ⚠ | 127 | **0.6941** | 0.4520 | 0.1004 | 0.1745 | 0.1704 | 0.4657 |
| `nullpii-bench` ⚠ self-authored | 2 421 | **0.5937** | 0.4678 | 0.2769 | 0.3070 | 0.2434 | 0.2303 |
| `nemotron-pii-test` ⚠ | 5 000 | **0.9537** | 0.8997 ‡ | 0.5376 | 0.5789 | 0.4876 | 0.5222 |
| `ai4privacy-300k-heldout` † | 5 000 | **0.3857** | 0.3688 | 0.1352 | 0.1586 | 0.2610 | 0.2099 |
| **Held-out OOD multilingual (5)** ← headline | — | **0.7907** | 0.6877 | 0.5876 | 0.5601 | 0.5296 | 0.4556 |
| **Mixed (7)** ¶ — incl. 2 ⚠ in-dist rows | — | **0.7487** | 0.6226 | 0.4736 | 0.4688 | 0.4374 | 0.4249 |
| **In-distribution diagnostic (2)** ⚠ | — | **0.6439** | 0.4599 | 0.1886 | 0.2407 | 0.2069 | 0.3480 |

**Headline — held-out OOD multilingual macro F1 = 0.7907** over 5 datasets the model never saw during training (`presidio-synthetic`, `isotonic-{en,de,fr,it}-heldout`): real generalisation across 4 languages, **+0.103 over the next-best baseline** (`nemotron-pii-raw` 0.6877). The 7-dataset **Mixed F1 = 0.7487** (+0.126 over `nemotron-pii-raw` 0.6226) folds in two ⚠ in-distribution diagnostic rows (`nullpii-bench` self-authored, `tab-echr`) — supporting, not the headline. nullpii wins every row on the canonical surface. `nemotron-pii-test` ⚠ excluded from every macro aggregate (simultaneous self-bench for `nemotron-pii-raw`). `ai4privacy-300k-heldout` † excluded from headline: ai4privacy is licence-gated (commercial use requires `licensing@ai4privacy.com`) so v0.2 model has zero exposure to its distribution — shown for transparency, treat as ultra-OOD.

Bucket interpretation:
- **Held-out OOD multilingual (5)** — model never saw these rows during training: `presidio-synthetic`, `isotonic-{en,de,fr,it}-heldout`. Real generalisation across 4 languages.
- **In-distribution diagnostic (2)** — same distribution as training (`nullpii-bench` ⚠ self-authored, `tab-echr` MIT). F1 here is in-distribution behaviour, not OOD generalisation. `nullpii-bench` summarises adversarial-pattern resistance in one cell. `nemotron-pii-test` ⚠ shown for reference but **excluded from all macro rows** — simultaneous self-bench for `nemotron-pii-raw`.

Legend:
- **bold** = best of the row
- ⚠ = in-distribution row (see bucket above)
- ⚠ self-authored = in-distribution diagnostic for the project pipeline; treat as a project regression test, not an OOD generalisation claim
- † `ai4privacy-300k-heldout` excluded from headline aggregate — licence-gated (cannot use in training); shown for transparency.
- ¶ `nemotron-pii-test` row shown for reference but excluded from all **Mixed** / **In-distribution** macro aggregates (simultaneous self-bench for `nemotron-pii-raw`)
- ‡ `nemotron-pii-raw` runs on its own training distribution — same self-bench caveat as nullpii on `nemotron-pii-test`
- § `presidio` runs on `presidio-synthetic` (generated by **Microsoft Presidio Evaluator**) — also a self-bench

### Latency

Hardware: **MacBook Pro · Apple M5 Pro · 48 GB · macOS 26.4** · CPU backend (no GPU/MPS).

`nullpii` per input size (n=50/size, single inference cycle, model preloaded):

| Input size | p50 | p95 | p99 |
|---|---:|---:|---:|
| 100 chars | 81 ms | 87 ms | 91 ms |
| 1 000 chars | 230 ms | 251 ms | 259 ms |
| 10 000 chars | 2.15 s | 2.25 s | 2.83 s |

### Cross-tool throughput (fair, serial)

6 tools × 15 datasets (cap 5 000 per dataset, `nemotron-pii-test` excluded), `--parallel-tools 1` (no CPU sharing). Same hardware as above. Throughput aggregated as `Σ n / Σ wall_s` across all 15 dataset cells per tool. **mixed F1 = 7-dataset macro** (canonical surface).

| Tool | mixed F1 | total samples | wall (s) | samp/s |
|---|---:|---:|---:|---:|
| `presidio` | 0.4249 | 64 548 | 392.4 | **164.5** |
| `deberta` | 0.4688 | 64 548 | 1 776.3 | 36.3 |
| **`nullpii`** | **0.7487** | 64 548 | 2 017.1 | 32.0 |
| `piiranha` | 0.4374 | 64 548 | 2 588.7 | 24.9 |
| `gliner-pii-large-v1` | 0.4736 | 64 548 | 10 848.7 | 5.9 |
| `nemotron-pii-raw` | 0.6226 | 64 548 | 16 009.3 | 4.0 |

`presidio` (regex/SpaCy) tops throughput at lowest F1. `nullpii` runs the unified GLiNER + recognizer pack + adversarial preprocessor + base64 decoder stack and lands in the top tier on throughput while topping F1 by **+0.126** over the next-best tool (`nemotron-pii-raw`). Source: `packages/eval/published-bench/matrix.json`. Full 16-dataset matrix (incl. ai4privacy / argilla extras and `ai4privacy-400k` where `piiranha` wins via training-set overlap) at `packages/eval/results/overnight-local-20260514/matrix.csv`.

### Where the +0.126 macro lives — concrete adversarial inputs

Six rows pulled directly from the `2026-05-14` bench checkpoints (`packages/eval/results/overnight-local-20260514/checkpoints/`). Each one is a real `nullpii-bench` sample where `nullpii` recovers the PII span and at least four of the five competing tools (`presidio`, `piiranha`, `deberta`, `gliner-pii-large-v1`, `nemotron-pii-raw`) miss it entirely under partial-match (IoU ≥ 0.5) scoring.

| Adversarial surface | Input | Decoded / canonical form | `nullpii` catches | Missed by |
|---|---|---|:---:|---|
| **base64-wrapped secret** | `(base64-encoded) c2stYW50LWFwaTAzLWFCY0RlRmcw…` | `sk-ant-api03-aBcDeFg012345…` (Anthropic key) | ✓ `secret` | `presidio`, `piiranha`, `nemotron-pii-raw` |
| **HTML-entity-encoded secret** | `(html_entity-encoded) &#115;&#107;&#45;&#97;&#110;&#116;&#45;…` | `sk-ant-…012345678901234567890123456789AA` | ✓ `secret` | `deberta`, `piiranha`, `gliner-pii-large-v1`, `nemotron-pii-raw` |
| **URL-percent-encoded email** | `(url-encoded) bob.jones%40company.io` | `bob.jones@company.io` | ✓ `private_email` | `deberta`, `piiranha`, `gliner-pii-large-v1`, `nemotron-pii-raw` |
| **Zero-width-obfuscated address** | `Profile: 221B Baker St[U+200B]re[U+200B]et [U+200B]London …` | `221B Baker Street London` | ✓ `private_address` | every other tool |
| **Spaced-out email** | `Detected pattern: u s e r . 1 2 3 @ g m a i l . c o m — …` | `user.123@gmail.com` | ✓ `private_email` | every other tool |
| **IBAN inside prose** | `Please contact IT60X0542811101000001023456 for details.` | (Italian IBAN, mod-97 valid) | ✓ `account_number` | `deberta`, `piiranha`, `gliner-pii-large-v1`, `nemotron-pii-raw` |
| **Multilingual address + date** | `Spedito a via Roma 45, 00184 Roma, nato il 14/02/1988.` | (literal) | ✓ both spans | every other tool misses at least one |
| **Stripe key in code context** | `api_key = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc'` | (literal) | ✓ `secret` | `deberta`, `piiranha`, `presidio`, `nemotron-pii-raw` |

These are exactly the inputs the headline macro stops aggregating over — `nullpii-bench` mixes them into a single F1 by design. The wins come from layered post-processing that the bare ML competitors don't ship: `base64-detector` decodes-then-classifies, `normalize.ts` iteratively decodes URL `%XX` and HTML numeric entities and strips zero-width characters before remapping spans back to original offsets, the 50+ recognizer regex pack (Stripe / Anthropic / IBAN / Luhn / mod-97 / etc.) catches token shapes the model wasn't trained to recognise, and the `private_ip` post-pass + RFC 5737 / 1918 / loopback never-PII filter keeps false positives off documentation traffic.

Adversarial robustness comes from the **runtime pipeline**, not the model alone. The HF `lBroth/nullpii` model card publishes both `model-only` and `full runtime` columns so the delta is explicit.

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an optional peer dependency (CPU / MPS / CUDA backend). Requires Node ≥ 22 (`.nvmrc` pins 24 for development).

> **First-call download**: the first `sanitize()` invocation downloads ~1.2 GB of model artifacts from HuggingFace Hub ([`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — one unified merged-LoRA ONNX + tokenizer + GLiNER config) into `~/.cache/nullpii/` (or `$XDG_CACHE_HOME/nullpii/`). One-shot; subsequent calls hit the local cache. Downloads stream to a per-process temp file, verify a SHA-256 checksum, retry transient failures with exponential backoff, and are idempotent — re-running after an interruption resumes from whichever files already verified.
>
> Pre-download deterministically (Docker build, CI, air-gapped staging) with `npx nullpii prefetch`; check the cache + backends with `npx nullpii doctor`. For fully air-gapped installs, mirror the HF repo locally and pass `modelDir`.

## Usage

```ts
import { sanitize, restore, wrapForLLM } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about SSN 123-45-6789');
// safe.sanitized: 'Email {{PII_PRIVATE_PERSON_0}} at {{PII_PRIVATE_EMAIL_0}} about SSN {{PII_ACCOUNT_NUMBER_0}}'
// safe.sessionId: opaque session id
// safe.spans:     PiiSpan[] in document order

// Optional: prefix the LLM prompt with a built-in preservation hint
// (saturates round-trip preservation to ~100% across translate /
// summarise / rewrite / json / markdown tasks; ~80 prompt-token cost
// once, break-even at ~5 placeholders). Pass to any LLM as the user
// message.
const prompt = wrapForLLM(safe, 'Translate to Italian');

// Or pass safe.sanitized directly to any LLM …
const reply = 'Hello {{PII_PRIVATE_PERSON_0}}, we received your request.';

const back = restore(reply, safe.sessionId);
// back.restored: 'Hello John Smith, we received your request.'
```

> **Placeholder format**: Mustache template variables `{{PII_<TYPE>_<N>}}`. LLMs are deeply trained on this convention (Anthropic prompts / LangChain `PromptTemplate` / Jinja2 / Handlebars / Vue / Django) and preserve it verbatim across most task scenarios — see `packages/eval/private/PLACEHOLDER_FORMAT_ANALYSIS.md` for the empirical study (token cost + round-trip preservation across 6 candidate formats × 6 task scenarios). Use `wrapForLLM()` to add an explicit hint when feeding adversarial / rewrite-style prompts.

Programmatic API:

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });
const { sessionId, sanitized, spans } = await np.sanitize(text);
// … LLM call uses `sanitized` …
const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

CLI:

```bash
npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
```

## What gets caught (9 categories)

| Label             | Examples                                          | Source                  |
| ----------------- | ------------------------------------------------- | ----------------------- |
| `private_person`  | personal names (first / last / middle, prefixes)  | ML model                |
| `private_email`   | email addresses                                   | ML + regex (`core:email`) |
| `private_phone`   | phone / fax numbers                               | ML + regex (intl / domestic IT/FR/ES) |
| `private_address` | street addresses, cities, GPE, ZIP                | ML model                |
| `private_date`    | birth / hire dates                                | ML model                |
| `private_url`     | private URLs (admin panels, internal wikis)       | ML + regex (`core:url`) |
| `private_ip`      | IPv4, IPv6 addresses                              | regex pack only (post-pass) |
| `private_mac`     | MAC / Ethernet hardware addresses                 | regex pack only (post-pass) |
| `account_number`  | bank accounts (IBAN mod-97), SSN, credit cards (Luhn), MRN, customer IDs, BTC / ETH addresses, national IDs (DNI, CPF, CF, EIN) | ML + regex (validated where possible) |
| `secret`          | API keys (AWS / GitHub / OpenAI / Anthropic / Stripe / Slack / Linear / etc.), JWT, PEM private-key blocks, base64-wrapped PII | regex pack (50+ patterns) + base64 decoder |

> **Why 10 categories?** Microsoft Presidio ships ~20 entity types (and 30+ optional recognizers). NVIDIA Nemotron-PII trains on 55 fine-grained classes (`first_name` vs `last_name`, `mrn` vs `health_plan_beneficiary_number`, etc.). nullpii inherits the 8-class schema of its [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) backbone (the ML model emits 8) and adds two regex-only post-pass labels — `private_ip` (IPv4 / IPv6) and `private_mac` (MAC) — for shapes the model is not trained on.
>
> Rationale: distinguishing `first_name` vs `last_name` doesn't matter when **redacting** — both end up as `{{PII_PRIVATE_PERSON_0}}`. SSN / IBAN / credit-card all collapse to `account_number` because you mask them the same way. Granular schemas are useful as training signal (Nemotron's 55-class fine-tune learns finer distinctions); broad schemas are easier downstream (one placeholder type per category, simpler restore mapping). Different targets.
>
> Bench-side: Presidio / Nemotron / DeBERTa native predictions are remapped to nullpii's 8-class **before** the F1 comparison so cross-tool bench is fair (see "Benchmarks" below). Symmetric — every cross-schema NER bench needs the bridge.

Add custom regex recognizers as a post-pass for known formats with low ML coverage:

```ts
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

## Backends

Single unified ONNX session loaded via [`onnxruntime-node`](https://www.npmjs.com/package/onnxruntime-node). Pass `backend` in `NullPiiConfig` to pick the execution-provider ladder:

| `backend` | ORT execution providers, in order            | Platform             |
| --------- | -------------------------------------------- | -------------------- |
| `'cpu'`   | `['cpu']`                                    | Universal default    |
| `'cuda'`  | `['cuda', 'cpu']` (fallback on CPU if absent)| Linux / Windows + NVIDIA |
| `'mps'`   | `['coreml', 'cpu']` (fallback on CPU)        | macOS Apple Silicon  |
| `'auto'`  | currently equivalent to `'cpu'`              | All                  |

Optional `intraOpNumThreads` / `interOpNumThreads` are forwarded to ORT session options (`0` = ORT default).

## Known limitations

What the library does **not** detect today. None of these are bugs — they are scope decisions. Calling them out so adopters can layer the right extra controls on top.

- **Biometric / genetic identifiers** (GDPR Art. 9 "special categories", HIPAA #15-#18). No detector for fingerprints, retina scans, voiceprints, DNA / RNA sequences, gait, facial geometry, or any structured representation of those. The schema has no class for them and the unified GLiNER was not trained to recognise them. If you handle biometric data, add a domain-specific pipeline upstream of nullpii.
- **Free-text medical content** beyond named MRN-shaped tokens. `account_number` matches IBAN-/SSN-/CC-/MRN-shaped digit runs by regex, but the library is **not** a HIPAA de-identifier. It will not redact diagnoses, ICD codes in prose, procedure descriptions, medication dosages, lab values, or implied health attributes (e.g. "the patient on dialysis"). For clinical text use Presidio + a medical entity stack (cTAKES, MedSpaCy) and treat nullpii as a thin extra layer for the obvious identifiers.
- **`private_ip` / `private_mac` are regex-only**. The unified GLiNER model is not trained to emit IPs or MAC addresses; the post-pass regex pack catches IPv4 / IPv6 under `private_ip` and 6-octet MAC addresses under `private_mac`. The never-PII filter drops RFC1918 / RFC5737 / loopback / link-local / multicast / IPv6 docs / IPv6 link-local (for IPs) and all-zero MACs. IPs embedded inside obfuscated text (zero-width separators, base64-wrapped) still depend on the adversarial preprocessor catching them.
- **Behavioural / quasi-identifiers**. Browser fingerprints, device IDs that aren't in the recognizer pack, location traces, login timestamps, social-graph edges. Out of scope.
- **Vendor-specific account-number formats** not in the regex pack (e.g. country-specific tax IDs beyond DNI / CPF / CF / EIN). Register a custom recognizer via `np.addRecognizer(...)` if you handle them.
- **Inputs > 1 MB**. `normalize.ts` and `recognizers.ts` refuse to scan past 1 MB to avoid quadratic regex behaviour on adversarial padding. Chunk the input upstream.
- **Detection is best-effort.** No detector is perfect. Treat nullpii as defence in depth, not the sole privacy control.

If you need a category that isn't in the schema, add a custom recognizer for known patterns (regex post-pass) — the runtime treats recognizer hits with `confidence ≥ 0.9` as authoritative over the ML model.

## Privacy guarantees

- Detection runs **entirely local** — never touches the network.
- Vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping.
- Logs never contain PII (counts and short ids only).
- See [SECURITY.md](SECURITY.md) for the threat model and how to report a vulnerability.

## Bench methodology

Numbers above come from `packages/eval/scripts/bench_full.py` against the 10 canonical datasets, Mac M-series CPU, single seed.

**Bare-mode contract** — zero nullpii post-processing on competitor rows: no `_normalize_for_detection`, no boundary refine, no never-PII filter, no regex pack. The only adapter glue is the universal NER-bench plumbing applied identically to every tool:

- **Chunking 1400/200 char stride** — every ML tool has a ~512-token context limit, so documents like TAB ECHR (avg 2000+ tokens) must be split + dedupe. Same code path on every tool, including the nullpii row.
- **Per-tool label remap** to nullpii's 8-class schema — Microsoft Presidio emits `PERSON` / `EMAIL_ADDRESS` / `LOCATION`, NVIDIA Nemotron emits 55 fine-grained labels (`first_name`, `ssn`, `mrn`, …), Microsoft DeBERTa fine-tune emits `PER` / `LOC` / `ORG`. Bench predictor wrappers translate those native labels to nullpii's 8-class **before** F1 comparison. Symmetric — every cross-tool NER bench needs it; not a nullpii advantage.

The `CLAIM-VERIFIER-01` finding (vendor F1 numbers 0.85+/0.99+ not reproducible with span IoU ≥ 0.5 + standard methodology) is exercised by `packages/eval/scripts/verify_claims.py`.

Reproduce — `bench_full.py --tools nullpii,deberta,piiranha,presidio,gliner-pii-large-v1,nemotron-pii-raw --backend cpu --datasets all --confusion`.

## Documentation

### Top-level

- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup + architecture rules
- [`SECURITY.md`](SECURITY.md) — threat model + vuln reporting

### Model card

Lives on HuggingFace Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — training data composition, intended use, limitations, in-distribution disclosures.

### Eval kit

- [`packages/eval/README.md`](packages/eval/README.md) — bench harness + scripts inventory
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset cards + licenses

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); verified by `npm run license-check` in CI.

The **model weights** on HuggingFace are a separate artifact with a separate licence — they are *not* covered by this repo's Apache-2.0 and are *not* bundled in the npm package (fetched on first use). v0.2 is trained on a permissive-only corpus; legal attributions live in [NOTICE](NOTICE) and the `lBroth/nullpii` model card.

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization with reversible vault.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, Zaratiana et al. NAACL 2024). Per-domain LoRA adapter training data composition + recipe: see the HF model card.
