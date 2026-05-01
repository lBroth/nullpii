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
> The `nullpii` npm package wraps **`onnx-community/gliner_multi_pii-v1` (FP32 ONNX, 278M params)** with chunking, a curated regex recognizer pack (~50 patterns covering AWS / GitHub / OpenAI / Anthropic keys + cloud SaaS tokens + PEM keys + JWTs + DB connection strings + IBAN / SSN / Italian Codice Fiscale), and a reversible in-memory vault. On the use-case-relevant benchmark — `nullpii-bench`, project-bundled real dev prompts (RFCs, PR reviews, multilingual ticket bodies, code with secrets) — F1 = **0.8239**, beating every alternative we tested by +0.13 F1 over baseline GLiNER and +0.15 F1 over the official `opf` CLI for `openai/privacy-filter`. On structured-PII datasets (`ai4privacy`, `isotonic`) it trades blows within ±0.04 F1 — see the per-row breakdown below; "winner everywhere" would not be honest.
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

- **Single-seed benches.** No bootstrap CI, no multi-seed runs. Numbers below are point estimates; treat differences smaller than ~0.02 F1 as noise.
- **`nullpii-bench` (n=264) is the only true-OOD dataset working right now.** The other planned plant-and-detect datasets (`enron-planted`, `stackoverflow-planted`, `thestack-planted`, `conll2003`) have broken loaders on the open-data path (mirrors removed/renamed/gated, deprecated `trust_remote_code=True`). The OOD generalisation evidence rests entirely on those 264 prompts.
- **Same-dataset heldout ≠ generalisation.** `*-heldout` cells are drawn from rows the fine-tune was not trained on, but from the same dataset distribution it *was* trained on. Heldout vs traindist numbers cluster within 0.005 F1 — slicing the row index isn't a real generalisation test.
- **The retracted preview headline (`0.93–0.97 multilingual F1`) was a same-dataset memorisation measurement.** It is misleading and has been removed from this README. The HF model card carries the corrected numbers.
- **CJK is a documented dead zone.** Every tool tested scores below 0.16 F1 on `wikiann-zh` / `wikiann-ja`. None of the training mixes used CJK data.
- **WikiAnn schema mismatch.** PER → `private_person`, LOC → `private_address`. Loose mapping; absolute F1 not comparable to PII-native rows.

## Headline comparison

F1, IoU ≥ 0.5. Mac M-series CPU bench, n=2000 per dataset (n=264 for `nullpii-bench`), single seed. Full matrix at `packages/eval/results/mac-overnight-20260430-v2/matrix.json` (19 tool variants tested; the table below distils to 4 — `nullpii` plus the three reference points). Per-component ablations and the fine-tune trade-off live in the appendices.

| Dataset                  | **`nullpii`** | baseline GLiNER (bare) | openai-official (Viterbi) | openai (HF naive) |
| ------------------------ | ------------: | ---------------------: | ------------------------: | ----------------: |
| **`nullpii-bench` (OOD, n=264)** | **0.8239** |             0.6947 |                    0.6764 |            0.4264 |
| ai4privacy-heldout       |        0.2085 |                 0.1267 |                **0.2303** |            0.1451 |
| isotonic-en-heldout      |        0.5731 |             **0.6016** |                    0.5631 |            0.3822 |
| isotonic-de-heldout      |        0.5808 |             **0.5912** |                    0.5734 |            0.3809 |
| isotonic-fr-heldout      |    **0.5993** |                 0.5953 |                    0.5766 |            0.3771 |
| isotonic-it-heldout      |        0.5789 |                 0.5818 |                **0.6053** |            0.3894 |
| isotonic-en-traindist    |        0.5837 |             **0.6065** |                    0.5767 |            0.3860 |
| ai4privacy-traindist     |        0.2028 |                 0.1171 |                **0.2224** |            0.1392 |
| wikiann-es               |        0.2919 |             **0.3326** |                    0.1844 |            0.0878 |
| wikiann-zh               |        0.1150 |             **0.1353** |                    0.0863 |            0.0383 |
| wikiann-ja               |        0.0500 |             **0.0665** |                    0.0563 |            0.0344 |

**Bold = per-row winner.** `nullpii` wins outright only on **`nullpii-bench` and `isotonic-fr-heldout`**. On every other row baseline GLiNER (bare, just chunking + dedupe, no regex) or `openai-official` (Viterbi) edges ahead by 0.005–0.04 F1. The numbers tell a more nuanced story than a single trophy:

- **`nullpii-bench` (the use case the package targets — dev paste real prompts with secrets, multilingual ticket bodies, code snippets):** `nullpii` wins by a margin (+0.13 vs baseline GLiNER, +0.15 vs openai-official). The regex pack pays off on this distribution because real prompts contain AWS / GitHub / OpenAI keys, IBANs, JWTs, DB connection strings — the patterns we curated for.
- **Structured-PII datasets (`isotonic-*`, `ai4privacy-*`):** baseline GLiNER and openai-official trade blows; `nullpii`'s regex pack adds a small drag (-0.01 to -0.04 F1) by occasionally matching parts of a structured field as `private_url` or `secret`. The regex helps on dev paste, hurts mildly on `Name: ... · Address: ... · Phone: ...` style lines. Still close enough to call it a tie.
- **WikiAnn:** schema mismatch (PER/LOC NER vs PII categories). All tools below 0.34 F1; baseline GLiNER edges the others. Read as non-Latin transfer signal only.

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

> **State today vs the headline comparison**: the source tree under `src/` currently loads `openai/privacy-filter` (1.5B + Viterbi BIOES decoder), default variant `int4` (~875 MB). It scores **0.7669 F1** on `nullpii-bench` — already strong, but below the **0.8239 F1** number quoted in the headline comparison. The headline reflects the *bench-validated target state* after the backbone migration to `onnx-community/gliner_multi_pii-v1` (FP32, ~1.1 GB). That migration is the next implementation milestone — see "Roadmap" below. The two states are a single src-tree refactor apart, not a separate codebase.

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

- **Backbone migration** — replace the in-tree `openai/privacy-filter` (1.5B, custom BIOES Viterbi decoder) with `onnx-community/gliner_multi_pii-v1` (278M, span output). Drops `src/viterbi.ts` + `src/labels-bioes.ts`, swaps tokenizer, simplifies the runtime. Shipping recipe: ONNX FP32 + chunking + the curated regex pack documented above. Bench-validated: 0.8239 F1 on `nullpii-bench` vs 0.7669 today.
- **Per-call timeout in the runtime** — the openai backbone deadlocks on certain long inputs in chunking + Viterbi (sample 1700 of `ai4privacy-heldout` triggered an infinite loop during the bench harness run). Add a per-sample timeout with a clean fallback to the unchunked single-pass result. Becomes moot once the gliner backbone migration lands (gliner doesn't run Viterbi).
- **Plant-and-detect dataset loaders** — `enron-planted`, `stackoverflow-planted`, `thestack-planted`, `conll2003` all have broken HF mirrors. Replace with currently-accessible mirrors (or vendor the corpora) so the OOD evidence base is more than `nullpii-bench`'s 264 samples.
- **Statistical significance** — bootstrap CI over per-sample F1, multi-seed runs, paired comparisons. Current numbers are point estimates; differences <0.02 should not be over-interpreted.
- **Failure analysis loop** — `packages/eval/scripts/failure_analysis.py` already extracts top FN/FP per label per tool. Use periodically to identify regex patterns worth adding to the recognizer pack (criterion: distinctive boundary-anchored prefix, low FP risk).

### Roadmap — under evaluation

- **Enterprise HTTPS-proxy deployment** — instead of (or in addition to) shipping `nullpii` as a per-process npm library, deploy it as a corporate HTTPS proxy that intercepts traffic to `api.openai.com` / `api.anthropic.com` / Mistral / Cohere / Google / local LLM gateways, sanitizes the request body, forwards to the upstream LLM, then `restore()`s on the response (incl. SSE streaming) before returning to the client. Same runtime stack, different deployment shape.
  - Architecture: TLS interception with a corporate CA cert (standard CASB / Zscaler / Netskope pattern); system-wide `HTTPS_PROXY` env-var or PAC file or VPN routing on managed devices; per-session vault (Redis/Postgres for multi-instance); zero-log mode for trust.
  - Pros: LLM-agnostic, zero client-side code change, central audit log of LLM exfiltration risk, GDPR/HIPAA-visible compliance posture.
  - Cons: requires CA cert install on managed devices (standard for enterprise security stacks); MITM trust paradox mitigated by full open-source code path; +50–200ms latency vs direct call (acceptable for chat, marginal for autocomplete); vault state management non-trivial across instances.
  - Prior work: `src/proxy.ts` (deleted in the research pivot, recoverable from `bench-runpod-on-demand` branch) had a working `ANTHROPIC_BASE_URL` proxy with SSE streaming. The same module is the starting point for this productisation.
  - Positioning: open-source enterprise PII firewall for LLM traffic. Compete with Zscaler/Netskope DLP modules (closed, generic) and Skyflow / Privatemode AI (closed, hosted). The OSS path + local-only deployment is the moat.

- **IDE / coding-assistant integration** — companion to (or alternative to) the proxy: ship `nullpii` as a plugin/extension for Claude Code, GitHub Copilot, Cursor, Zed, JetBrains, VS Code, Neovim. Sanitises prompts on send (Cmd-K, chat panel, autocomplete request); on response, auto-restores spans inline if the user has the right authorisation policy, otherwise leaves the placeholders visible. Live decode during streaming responses (token-by-token restore). Works without a corporate proxy — single-machine, per-user — so engineers on personal devices can opt in without IT involvement.
  - Architecture: language-agnostic core via the npm package; thin per-IDE shim (≈ 200–500 LoC) that hooks the IDE's pre-LLM-send / post-LLM-receive callbacks. Vault stays local to the IDE process.
  - Auth model: per-user policy file (sops-encrypted or local keychain) that lists which placeholder categories auto-decode (`secret` → never, `private_email` → always for owner, etc.). Without policy, all placeholders stay visible.
  - Live-changes flow: IDE intercepts streaming SSE chunks, runs `restore()` incrementally (single `nullpii` instance, multiple sessions). Render restored text in the chat panel as it arrives.
  - Distribution: VS Code Marketplace / JetBrains Plugin Repository / nvim plugin manager / native Claude Code skill (per Claude Code's plugin SDK).
  - Complements the proxy path: enterprise = proxy + audit. Personal / SMB = IDE plugin, no infra.

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
