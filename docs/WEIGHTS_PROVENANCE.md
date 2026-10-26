# Weights provenance

What the nullpii detection model was trained on, under which licence, and what was kept out. Read this before you approve the model for use in your organisation.

The model is a fine-tune of a GLiNER span model, exported to ONNX. nullpii downloads it from the Hugging Face Hub on first use, and checks every file it downloads against a SHA-256 pinned in the library; it is not part of the npm package.

## Base model

| Model | Licence | Revision |
|---|---|---|
| [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER head on Microsoft `mdeberta-v3-base`; Zaratiana et al., NAACL 2024) | Apache-2.0 | `1fcf13e8` |

## Training data

Every source below allows commercial use and redistribution of a model trained on it. The licence column is the source's own licence, checked on its Hugging Face page or in its repository.

| Source | Licence | What it contributes |
|---|---|---|
| [`nvidia/Nemotron-PII`](https://huggingface.co/datasets/nvidia/Nemotron-PII), a slice of the train split | **CC-BY-4.0**, attribution required | Synthetic English documents in many domains, with personal data spans, including the extended categories |
| [`allenai/c4`](https://huggingface.co/datasets/allenai/c4) (English web text from Common Crawl), sampled | **ODC-BY** (with the Common Crawl terms of use) | Ordinary web text with no labelled spans, so the model learns when not to mask |
| [TAB, the Text Anonymization Benchmark](https://github.com/NorskRegnesentral/text-anonymization-benchmark) (ECHR court cases), train split | MIT | Long legal documents: persons, dates, locations |
| [`microsoft/presidio-research`](https://github.com/microsoft/presidio-research) synthetic sentences | MIT | Template sentences |
| Project-generated synthetic data | Apache-2.0 | Multilingual sentences, developer pastes (config files, logs, stack traces), US formats, secrets in prose and code, financial and developer identifiers, personal attributes, and developer text that must stay unmasked |

**Carrier text in the generated data.** To place generated values inside realistic code, the generator embeds short excerpts of source files from npm and PyPI packages. Only permissively licensed packages qualify (MIT, ISC, BSD, Apache-2.0, 0BSD, Unlicense, CC0, PSF); the licence is read from each package's metadata. 419 such files are used, from scoped npm packages and installed Python packages, none from the packages the benchmark's trace sets read.

## Kept out of training

These datasets are used to evaluate, never to train:

| Dataset | Why it is excluded from training |
|---|---|
| `ai4privacy/pii-masking-300k` and `-400k` | Custom licence, with commercial use gated |
| `Isotonic/pii-masking-200k` | CC-BY-NC-4.0 (non-commercial) |
| `bigcode/bigcode-pii-dataset` | Gated |
| A held-out slice of Nemotron-PII | Held out to measure generalisation |
| TAB dev and test splits | Evaluation only |
| Every benchmark set nullpii reports on, including PIIMB | Evaluation only |

Held-out slices of `Isotonic/pii-masking-200k` and `ai4privacy/pii-masking-300k` are also nullpii's tuning set: nullpii's thresholds and code changes were chosen on them (see `packages/eval/METHOD.md`, Data). No weights were trained on them.

## Your obligations as a redistributor

If you redistribute the weights:

- Keep the Apache-2.0 licence and the `NOTICE` file.
- Keep the attributions to NVIDIA (Nemotron-PII, CC-BY-4.0) and to the Allen Institute for AI and Common Crawl (C4, ODC-BY) that `NOTICE` carries.

Most of the training text is synthetic. Three sources are real text: the package source excerpts above; TAB, published judgments of the European Court of Human Rights, which name the people involved as the Court published them; and C4, web text. All three are public and used under their published licences.

## Status

This document describes the weights published with nullpii 0.5 (`model.onnx` SHA-256 `58b6d795…4253313a`, `model_fp16.onnx` `900b2b02…c1ae2065`). The weights published before them (v0.3.0) came from the same kinds of sources, with fewer generated categories, and are withdrawn.
