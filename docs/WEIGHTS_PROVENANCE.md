# Weights provenance

What the nullpii detection model was trained on, under which licence, and what was kept out. Read this before you approve the model for use in your organisation.

The model is a LoRA fine-tune of a GLiNER span model, merged into the base and exported to ONNX. nullpii downloads it from the HuggingFace Hub on first use; it is not part of the npm package.

## Base model

| Model | Licence | Revision |
|---|---|---|
| [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER head on Microsoft `mdeberta-v3-base`; Zaratiana et al., NAACL 2024) | Apache-2.0 | `1fcf13e8` |

Only LoRA adapters on the encoder's attention projections are trained. Every other weight of the base model is frozen.

## Training data

Every source below allows commercial use and redistribution of a model trained on it. The licence column is the source's own licence, checked on its HuggingFace page or in its repository.

| Source | Licence | What it contributes | Rows used |
|---|---|---|---:|
| [`nvidia/Nemotron-PII`](https://huggingface.co/datasets/nvidia/Nemotron-PII), train split, ~10k rows from the start of the split | **CC-BY-4.0**, attribution required | Synthetic English documents in many domains, with personal data spans | ~10,000 |
| Faker-generated US formats (`build_us_formats_corpus.py`) | Apache-2.0, project-generated | Phone numbers, SSNs, addresses and dates in US formats | 5,000 |
| Developer pastes (`dev-paste-synth-train.jsonl`) | Apache-2.0, project-generated | Config files, logs and stack traces with personal data | 12,000 |
| Faker baselines in en, de, fr, it, es, and long English prompts | Apache-2.0, project-generated | Short multilingual sentences | 264 |
| [`microsoft/presidio-research`](https://github.com/microsoft/presidio-research) synthetic sentences, rows 0–3,999 | MIT | Template sentences | 4,000 |
| [TAB, the Text Anonymization Benchmark](https://github.com/NorskRegnesentral/text-anonymization-benchmark) (ECHR court cases), train split, first annotator | MIT | Long legal documents: persons, dates, locations | up to 5,000 windows |
| [`allenai/c4`](https://huggingface.co/datasets/allenai/c4) (English web text from Common Crawl), sampled | **ODC-BY** (with the Common Crawl terms of use) | Ordinary web text with no labelled spans, so the model learns when not to mask | up to 14,000 windows |
| Gap corpus (`build_gap_corpus.py`): synthetic secrets, crypto and bank numbers, developer records, personal attributes, and developer hard negatives | Apache-2.0, project-generated | The classes and contexts the base corpus lacked | 26,100 |

**Carrier text in the gap corpus.** To place generated values inside realistic code, the generator embeds short excerpts of source files from npm and PyPI packages. Only permissively licensed packages qualify (MIT, ISC, BSD, Apache-2.0, 0BSD, Unlicense, CC0, PSF); the licence is read from each package's metadata. Packages that the evaluation traces read are excluded.

**Augmentation.** A quarter of the rows also appear with adversarial character perturbations (homoglyphs, zero-width characters, spacing) applied inside the personal-data spans.

## Kept out of training

These datasets are used to evaluate, never to train:

| Dataset | Why it is excluded from training |
|---|---|
| `ai4privacy/pii-masking-300k` and `-400k` | Custom licence, with commercial use gated |
| `Isotonic/pii-masking-200k` | CC-BY-NC-4.0 (non-commercial) |
| `argilla/textcat-tokencat-pii-per-domain` | Report set: evaluation only |
| `bigcode/bigcode-pii-dataset` | Gated |
| A held-out slice of Nemotron-PII (train rows 20,000–21,999) | Held out to measure generalisation |
| The `claude-code-traces` sets | Evaluation only: their tuning half is used to choose between variants, their report half only to report |

How the evaluation keeps tuning and reporting apart is described in `packages/eval/scripts/ab/PROTOCOL.md`.

## Your obligations as a redistributor

If you redistribute the weights:

- Keep the Apache-2.0 licence and the `NOTICE` file.
- Keep the attributions to NVIDIA (Nemotron-PII, CC-BY-4.0) and to the Allen Institute for AI and Common Crawl (C4, ODC-BY) that `NOTICE` carries.

Most of the training text is synthetic: Nemotron-PII, presidio-research and the project's own generators. Two sources are real text: TAB is published judgments of the European Court of Human Rights, which name the people involved as the Court published them, and C4 is web text. Both are public, and both are used under their published licences.

## Status

This document describes the phase-F weights (training corpus v4), which are being evaluated and are not yet released. The exact dataset revisions will be pinned here when they are. The weights published today (`lBroth/nullpii`, v0.2) were trained on the same sources, except for the gap corpus.
