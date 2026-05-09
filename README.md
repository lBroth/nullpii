<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with reversible in-memory vault. ML span detection swaps PII with placeholders; pass the sanitized text anywhere (LLM, log, third-party API), then restore original values from the response.

## Why this exists

Honest framing: this is a **night-hobby project**, not a production-ready PII tool, not a research paper, not a commercial product.

Since I started using Claude Code I stopped playing video games — it became my night toy. nullpii is what fell out of those nights: a chance to learn the GLiNER + LoRA + router stack end-to-end, run it under a strict bench harness, write the honest audit on what works and what doesn't, and ship something that does the round-trip cleanly.

What's interesting here is the engineering rigor + adversarial preprocessor, not state-of-the-art F1.

> **Status (2026-05-06)** — first release `v0.1.0`. Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, ~278M params). Shipping pipeline: **Google distiluse** sentence encoder + 5 per-domain LoRA adapters merged into the GLiNER backbone (~6 GB total artifacts). The npm runtime downloads the full router stack from HF on first call.

## Bench at a glance

MacBook Pro M5 Pro CPU, 8-dataset canonical surface (macro), macro F1 at IoU ≥ 0.5 (partial-match span scoring), `--parallel-tools 1` fair-serial, cap=5000 per dataset. `nullpii` = npm subprocess (what `npm i nullpii` runs — model + recognizer pack + boundary refinement + never-PII filter); other columns = bare third-party baselines (no nullpii post-processing leak — see [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) for the bare-mode contract). Full matrix: [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

> **Honest disclosure**: F1 below reflects the full npm runtime. The `lBroth/nullpii` HF model alone (without the npm regex pack / boundary / never-PII filter) scores **~0.04 lower** on average — the [HF model card](https://huggingface.co/lBroth/nullpii) publishes both `model-only` and `full runtime` columns explicitly.

`nullpii-bench` is the unified project corpus (2 421 rows: bundled OOD + long-prompts + 6 self-authored preprocessor-regression subsets + 5 TextAttack perturbation slices) — single F1 number summarises behaviour across every adversarial pattern we author. Multilingual coverage via held-out isotonic in en + de + fr + it.

| Dataset | n | **`nullpii`** | `presidio` | `nemotron-pii-raw` | `piiranha` | `deberta` | `gliner-onnx-pii-fp32` | `gliner-pii-large-v1` |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `tab-echr` ⚠ | 127 | **0.9170** | 0.4657 | 0.4521 | 0.1704 | 0.1745 | 0.2172 | 0.1002 |
| `isotonic-de-heldout` | 5 000 | **0.8756** | 0.4047 | 0.7040 | 0.5642 | 0.4934 | 0.5470 | 0.5827 |
| `isotonic-it-heldout` | 5 000 | **0.8687** | 0.4133 | 0.6925 | 0.5660 | 0.5367 | 0.5444 | 0.5721 |
| `isotonic-en-heldout` | 5 000 | **0.8685** | 0.4726 | 0.7281 | 0.5660 | 0.7512 | 0.5458 | 0.5838 |
| `isotonic-fr-heldout` | 5 000 | **0.8625** | 0.4129 | 0.6970 | 0.5694 | 0.5738 | 0.5512 | 0.5676 |
| `nullpii-bench` ⚠ self-authored | 2 421 | **0.7622** | 0.2303 | 0.4684 | 0.2426 | 0.3070 | 0.2855 | 0.2755 |
| `nemotron-pii-test` ⚠ | 5 000 | 0.7227 | 0.5222 | **0.8997** ‡ | 0.4875 | 0.5789 | 0.4924 | 0.5376 |
| `presidio-synthetic` | 5 000 | 0.6050 | 0.5737 § | 0.6184 | 0.3819 | 0.4453 | 0.5360 | **0.6323** † |
| `ai4privacy-300k-heldout` | 5 000 | **0.5170** | 0.2099 | 0.3688 | 0.2610 | 0.1586 | 0.2032 | 0.1352 |
| **Mixed (8)** ¶ | — | **0.7846** | 0.3979 | 0.5912 | 0.4152 | 0.4301 | 0.4288 | 0.4312 |
| **Held-out OOD multilingual (6)** | — | **0.7662** | 0.4145 | 0.6348 | 0.4847 | 0.4932 | 0.4879 | 0.5123 |
| **In-distribution diagnostic (2)** | — | **0.8396** | 0.3480 | 0.4602 | 0.2065 | 0.2407 | 0.2513 | 0.1879 |

**nullpii wins 7 of 8 macro datasets**. Loss: `presidio-synthetic` to `gliner-pii-large-v1` by 0.027. `nemotron-pii-test` ⚠ excluded from macro (enterprise adapter in-distribution + self-bench for `nemotron-pii-raw`). **Mixed F1 +0.19 over next-best baseline (`nemotron-pii-raw` 0.5912)**.

Bucket interpretation:
- **Held-out OOD multilingual (6)** — model never saw these rows during training: `presidio-synthetic`, `ai4privacy-300k-heldout`, `isotonic-{en,de,fr,it}-heldout`. Real generalisation across 4 languages.
- **In-distribution diagnostic (2)** — adapters trained on slices of these datasets (`nullpii-bench` ⚠ self-authored, `tab-echr`). F1 is memorisation + preprocessor regression, not generalisation. `nullpii-bench` mixes bundled OOD + 6 preprocessor-regression subsets + 5 TextAttack slices in one cell — single number summarises adversarial-pattern resistance. `nemotron-pii-test` ⚠ shown in table but **excluded from all macro rows** — enterprise adapter is in-distribution and the row is simultaneously a self-bench for `nemotron-pii-raw`.

Legend:
- **bold** = best of the row
- ⚠ = in-distribution row (see bucket above)
- ⚠ self-authored = both perturbation generator and preprocessor authored by this project; treat as regression test, not generalisation claim
- ¶ `nemotron-pii-test` row shown for reference but excluded from all **Mixed** / **In-distribution** macro aggregates (double disqualification: enterprise adapter in-distribution + simultaneous self-bench for `nemotron-pii-raw`)
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

7 tools × 9 datasets (cap 5 000 per dataset), `--parallel-tools 1` (no CPU sharing). Same hardware as above. Throughput aggregated as `Σ n / Σ wall_s` across all 9 dataset cells per tool. **mixed F1 = 8-dataset macro** (nemotron-pii-test excluded from F1 aggregate, included in wall-time total).

| Tool | mixed F1 | total samples | wall (s) | samp/s |
|---|---:|---:|---:|---:|
| `presidio` | 0.3979 | 37 548 | 237.0 | **158.4** |
| `gliner-onnx-pii-fp32` | 0.4288 | 37 548 | 1 022.8 | 36.7 |
| **`nullpii`** | **0.7846** | 37 548 | 1 398.1 | 26.9 |
| `deberta` | 0.4301 | 37 548 | 1 564.6 | 24.0 |
| `piiranha` | 0.4152 | 37 548 | 1 661.1 | 22.6 |
| `gliner-pii-large-v1` | 0.4312 | 37 548 | 6 737.6 | 5.6 |
| `nemotron-pii-raw` | 0.5912 | 37 548 | 8 079.6 | 4.6 |

`presidio` (regex/SpaCy) tops throughput at lowest F1. `nullpii` runs the full distiluse + GLiNER + 5-LoRA stack and lands in the top tier on throughput while topping F1 by **+0.19** over the next-best tool (`nemotron-pii-raw`). Source: `packages/eval/published-bench/matrix.json`.

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an optional peer dependency (CPU / MPS / CUDA backend). Requires Node 24 LTS (see `.nvmrc`).

> **First-call download**: the first `sanitize()` invocation downloads ~6 GB of model artifacts from HuggingFace Hub ([`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes) into `~/.cache/nullpii/` (or `$XDG_CACHE_HOME/nullpii/`). One-shot; subsequent calls hit the local cache. Plan accordingly for air-gapped installs (mirror the HF repo locally and pass `modelDir`).

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

## What gets caught (8 categories)

| Label             | Examples                                          |
| ----------------- | ------------------------------------------------- |
| `private_person`  | personal names (first / last / middle, prefixes)  |
| `private_email`   | email addresses                                   |
| `private_phone`   | phone / fax numbers                               |
| `private_address` | street addresses, cities, GPE, ZIP                |
| `private_date`    | birth / hire dates                                |
| `private_url`     | private URLs (admin panels, internal wikis)       |
| `account_number`  | bank accounts, IBAN, SSN, credit cards, MRN, customer IDs |
| `secret`          | API keys, tokens, passwords, JWT, PEM private keys |

> **Why only 8 categories?** Microsoft Presidio ships ~20 entity types (and 30+ optional recognizers). NVIDIA Nemotron-PII trains on 55 fine-grained classes (`first_name` vs `last_name`, `mrn` vs `health_plan_beneficiary_number`, etc.). nullpii inherits the 8-class schema of its [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) backbone and keeps it.
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

| Backend | Platform                | Notes                                  |
| ------- | ----------------------- | -------------------------------------- |
| `cpu`   | All                     | Universal; fast on Apple Silicon       |
| `mps`   | macOS Apple Silicon     | CoreML EP, partial op coverage         |
| `cuda`  | Linux / Windows + NVIDIA | CUDA EP via `onnxruntime-node`        |

Auto-selects in priority **CUDA → MPS → CPU**.

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

The `CLAIM-VERIFIER-01` finding (vendor F1 numbers 0.85+/0.99+ not reproducible with span IoU ≥ 0.5 + standard methodology) is documented in [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md).

Reproduce — `bench_full.py --tools nullpii,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1 --datasets <canonical 10> --backend cpu`.

## Documentation

### Top-level

- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — bench methodology + competitor landscape
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

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization with reversible vault.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, Zaratiana et al. NAACL 2024). Per-domain LoRA adapter training data composition + recipe: see the HF model card.
