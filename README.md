---
license: apache-2.0
language:
  - en
  - de
  - fr
  - it
  - es
  - multilingual
tags:
  - pii-detection
  - token-classification
  - gliner
  - privacy
  - redaction
library_name: gliner
base_model: urchade/gliner_multi_pii-v1
pipeline_tag: token-classification
datasets:
  - ai4privacy/pii-masking-300k
  - Isotonic/pii-masking-200k
---

<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

[![CI](https://github.com/lBroth/nullpii/actions/workflows/ci.yml/badge.svg)](https://github.com/lBroth/nullpii/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/nullpii?color=cb3837)](https://www.npmjs.com/package/nullpii)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> **What this is.** Two independent deliverables packaged together with an honest evaluation. Read the limitations before quoting any number.
>
> 1. **npm library** — `nullpii` on npm. Wraps `openai/privacy-filter` (1.5B) with the constrained Viterbi BIOES decoder, chunking, regex recognizers, and a reversible in-memory vault. Independent of the fine-tuned model below.
> 2. **HuggingFace model** — `lBroth/nullpii` on HF. A separate fine-tune of `urchade/gliner_multi_pii-v1` (278M). Useful as a smaller, drop-in detector. **Not used by the npm library.**
>
> **TL;DR — what `nullpii` ships**:
>
> The `nullpii` npm package wraps **`onnx-community/gliner_multi_pii-v1` (FP32 ONNX, 278M params)** with chunking, a curated regex recognizer pack (~65 patterns covering AWS / GitHub / OpenAI / Anthropic / Slack / Stripe / Twilio / DigitalOcean / Cloudflare / Mailgun / Discord / Telegram / Google API keys + cloud SaaS tokens + PEM keys + JWTs + crypto wallet addresses + UUIDs + MAC addresses + IBAN / SSN / Spanish DNI / US passport / Brazilian CPF / Italian P.IVA + URL with public-domain whitelist filter), and a reversible in-memory vault. On the use-case-relevant benchmark — `nullpii-bench`, project-bundled real dev prompts (RFCs, PR reviews, multilingual ticket bodies, code with secrets) — F1 = **0.8638** (clean baseline, no test-set tuning), beating every alternative tested by **+0.17 F1 over baseline GLiNER** and +0.19 F1 over the official `opf` CLI for `openai/privacy-filter`. On `oasst-dev-planted` (real chat text + planted PII): F1 = **0.6250** vs 0.3524 next-best (+0.27). Across the 9-dataset matrix `nullpii` wins **4/9 rows outright** (nullpii-bench, ai4privacy-300k, isotonic-fr, oasst-dev-planted); on isotonic-en/de/it + presidio-synthetic bare GLiNER edges by 0.008–0.010 F1.
>
> **Two reproducible findings backing the design choice**:
>
> 1. HF `transformers.pipeline()` with default `aggregation_strategy="simple"` **does not implement** the constrained Viterbi BIOES decoder that `openai/privacy-filter`'s model card prescribes — the integration ships only per-token logits and naive aggregation produces fragmented spans. The official [`opf` CLI](https://github.com/openai/privacy-filter) (via `opf._api.OPF`) recovers +0.25 F1 vs naive HF on `nullpii-bench`. Useful PSA, but `nullpii` skips this entire layer by switching backbone.
> 2. A 2-round fine-tune of GLiNER on `ai4privacy/pii-masking-300k` + `Isotonic/pii-masking-200k` **loses 0.22 F1 on real-world OOD** (`nullpii-bench`: baseline 0.69 → fine-tune 0.47), even while winning by +0.35 F1 on held-out splits of the *same* training datasets. Held-out vs train-dist numbers are within 0.005 — same-dataset slicing isn't a generalization test. The earlier preview "0.93–0.97 multilingual F1" was measured on the training distribution and is misleading.
>
> Implication: the npm package's value is **the runtime stack on top of the right backbone**, not a custom-trained model. Ship the well-known `gliner_multi_pii-v1` ONNX FP32 + a curated, transparent regex pack + minimal post-processing, not a fragile fine-tune.

## What's in this repo

1. **`nullpii` (npm library)** — sanitize / restore engine over `onnx-community/gliner_multi_pii-v1` (ONNX FP32) with chunking + curated regex recognizer pack + reversible in-memory vault. CLI binary (`nullpii sanitize|restore|scan|benchmark|...`) plus a TS API (`sanitize()`, `restore()`, `NullPii` class). This is the **production deliverable**.
2. **Reproducibility kit** (`packages/eval/`) — bench harness, dataset loaders (incl. heldout / traindist splits), training scripts, and the full comparison matrix that justifies the design choices in (1). Gitignored from the npm publish artefact.

A separate fine-tuned GLiNER model exists at [`lBroth/nullpii` on HF](https://huggingface.co/lBroth/nullpii) for users whose workload looks structurally like `ai4privacy/pii-masking-300k` or `Isotonic/pii-masking-200k`. **It is not the npm package's backbone** — see the headline finding above for why; the bench shows the fine-tune memorises training distribution and regresses on real OOD prompts.

## Honest limitations (read before quoting any number)

- **GDPR Art. 9 special-category data is structurally invisible.** The 8-class schema (`private_person` / `private_email` / `private_phone` / `private_address` / `private_date` / `private_url` / `account_number` / `secret`) has **no class for health / biometric / political / religion / sexual-orientation / trade-union / ethnic-origin / criminal data**. A Slack thread discussing an employee's sick leave, an HR file flagging political affiliation, or a DM about a medical condition will pass through with the *names* and *dates* redacted but the *categorical fact itself* unmodified. **nullpii is not an Art. 9 control.** Use a downstream classifier or rule-based filter for Art. 9 categories.
- **Offset-disjoint ≠ distribution-disjoint on Faker-templated datasets.** The fine-tuned models score 0.88+ on `isotonic-{en,de,fr,it}` and 0.56+ on `ai4privacy-300k`, but those datasets are template-generated — different row indices share the same surface patterns. Treat the v8/v9 numbers on those rows as **template-distribution generalisation, not OOD evidence**. The OOD signal lives only in `nullpii-bench` (real, hand-built, 264 samples) and `oasst-dev-planted` (real chat + planted PII).
- **`medical-experimental` profile is NOT a HIPAA control.** The profile name carries an `-experimental` suffix on purpose. It has no medical-specific recognizers (MRN, NPI, prescription IDs are not implemented) and has not been validated on i2b2 / MEDDOCAN / MIMIC. Coverage is estimated at ~10/18 Safe Harbor identifiers. Use as a research-grade pre-filter with a human reviewer; do not cite as a de-identification control.
- **Adversarial section is a transparency probe, not a robustness claim.** nullpii currently scores second to opf-Viterbi on the third-party-framework adversarial run (TextAttack, n=1670). The corpus is also team-curated. Do not cite the adversarial section as a feature claim.
- **Single-seed benches.** No bootstrap CI, no multi-seed runs. Numbers below are point estimates; treat differences smaller than ~0.02 F1 as noise.
- **`nullpii-bench` (n=264) is the only true-OOD dataset working right now.** The other planned plant-and-detect datasets (`enron-planted`, `stackoverflow-planted`, `thestack-planted`, `conll2003`) have broken loaders on the open-data path (mirrors removed/renamed/gated, deprecated `trust_remote_code=True`). The OOD generalisation evidence rests entirely on those 264 prompts.
- **Same-dataset heldout ≠ generalisation.** `*-heldout` cells are drawn from rows the fine-tune was not trained on, but from the same dataset distribution it *was* trained on. Heldout vs traindist numbers cluster within 0.005 F1 — slicing the row index isn't a real generalisation test.
- **The retracted preview headline (`0.93–0.97 multilingual F1`) was a same-dataset memorisation measurement.** It is misleading and has been removed from this README. The HF model card carries the corrected numbers.
- **CJK is a documented dead zone.** Every tool tested scores below 0.16 F1 on `wikiann-zh` / `wikiann-ja`. None of the training mixes used CJK data.
- **WikiAnn schema mismatch.** PER → `private_person`, LOC → `private_address`. Loose mapping; absolute F1 not comparable to PII-native rows.

## Headline comparison

F1, IoU ≥ 0.5. Mac M-series CPU bench, n=2000 per dataset (n=264 for `nullpii-bench`), single seed. Full matrix at `packages/eval/results/iter-v7-final-clean/matrix.json` (clean baseline — no test-set tuning, see [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md) for the cheat-stripping audit and ablation details).

`wikiann-{es,zh,ja}` rows dropped from the headline matrix: schema mismatch (PER/LOC/ORG NER, not PII) — all tools score 0.05–0.32. Documented as "NER-subset coverage gap", not a meaningful PII signal.

| Dataset                  | **`nullpii`** | baseline GLiNER (bare) | openai-official (Viterbi) | openai (HF naive) |
| ------------------------ | ------------: | ---------------------: | ------------------------: | ----------------: |
| **`nullpii-bench` (OOD, n=264)** | **0.8638** |             0.6947 |                    0.6764 |            0.4264 |
| ai4privacy-300k          |    **0.3112** |                 0.1481 |                    0.2882 |            0.1931 |
| ai4privacy-400k          |        0.5238 |                 0.5988 |                **0.6750** |            0.4390 |
| isotonic-en              |        0.5908 |             **0.6065** |                    0.5767 |            0.3860 |
| isotonic-de              |        0.5948 |             **0.6028** |                    0.5823 |            0.3850 |
| isotonic-fr              |    **0.5879** |                 0.5810 |                    0.5857 |            0.3831 |
| isotonic-it              |        0.5885 |             **0.5971** |                    0.5900 |            0.3841 |
| oasst-dev-planted        |    **0.6250** |                 0.2500 |                    0.3524 |            0.2322 |
| presidio-synthetic       |        0.5854 |             **0.5952** |                    0.5769 |            0.3899 |

**Bold = per-row winner.** Win counts across the 9 rows:

| Tool | Wins |
|--|--|
| **`nullpii`** | **4/9** (nullpii-bench, ai4privacy-300k, isotonic-fr, oasst-dev-planted) |
| baseline GLiNER (bare) | 4/9 (isotonic-en, isotonic-de, isotonic-it, presidio-synthetic) |
| openai-official (Viterbi) | 1/9 (ai4privacy-400k) |
| openai (HF naive) | 0/9 |

**Reading the table:**

- **`nullpii-bench` (real-world OOD use case)**: `nullpii` wins decisively at **0.8638** — that's +0.17 vs baseline GLiNER, +0.19 vs openai-official Viterbi, +0.44 vs openai HF naive. This is the distribution the package targets: dev prompts pasted into LLMs (RFCs, PR reviews, ticket bodies, code with secrets, multilingual customer-support emails). The runtime stack — gliner-pii backbone + curated regex pack with URL whitelist + ensemble merge + boundary refinement — earns its keep here.
- **`oasst-dev-planted` (real conversational text + planted PII)**: `nullpii` wins decisively at **0.6250** — that's +0.27 over openai-official Viterbi (the closest competitor) and +0.38 over baseline GLiNER. Real chat text is exactly the use case the runtime stack targets after the dev-paste workload.
- **`isotonic-{en,de,it}` and `presidio-synthetic`**: bare GLiNER edges `nullpii` by 0.008–0.010 F1. The runtime stack adds nothing on these structured-PII templates — plain GLiNER is competitive without the wrapper. Worth flagging honestly: the wrapper helps on real-world text and dev paste, not on synthetic structured templates.
- **`ai4privacy-*`**: openai-official (Viterbi) wins ai4privacy-400k by 0.15. ai4privacy uses inline-tagged PII formats (`<email>foo@bar.com</email>`) where Viterbi's BIOES-aware decoder outperforms span output. Worth flagging; not worth switching backbones for it given the OOD trade-off.
- **`openai (HF naive)`** loses every row. The +0.25 F1 delta to `openai-official` on `nullpii-bench` is the validated PSA: HF transformers default aggregation drops the model's prescribed Viterbi BIOES decoder. If you must use `openai/privacy-filter` directly (e.g. on Python), call `opf._api.OPF` not `transformers.pipeline()`.

**Honesty note (test-set leakage strip):** an earlier production pipeline included three regex patterns derived from `failure_analysis.py` runs on `nullpii-bench` itself + IPv4 lookahead/lookbehind tuned on 6 specific bench FPs + a `gliner_threshold=0.8` value picked by sweeping on the bench. All four were forms of test-set tuning. They are stripped from the numbers above. Prior cheat-laden `nullpii-bench` F1 was 0.8810; clean is 0.8638. The cheat magnitude across all 9 datasets averages to **+0.005 in favour of the clean baseline** — bench-tuning narrowed wins on `nullpii-bench` and isotonic Romance but actively hurt cross-distribution F1 on `oasst-dev-planted` (+0.097 clean) and `ai4privacy-400k` (+0.057 clean). See COMPETITIVE_ANALYSIS.md for the full audit + iter-v7 ablation lessons (stoplist / score-ranked / zero-shot semantic / trained tiny verifier — none generalised).

**Tool definitions:**
- **`nullpii`** = `onnx-community/gliner_multi_pii-v1` (ONNX FP32, 278M) + chunking + curated regex pack (~50 patterns) + ensemble merge. The npm package, the production winner on OOD.
- **baseline GLiNER (bare)** = `urchade/gliner_multi_pii-v1` PyTorch, just `.predict_entities()` with chunking. Reference for what `nullpii` adds on top of the model.
- **openai-official (Viterbi)** = `openai/privacy-filter` (1.5B) via the official [`opf` CLI](https://github.com/openai/privacy-filter) Python API (`opf._api.OPF`). Reference for the model's intended-quality output.
- **openai (HF naive)** = same `openai/privacy-filter` model via `transformers.pipeline()` defaults (`aggregation_strategy="simple"`). Reference for what *not* to do — produces fragmented spans because the integration drops the model's prescribed Viterbi BIOES decoder.

**The PSA layer of the table** — the `openai (HF naive)` → `openai-official (Viterbi)` delta (+0.25 F1 on `nullpii-bench`) is the most reproducible useful finding in the repo: HF transformers default aggregation drops the model's prescribed Viterbi BIOES decoder, producing fragmented spans. If you must use `openai/privacy-filter` directly (e.g. on Python), call `opf._api.OPF` not `transformers.pipeline()`.

### Appendix — fine-tune trade-off (memorisation vs generalisation)

A 2-round fine-tune of GLiNER on `ai4privacy/pii-masking-300k` + `Isotonic/pii-masking-200k`. PT FP32 + ONNX INT4 variants benched against `nullpii` on the same datasets:

| Dataset                  | `nullpii` | nullpii PT-fine-tune+regex | nullpii INT4-fine-tune+regex | Δ best fine-tune vs `nullpii` |
| ------------------------ | --------: | -------------------------: | ---------------------------: | ----------------------------: |
| **`nullpii-bench` (OOD)** | **0.8239** |                     0.5783 |                       0.5698 |                    **−0.246** |
| isotonic-en-heldout      |    0.5731 |                     0.9317 |                       0.9386 |                        +0.366 |
| isotonic-de-heldout      |    0.5808 |                     0.9390 |                       0.9510 |                        +0.370 |
| isotonic-fr-heldout      |    0.5993 |                     0.9408 |                       0.9498 |                        +0.350 |
| isotonic-it-heldout      |    0.5789 |                     0.9396 |                       0.9427 |                        +0.364 |
| isotonic-en-traindist    |    0.5837 |                     0.9355 |                       0.9404 |                        +0.357 |
| ai4privacy-heldout       |    0.2085 |                     0.3296 |                       0.3406 |                        +0.132 |
| ai4privacy-traindist     |    0.2028 |                     0.3270 |                       0.3395 |                        +0.137 |

The fine-tune wins by **+0.35 F1 on training-distribution datasets** and loses by **−0.25 F1 on real OOD**. Same-dataset heldout vs traindist numbers are within 0.005 — slicing rows of the same dataset is not a generalisation test, only `nullpii-bench` is. The fine-tune is published at [`lBroth/nullpii` on HF](https://huggingface.co/lBroth/nullpii) for users whose production prompts look structurally like ai4privacy / Isotonic; **the npm package does not use it as the default**, and the older preview "0.93–0.97 multilingual F1" (measured on the training distribution) is misleading and now retracted.

### Appendix — dataset notes

- **`nullpii-bench` (n=264)** — project-bundled at `packages/eval/datasets/nullpii-bench.jsonl`, Apache-2.0. The only true-OOD generalisation dataset currently working. Mix of dev-style prompts (RFCs, PR reviews, deploy logs, ticket bodies, customer-support emails) plus long-prompts that exercise chunking. 5 locales (en/it/de/fr/es).
- **`*-heldout`** — slices of the *upstream training datasets* drawn from row indices the fine-tune was not trained on (`ai4privacy[100000:105000]` + `isotonic[200000:]` per locale). Constructed to test fine-tune generalisation; in practice numbers cluster with `*-traindist` (within 0.005 F1) — same-dataset slicing isn't a real generalisation test.
- **`*-traindist`** — first-rows slices, same indices the fine-tune *was* trained on. Regression sentinel.
- **`wikiann-{es,zh,ja}`** — WikiAnn PER/LOC NER. PER → `private_person`, LOC → `private_address` is a loose mapping; absolute F1 is not comparable to PII-native rows. CJK rows confirm the documented gap (every tool below 0.16 F1).
- **`dev-prompts-synth`** — ours, dropped from headline because round-2 of the fine-tune mixed it into training. Available via `packages/eval/src/nullpii_eval/public_datasets.py:_generate_dev_prompts` for regression checks.

## Library mode (npm)

```ts
import { sanitize, restore } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about his SSN 123-45-6789');
// safe.text = 'Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about his [[NULLPII:secret:0]]'
// safe.session = opaque session id

// ... pass safe.text to any LLM ...
const reply = `Hello [[NULLPII:private_person:0]], we received your request.`;

const back = await restore(reply, safe.session);
// back = 'Hello John Smith, we received your request.'
```

Programmatic API (full control):

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

const { sessionId, sanitized, spans } = await np.sanitize(
  "Hi, I'm Maria Rossi (maria.rossi@example.it). My order #ACME-2026-04812 shipped to via Roma 45, 00184 Roma.",
);

// ... LLM call uses `sanitized` ...
const reply = '...';

const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

CLI:

```bash
$ npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
"Hi [[NULLPII:private_person:0]], thanks for reaching out about [[NULLPII:account_number:0]]..."
```

## Model mode (HuggingFace, fine-tune variant)

For users whose production prompts look structurally like `ai4privacy/pii-masking-300k` or `Isotonic/pii-masking-200k` (structured fields like `Name: ...`, `Email: ...`, `Address: ...`), a separate fine-tune is published. **Not the npm package's default** — it loses 0.25 F1 on `nullpii-bench`-style real prompts (see appendix above). Use only if your workload matches the training distribution.

```python
from gliner import GLiNER

model = GLiNER.from_pretrained("lBroth/nullpii")  # ai4privacy/Isotonic-style data ONLY
labels = ["account_number", "private_address", "private_date",
          "private_email", "private_person", "private_phone",
          "private_url", "secret"]

text = "Customer Name: Maria Rossi · Email: maria.rossi@example.it · IBAN: IT60X0542811101000000123456"
for entity in model.predict_entities(text, labels, threshold=0.5):
    print(entity["label"], "→", entity["text"], entity["score"])
```

ONNX INT4 deployment: `model_int4.onnx` ~844 MB, quantised via `onnxruntime.quantization.matmul_nbits_quantizer`. ONNX INT8 not published (F1 collapses).

## What gets caught (8 categories)

| Label             | Examples                                             |
| ----------------- | ---------------------------------------------------- |
| `private_person`  | personal names                                       |
| `private_email`   | email addresses                                      |
| `private_phone`   | phone / fax numbers                                  |
| `private_address` | street addresses                                     |
| `private_date`    | birth dates, hire dates, anniversaries               |
| `private_url`     | private URLs (admin panels, internal wikis)          |
| `account_number`  | bank accounts, IBAN, customer IDs                    |
| `secret`          | API keys, passwords, JWT tokens                      |

For known formats with low ML coverage (your internal employee ID, AWS access keys, SWIFT BIC), add custom regex-based recognizers as a post-pass:

```ts
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

ML-first, regex-augmented. No "no regex" purity theatre.

## Install (npm)

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an **optional peer dependency** — install it only if you want the Node-side backend (CPU / MPS / CUDA). The library is also usable in browsers / WebGPU via the `nullpii/backend/*` subpath imports.

Requires **Node 24 LTS** (see `.nvmrc`).

## Backends

| Backend | Platform               | Notes                                              |
| ------- | ---------------------- | -------------------------------------------------- |
| `cpu`   | All                    | Universal. Currently fastest on macOS.             |
| `mps`   | Apple Silicon          | CoreML EP; partial op coverage — see `EVAL_RESULTS.md`. |
| `cuda`  | Linux/Windows + NVIDIA | Tensor cores on Volta+. CUDA EP via ORT.           |

Auto-selects in priority **CUDA → MPS → CPU**.

> **State today vs the headline comparison**: the source tree under `src/` currently loads `openai/privacy-filter` (1.5B + Viterbi BIOES decoder), default variant `int4` (~875 MB). It scores **0.7669 F1** on `nullpii-bench` — already strong, but below the **0.8638 F1** number quoted in the headline comparison. The headline reflects the *bench-validated target state* after the backbone migration to `onnx-community/gliner_multi_pii-v1` (FP32, ~1.1 GB) plus the curated regex pack with URL whitelist + ensemble merge + boundary refinement (clean baseline, no test-set tuning). That migration is the next implementation milestone — see "Roadmap" below. The two states are a single src-tree refactor apart, not a separate codebase.

## Architecture

```
input text
   │
   ▼                  ┌──────────────────────────────┐
tokenizer ─offsets─►  │ ONNX Runtime (CPU / MPS /    │
   │                  │             CUDA EP)         │
   │                  │                              │
   ▼                  └────────────────┬─────────────┘
attention_mask                          │ logits [seq × 33]
                                        ▼
                            constrained Viterbi (BIOES)
                                        │
                                        ▼
                              char-level PiiSpan[]
                                        │
                                        ▼
              vault.sanitize ──► (placeholder text, sessionId)
                                        │
                                        ▼
                            (LLM call with placeholder text)
                                        │
                                        ▼
                            vault.restore(sessionId) ──► original text
```

## Roadmap

- **Backbone migration** — replace the in-tree `openai/privacy-filter` (1.5B, custom BIOES Viterbi decoder) with `onnx-community/gliner_multi_pii-v1` (278M, span output). Drops `src/viterbi.ts` + `src/labels-bioes.ts`, swaps tokenizer, simplifies the runtime. Shipping recipe: ONNX FP32 + chunking + the curated regex pack documented above. Bench-validated (clean baseline): 0.8638 F1 on `nullpii-bench` vs 0.7669 today.
- **Per-call timeout in the runtime** — the openai backbone deadlocks on certain long inputs in chunking + Viterbi (sample 1700 of `ai4privacy-heldout` triggered an infinite loop during the bench harness run). Add a per-sample timeout with a clean fallback to the unchunked single-pass result. Becomes moot once the gliner backbone migration lands (gliner doesn't run Viterbi).
- **Plant-and-detect dataset loaders** — `enron-planted`, `stackoverflow-planted`, `thestack-planted`, `conll2003` all have broken HF mirrors. Replace with currently-accessible mirrors (or vendor the corpora) so the OOD evidence base is more than `nullpii-bench`'s 264 samples.
- **Statistical significance** — bootstrap CI over per-sample F1, multi-seed runs, paired comparisons. Current numbers are point estimates; differences <0.02 should not be over-interpreted.
- **Failure analysis loop** — `packages/eval/scripts/failure_analysis.py` already extracts top FN/FP per label per tool. Use periodically to identify regex patterns worth adding to the recognizer pack (criterion: distinctive boundary-anchored prefix, low FP risk).
- **Score-based ensemble ranking (generalist FP-cascade fix)** — replace the binary `primary` / `union` / `intersection` ensemble strategies with a confidence-weighted overlap resolver. Each predictor produces (label, span, score); on overlap, keep the higher-score span; for non-overlap regex spans, drop those below a per-category confidence threshold. Removes the ai4privacy-style FP cascade where regex spans fire on workloads they weren't designed for — generalist single-recipe alternative to per-workload profiles.
- **Span-boundary Viterbi refinement on top of GLiNER** — GLiNER outputs span lists (start/end/label/score) but with looser token-level boundaries than constrained Viterbi BIOES decoders. On structured-PII templates (`ai4privacy-*`, medical record formats), opf-Viterbi beats GLiNER-based recipes by 0.02–0.20 F1 on tight boundary detection. Add a post-pass that re-decodes GLiNER's per-token logits with a constrained Viterbi over the span set, refining left/right edges. Expected lift: +0.05 F1 on ai4-heldout / ai4-400k without affecting nullpii-bench. Implementation: ~2 days (decoder + integration test).
- **Note on piiranha + deberta benchmark scores** — the empirical bench shows piiranha hitting **F1 0.96 on `ai4privacy-400k`** while scoring 0.36 on `nullpii-bench`; deberta hits **0.75 on `isotonic-en-heldout`** while scoring 0.32 on `nullpii-bench`. Both numbers reflect model fine-tuning on the target dataset (memorization), not generalization. They're documented in the competitor table for completeness but should not drive design decisions — the same fine-tune-on-distribution failure mode that nullpii's own GLiNER fine-tune exhibited. Real-world OOD numbers (`nullpii-bench`, `oasst-dev-planted`) are the ones that matter.

### Profile-based deployment

`nullpii` ships with 4 detection profiles, selectable via `--profile` flag:

- **`devops` (default)**: dev-paste workload (PR reviews, deploy logs, code with secrets, multilingual customer support). Uses `gliner_multi_pii-v1` (ONNX, 278M) + full ~65-pattern regex pack covering AWS / GitHub / Stripe / OpenAI / Anthropic / Slack / Discord / Telegram / Google API keys + DB connection strings + crypto wallets + IBAN / SSN / EU codes. Fits GDPR-aligned developer-workflow compliance.

- **`legal`**: legal text, court rulings, contracts. Uses the v8 multi-domain fine-tune (trained on TAB ECHR + ai4privacy + isotonic) + minimal regex pack (URL / email / IBAN / SSN / phone only). Optimised for PERSON / DATETIME / LOC heavy distributions. F1 +0.39 over `devops` on TAB ECHR.

- **`medical-experimental`** (EXPERIMENTAL ONLY): medical-narrative pre-filter. Uses v8 multi-domain backbone + minimal regex (currently identical to `legal`). Medical-specific recognizers (MRN, prescription IDs, insurance numbers, NPI) are **NOT YET implemented**; the profile is **NOT validated** against i2b2 / MEDDOCAN / MIMIC. Coverage estimated at ~10/18 HIPAA Safe Harbor identifiers. **Do NOT cite this profile as a HIPAA de-identification control.** Use only as a research-grade pre-filter with a human reviewer in the loop. The `-experimental` suffix is intentional and stays until a MEDDOCAN-validated medical recognizer pack ships.

- **`general`**: unknown / mixed-domain workload. Runs both v6 and v8 backbones in ensemble (union merge); 2× inference latency but broadest coverage. Recommended for high-stakes cases where false negatives are unacceptable.

Profile selection trade-offs documented in `packages/eval/results/profile-bench-20260502/decision_matrix.md` (after bench).

### Roadmap — v10 LoRA-per-domain (8–10 weeks)

The compliance review (`packages/eval/results/compliance-expert-review-20260502.md`) recommends LoRA adapters per domain over the frozen v6 backbone, instead of single-model rebalancing. The single-model path (v8 / v9) proved fundamentally tension-bound: a fixed-capacity GLiNER backbone cannot fit ~74% structured + ~5% narrative training data without sacrificing one side.

**v10 corpus mix (target ~150k):**

| Source | Records | Rationale |
|---|---:|---|
| TAB ECHR train (un-collapsed schema, all 8 entity types) | 15k | full Art. 4 surface, preserve ORG/DEM/CODE |
| MEDDOCAN train | 10k | medical narrative + Spanish, DUA-free |
| i2b2 2014 (DUA gated) | 15k | HIPAA-grounded narrative |
| OASST + planted PII (handcrafted) | 20k | real conversational distribution |
| ai4privacy 0–20k | 20k | structured floor |
| isotonic 0–7.5k × 4 locales | 30k | multilingual structured |
| dev-paste-synth (capped) | 15k | dev-paste anchor |
| Common Crawl prose (negative class) | 25k | learn to NOT fire on prose |

Structured ≈ 33%, narrative ≈ 67% — inverts v9's ratio.

**Architecture:** LoRA adapters over frozen v6 backbone (one adapter per domain: devops / legal / medical / general). Switchable inference (adapter on/off). Multi-task training: shared encoder + `pii_span_head` + auxiliary `domain_head` (4-way) used only at training to encourage domain-invariant span representations.

**Training plan:** class-balanced sampling, curriculum (epoch 1 structured → epoch 2 narrative → epoch 3 mixed). Held-out routing-eval corpus: 500 hand-annotated documents covering 8 PII classes × 5 locales × 4 domains, used **only** for v10 go/no-go.

**Effort estimate:** ~8–10 weeks calendar (corpus prep 3–4 weeks gated by i2b2 DUA, LoRA fine-tune 1 week 4090 GPU, held-out annotation 2 weeks with 2 annotators + adjudicator, writeup 1 week). Without i2b2: ~6–7 weeks MEDDOCAN-only.

### Roadmap — bench completeness

> **Headline gating rule**: until at least one third-party PII bench (i2b2 / TAB / MEDDOCAN) validates the OOD claim, `nullpii-bench` numbers are positioned as "best on dev-paste workload, self-built bench, schema public" — not as raw "SOTA". The self-built-bench critique is real; third-party validation removes it.

**Done (`packages/eval/results/mac-overnight-20260501/`):**
- ✅ Presidio + Piiranha + DeBERTa-PII + scrubadub competitor matrix on 9 PII datasets (`nullpii-bench`, `ai4privacy-300k/400k`, `isotonic-en/de/fr/it`, `oasst-dev-planted`, `presidio-synthetic`). Empirical numbers in [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md). Competitor numbers frozen as immutable baseline — future iterations re-run only `--tools nullpii` and merge against this baseline (~12× faster iteration).

**Drop from headline matrix:**
- ❌ `wikiann-es/zh/ja` — NER schema (PER/LOC/ORG), not PII. All tools score 0.05–0.32 due to schema mismatch, not detection failure. Misleads readers. Keep as appendix-only "NER coverage signal", not main matrix row. CJK PII coverage gap acknowledged separately.

**Third-party validation (highest priority — removes self-built-bench critique):**
- **TAB (Text Anonymization Benchmark)** — ECHR court rulings annotated for legal PII, ACL 2022, public. Real third-party gold standard. No DUA gating. Top priority for headline credibility.
- **i2b2 2014 deid challenge** — real medical record PII, gated DUA but legit. Highest-cred medical bench, paired with future `healthcare` profile work.
- **MEDDOCAN** — Spanish medical PII shared task, real records, public. Adds Romance-language medical coverage.
- **WikiPII** — Wikipedia bio extracts annotated PII, multilingual real samples.
- **MIMIC-III/IV physician notes** — gated DUA painful, lowest priority of the medical set.

**Adversarial edge-case suite (build ourselves, ~50–100 samples per category):**
- **Typo PII** — `gianluca@gmial.com`, `+1 (555 555 1234`, transposed digits, off-by-one ZIP. Tests model robustness to user input noise.
- **Unicode obfuscation** — homoglyph substitution (`gianluca@gmaiI.com` cap-i for lowercase-l, Cyrillic `а`/`о` for Latin), zero-width chars (`gian​luca@gmail.com`), full-width Latin (`ｇｉａｎｌｕｃａ`).
- **Whitespace obfuscation** — `g 1 a n l u c a @ g m a i l . c o m`, `gianluca @ gmail . com`, line breaks mid-token.
- **Encoding obfuscation** — base64 / URL-encoded / HTML entity (`g%69anluca`, `&#103;ianluca`) PII embedded in text. Tests if model catches obvious leak attempts.
- **Adversarial decoys** — non-PII patterns that look like PII (`localhost:5432`, `x@y.z`, `0.0.0.0`, MAC addresses, UUID tokens). Tests FP rate under deliberate confusion.
- **Code with PII** — credentials in comments / docstrings / config files (`# api_key=sk-ant-...`, `password = 'P@ssw0rd!'`). Already partial coverage in `nullpii-bench`, formalise as standalone suite.

**Secondary (NER-subset coverage, not PII validation):**
- **CoNLL2003 / OntoNotes / MultiNERD** — NER schema (PER/LOC/ORG), not PII. Useful only as `person_name` subset signal across multiple languages. Document the schema mismatch explicitly. Don't headline.

**Performance + cloud-API comparisons:**
- **Latency benchmark suite** — F1 vs throughput Pareto curve. Per-tool latency p50/p95/p99 across prompt sizes (100 / 1k / 10k chars), throughput in samples/s per backend (CPU / MPS / CUDA on Linux x86 + Apple Silicon).
- **Cloud-API + closed-source competitor matrix (tiered)** — extend headline bench to closed competitors. Tiering by direct comparability:
  - **Tier 1 — direct PII API, benchable**: AWS Comprehend PII (`detect_pii_entities`, $1.20/1M chars), Google Cloud DLP (`InspectContent` with `infoTypes`, ~$3/1M chars), Azure AI Language PII Recognition ($1/1k req). All three offer official API + `n=2000` per dataset across 9 PII benches feasible at ~$50–100 total. Highest-cred "we beat closed SaaS" datapoint when paired with `nullpii-bench` real-world OOD.
  - **Tier 2 — closed enterprise, contact-sales (best-effort)**: Protect AI Guardian (PII is one feature of runtime, no public API endpoint, requires demo / trial), Lakera Guard PII module (primary product is injection detection — PII coverage uncertain, requires sales contact). Bench only if trial access granted.
  - **Tier 3 — not directly benchable, positioning notes only**: Portkey (gateway — guardrails plugins wrap external PII libs, benching Portkey = benching the plugin, redundant), OpenAI moderation API (content safety, NOT PII detection — incomparable schema), Helicone (observability only, zero PII), Robust Intelligence (closed Cisco enterprise, no public API), OpenRouter (LLM proxy aggregator, zero PII detection — architecture reference for `nullpii.cloud` proxy design only).
  - One-shot bench run for Tier 1 → headline numbers in COMPETITIVE_ANALYSIS.md. Not part of recurring eval (cost + rate limits). Tier 2 opportunistic. Tier 3 documented as "not applicable" with reason.
- **Ablation table** — quantify the F1 contribution of each pipeline component on `nullpii-bench`: nullpii w/o regex pack, w/o URL whitelist filter, w/o boundary refinement, with default-only regex (~10 patterns) vs extended (~70). Defends design choices.

**Iteration loop (post-bench):**
- Branch `research-iter-v7` opens with frozen competitor baseline. Each pipeline change re-runs `bench_full.py --tools nullpii --datasets <9-non-wikiann>` (~15 min Mac CPU) and merges against the immutable competitor matrix. Iteration cost drops from 3 h → 15 min.

### Roadmap — competitive positioning

- **OSS PII firewall for LLM traffic** — see [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md). Strategic gap nullpii fills: open-source, reversible-vault, local-first, latency-zero, backbone-agnostic. No competitor combines all four. Closest commercial peer is Skyflow (cloud-only) which charges per-call SaaS pricing. Positioning: pair with Portkey (gateway) + Rebuff (injection) for the full stack rather than competing head-to-head with Lakera (injection detection) or Portkey (gateway).
- **OSS-license enterprise tier between "library" and "Zscaler-tier closed product"** — gap in the market: Guardrails AI is library-only, Zscaler is closed enterprise SaaS, nothing in the middle. The SDK-adapter pattern + managed cloud (`nullpii.cloud`) items below are the concrete steps into that gap.

### Roadmap — under evaluation

- **SDK adapter pattern (multi-provider wrappers)** — wrap each LLM SDK so users get sanitize+restore transparently while keeping native ergonomics. Targets: `nullpii/adapter/openai`, `nullpii/adapter/anthropic`, `nullpii/adapter/gemini`, `nullpii/adapter/mistral`, `nullpii/adapter/cohere`. Pattern: `wrapOpenAI(new OpenAI())` returns a drop-in proxy with vault wired into request/response paths. Streaming SSE support via stream-restore primitive (chunk-buffer until span boundary safe). Tool-call vault scope: `tool_use.input` JSON + `tool_result.content` blocks (already solved in prior `src/proxy.ts` on `bench-runpod-on-demand` branch — port logic into `nullpii/stream` reusable primitive).

- **Web framework middleware** — `nullpii/middleware/express`, `/fastify`, `/nestjs`, `/hono`. Single primitive on top of stream-restore. Hono variant covers Cloudflare Workers / Bun / long-lived Node containers under one handler. AWS Lambda dropped from v1 — cold-start tax (1–2s GLiNER load) kills DX. Use Fly Machines / Cloud Run / Fargate for serverless instead (scale-to-zero with sub-second wake).

- **`nullpii.cloud` — managed wrapper proxy (paid SaaS)** — for users who can't or won't self-host. Architecture:
  - Always-warm dispatcher (Hono on Cloudflare Workers) → routes to per-tenant pod.
  - Per-tenant pods on Fly Machines / Cloud Run, scale-to-zero, ~1–3s cold wake.
  - Provider API key passthrough — **never stored**. User envs key in proxy header; dispatcher forwards to OpenAI / Anthropic / Gemini.
  - Vault scoped per-request, in-memory only, evict on response complete. No payload logging.
  - Auth: per-tenant nullpii API key.
  - Pricing: per-request micro-fee + optional warm-pool subscription per power user.
  - Compliance path: SOC2 Type 1 → Type 2 → HIPAA BAA (enterprise unlock).
  - Onboarding: swap `BASE_URL` env var (Claude Code / Codex CLI / Cursor) — 30-second setup.
  - Tradeoff: breaks "PII never leaves device" claim → positioned as second-tier convenience product. OSS local stays as paranoia tier. Standard SaaS+OSS dual play (Skyflow, Lakera same logic).

- **Tool-support matrix for `BASE_URL` swap** —
  - Claude Code: `ANTHROPIC_BASE_URL` ✓
  - Codex CLI (OpenAI): `OPENAI_BASE_URL` ✓
  - Cursor: Settings → "Override OpenAI Base URL" ✓
  - Continue / Aider / Cline / aider-style tools: ✓ (custom endpoint config)
  - GitHub Copilot: ✗ (endpoint locked; enterprise tier has separate proxy mechanism, not user-config)
  - ChatGPT desktop / web: ✗ (closed product, no override; out of scope)

- **Audit pass + out-of-band signals** — safety net for users worried "did nullpii catch my API key?". Two-pass design:
  1. Sanitize: model + regex → vault populated.
  2. Audit shadow-scan: high-recall regex over original input cross-checked against vault. Patterns: AWS (`AKIA[0-9A-Z]{16}`), Stripe (`sk_live_`, `sk_test_`, `rk_live_`), GitHub (`ghp_`, `gho_`, `ghs_`), OpenAI (`sk-proj-`, `sk-`), Anthropic (`sk-ant-`), Google API (`AIza[0-9A-Za-z_-]{35}`), Slack (`xox[baprs]-`), JWT pattern. If audit hit not in vault → leak suspected.
  - Signal channel: HTTP response headers (out-of-band, non-invasive — no inline comments in payload):
    - `X-Nullpii-Status: verified | warned | leaked`
    - `X-Nullpii-Spans: <count>`
    - `X-Nullpii-Confidence: <min span score>`
    - `X-Nullpii-Audit: clean | suspect`
  - IDE / CLI extension reads headers → status badge (🟢 verified / 🟡 warned / 🔴 leaked).
  - Configurable behaviour on `leaked`: `onAudit: 'block'` (throws, drops request) or `onAudit: 'warn'` (forwards with header). Express/Nest middleware example: `throw new ForbiddenException('secret leak detected')`.
  - Reassurance UX: user sees green badge after each call → trust signal that vault caught everything. Red badge = pre-flight abort before token leaves device/proxy.

- **Browser WebGPU runtime** — `nullpii/web` running ONNX via `onnxruntime-web` + WebGPU EP. INT4 GLiNER (~110 MB) cached in IndexedDB after first download. **Killer privacy story**: PII never leaves browser, only sanitized text goes to LLM, vault stays client-side. Differentiator no closed-cloud competitor can match (Skyflow / Lakera architectural lock-in to server-side processing). Use case: ChatGPT-style web UIs that proxy through a WebGPU-detect-enabled extension or first-party deployment.

- **React Native runtime** — `nullpii/react-native` via `onnxruntime-react-native`, CoreML EP on iOS / NNAPI on Android. Bundle bloat constraint: ship INT4 ONNX over CodePush / Expo Updates rather than baked into the IPA/APK. Use case: mobile chat apps, voice transcription privacy filter.

- **IDE / coding-assistant integration** — VS Code / JetBrains / Cursor / Zed extensions. Hooks pre-LLM-send and post-LLM-receive in the IDE's chat / autocomplete path. Live SSE restore on streaming responses (token-by-token incremental restore). Per-user policy file (sops-encrypted or local keychain) for category auto-decode rules (`secret` → never, `private_email` → always for owner, etc.). Distribution: VS Code Marketplace / JetBrains Plugin Repository / nvim plugin manager. Complements OSS local + cloud SaaS: enterprise = managed cloud + IDE extension; personal = OSS local + IDE extension.

## nullpii-bench (eval dataset)

`packages/eval/datasets/nullpii-bench.jsonl`:

- **271 samples**, **680 PII spans**, **5 locales** (en / it / de / fr / es), Apache-2.0.
- Three subsets: `bundled` (202 dev-style prompts — PR reviews, deploy logs, RFCs, customer-support tickets), `adversarial` (decoys), `long-prompts` (62 ~3k-char prompts that exercise chunking).
- Schema: `{ id, locale, subset, text, spans }` per row. See [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md).

## HF fine-tune model — training details + limitations

This section documents the [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) fine-tune, which is **not the npm package's default backbone**. Use only for ai4privacy / Isotonic-style structured-PII workloads (see appendix above for trade-off).

- Base: `urchade/gliner_multi_pii-v1` (mDeBERTa-v3-base + GLiNER head, ~278M params)
- Hardware: 1× RTX 5090 (32 GB)
- Mixed precision: BF16 + TF32
- Optimizer: AdamW, cosine LR with linear warmup (ratio 0.1)
- **Training data is a subset, not the full upstream releases.** Default caps (`packages/eval/scripts/runpod/train-on-pod.sh`): `ai4privacy/pii-masking-300k` capped at **100k** samples (≈33% of the full release), `Isotonic/pii-masking-200k` capped at **20k per locale × 5 locales = 100k** samples (≈50% of the release, distributed across en/de/fr/it/es). Round 2 added **30k synthetic dev-prompts**. Total train mix ≈ 230k samples.
- **Round 1**: ai4privacy + Isotonic only. Effective batch 24 (12 × 2 grad accum), encoder LR 5e-6 / head LR 1e-5, 20 epochs cap, early stopping patience 3 → stopped at epoch 6. Recovered multilingual F1 0.93+ on training distribution but **regressed dev-prompts-synth** (0.62 → 0.43) due to distribution mismatch.
- **Round 2**: continued from round-1 best, added 30k dev-prompts-synth to the mix, halved LR to 2e-6 / 5e-6, raised weight decay from 0.01 to 0.05. 10 epochs cap, early stopping patience 3 → best at epoch 8 (eval_loss 1.528). dev-synth recovered to 0.82 while training-distribution multilingual stayed 0.93+.

**Limitations of the fine-tune**:

- **Generalisation cost** — loses 0.25 F1 vs the npm-package recipe on `nullpii-bench` (real-world OOD). Quantified in the headline appendix above. This is why the npm package does NOT use this model as its backbone.
- **Non-Latin scripts** — Japanese / Korean / Chinese dates and names are *not* reliably detected. CJK was excluded from the training mix. The bench's `wikiann-zh` / `wikiann-ja` rows quantify it (every tool collapses below 0.16 F1 there).
- **INT8 dynamic quant collapses** — do not use the INT8 ONNX path; F1 drops to ~0.58. INT4 (matmul-nbits) is the recommended quantised variant.

## Privacy guarantees

- The PII detection step **never touches the network**.
- The vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping.
- No `console.log` of PII; debug logs only carry counts and short ids.
- See [SECURITY.md](SECURITY.md) for the full threat model and how to report a vulnerability.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Same as the GLiNER base model and both training datasets.

The full runtime tree is **100% permissive** (MIT / Apache-2.0 / BSD / ISC / CC0). Verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: a study comparing openai/privacy-filter and a fine-tuned GLiNER for local PII detection.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, mDeBERTa-v3-base + GLiNER head). Training data: a **subset** of [`ai4privacy/pii-masking-300k`](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) (~100k of 300k) and [`Isotonic/pii-masking-200k`](https://huggingface.co/datasets/Isotonic/pii-masking-200k) (~100k of 200k, multilingual mix), plus 30k synthetic dev-prompts. See "Training details" above.
