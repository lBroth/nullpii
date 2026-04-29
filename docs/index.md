---
layout: home
title: nullpii
hero:
  name: nullpii
  text: A study in PII detection.
  tagline: openai/privacy-filter (1.5B) used the right way vs a fine-tuned GLiNER (278M). Same task, different trade-offs. Apache 2.0.
  image:
    src: /logo-256.png
    alt: nullpii logo
  actions:
    - theme: brand
      text: Read the comparison
      link: /guide/comparisons
    - theme: alt
      text: Eval results
      link: /guide/eval-results
    - theme: alt
      text: GitHub
      link: https://github.com/lBroth/nullpii
features:
  - title: openai/privacy-filter, used right
    details: 'The 1.5B model needs a constrained Viterbi BIOES decoder. The HF transformers integration ships only logits, so naive `pipeline()` fragments spans. Use the official `opf` CLI or nullpii''s runtime, which both ship the Viterbi.'
  - title: GLiNER fine-tune (nullpii)
    details: 'Two-round fine-tune of `urchade/gliner_multi_pii-v1` on ai4privacy + Isotonic + dev-prompts-synth. Multilingual F1 0.93–0.97 (en/de/fr/it), 14 ms/sample on a 5090. PT, ONNX FP32 and ONNX INT4 published.'
  - title: Reversible vault library
    details: 'Same npm package ships a sanitize / restore engine: each PII span becomes a typed placeholder, the original lives in an in-memory vault keyed by an opaque session id. Round-trip is byte-for-byte exact.'
  - title: Permissive licenses only
    details: MIT / Apache-2.0 / BSD / ISC / CC0 in the runtime tree. Zero LGPL / GPL / AGPL. Audit table in `THIRD_PARTY_LICENSES.md`.
---

## What this repo is

A study + reproducibility kit. We compare the well-known
`openai/privacy-filter` (1.5B parameters, gpt-oss style architecture)
against a fine-tuned, much smaller `urchade/gliner_multi_pii-v1`
(278M, older) on the same PII detection task.

Two deliverables:

1. **npm library** (`nullpii`) — sanitize / restore engine over
   `openai/privacy-filter`, with a constrained Viterbi BIOES decoder.
2. **HF model** (`lBroth/nullpii`) — the GLiNER fine-tune
   in PT, ONNX FP32 and ONNX INT4 variants.

## Library mode (4 lines)

```ts
import { sanitize, restore } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about his SSN.');
// safe.text → 'Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about his SSN.'

const back = await restore(safe.text, safe.session);
// back === original text, byte for byte.
```

## What gets caught

Eight categories from `openai/privacy-filter`: names, emails, phone
numbers, addresses, dates, URLs, account numbers, secrets. Decoded
from BIOES tags via a constrained Viterbi pass against char-level
offsets — no regex, no language-specific tweaks.

## How it stays cheap

- One ONNX file (~875 MiB int4, default) cached in `~/.cache/nullpii/`.
  Pin `variant: 'fp32'` (~5 GiB) for max accuracy
- Backend auto-selects CUDA → MPS → ROCm → CPU
- ~25 ms / 512 tokens on Apple Silicon CPU (int4); chunked above 512
- Zero outbound traffic for the detection step
