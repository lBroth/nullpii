---
license: apache-2.0
base_model: urchade/gliner_multi_pii-v1
datasets:
  - nvidia/Nemotron-PII
  - allenai/c4
language:
  - en
  - de
  - fr
  - it
  - es
  - pt
pipeline_tag: token-classification
library_name: onnx
tags:
  - pii
  - privacy
  - redaction
  - gliner
  - onnx
---

<!-- Source of the model card on huggingface.co/lBroth/nullpii. The release script uploads it as README.md. -->

# nullpii detection model

This is the detection model of [nullpii](https://lbroth.github.io/nullpii/). nullpii hides personal data and secrets in text before the text goes to an LLM, and puts the real values back in the reply. Everything runs on your machine.

The model finds spans of personal data (names, emails, addresses, account numbers, secrets and more). nullpii adds pattern recognizers with checksums, filters, and a vault that swaps each value for a placeholder.

- **Base model:** [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1), a GLiNER span model on Microsoft `mdeberta-v3-base`.
- **Format:** ONNX, in fp32 (`model.onnx`) and fp16 (`model_fp16.onnx`).
- **Licence:** Apache-2.0. The training data is listed below.

## How to use it

Use it through the nullpii npm package. nullpii downloads these files on first use and checks each one against a SHA-256 written into the library.

```bash
npm install nullpii onnxruntime-node
```

```ts
import { NullPii } from 'nullpii';

const np = new NullPii();
const safe = await np.sanitize('Email John Smith at john@acme.io');
// safe.sanitized: 'Email {{PII_PRIVATE_PERSON_0_…}} at {{PII_PRIVATE_EMAIL_0_…}}'
const back = np.restore(safe.sanitized, safe.sessionId);
// back.restored: the original text
```

nullpii also ships a gateway for the Anthropic and OpenAI chat APIs and a Claude Code mod. See the [nullpii documentation](https://lbroth.github.io/nullpii/); the source is on [GitHub](https://github.com/lBroth/nullpii).

nullpii runs these files with its own tokenizer and decoder. Loading them with the Python `gliner` package has not been tested.

## What it finds

nullpii can ask the model for 17 labels: `private_person`, `private_email`, `private_phone`, `private_address`, `private_url`, `account_number`, `secret`, `private_passport`, `private_driver_license`, `private_vehicle_id`, `private_geolocation`, `private_date`, `private_organization`, `private_occupation`, `private_demographic`, `private_sensitive` and `private_title`.

By default nullpii masks what is risky to give to a coding agent's model: names, contact details, addresses, ids and accounts, secrets. It turns off the last six labels (dates and five personal attributes), so they stay readable. Health, religion or sexual orientation written in your text reaches the model by default; `/pii mask sensitive` (or `disabledCategories`) changes that. You can change this in one config file.

## Results

These numbers are for nullpii as a whole: this model plus the recognizers and filters. They are not for the model alone. Every test was fixed before the run, except one AB-1 scoring rule changed after the scores were first read; that change helped the other tools more, and both scorings are published. The results include the cases nullpii loses. The method is in [METHOD.md](https://lbroth.github.io/nullpii/method).

![Agent traffic: leak rate and keep rate per tool](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/ab1-agent-traffic.svg)

- **Coding-agent traffic (AB-1, 966 documents):** nullpii lets 9.5% of the values that must be hidden through, and keeps 85.4% of the values that must stay readable. Only rizzo-pii lets fewer through (8.1%), but it keeps only 44.5% readable.
- **Weak spots:** person names (24% let through; 11 of the 15 other tools let fewer through) and URLs (31%). On secrets alone, nullpii does not lead: openai's privacy-filter lets fewer GitHub-issue secrets through (8.2% against 11.5%), and on CredData nullpii lets 24.5% through, most of it UUIDs that CredData counts as credentials and nullpii keeps readable as ids (13.0% without them).

![Documents: macro char-F2 per tool](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/r3-documents.svg)

- **Documents (five held-out sets):** nullpii is second of 15 tools (macro char-F2 0.758; rizzo-pii 0.770). On English documents alone it is fifth (0.714). Much of its lead comes from one set, Greek and German clinical notes.
- **It masks a lot.** Its recall is the highest of any tool at its best-scoring setting (0.958). Its precision is below most tools'.

## Training data

All training data allows commercial use. Full details: [WEIGHTS_PROVENANCE.md](https://lbroth.github.io/nullpii/WEIGHTS_PROVENANCE).

| Source | Licence |
|---|---|
| [`nvidia/Nemotron-PII`](https://huggingface.co/datasets/nvidia/Nemotron-PII), part of the train split | CC-BY-4.0 |
| [`allenai/c4`](https://huggingface.co/datasets/allenai/c4), a sample of English web text | ODC-BY |
| [TAB](https://github.com/NorskRegnesentral/text-anonymization-benchmark), train split (European Court of Human Rights cases) | MIT |
| [`microsoft/presidio-research`](https://github.com/microsoft/presidio-research) template sentences | MIT |
| Synthetic data generated by the nullpii project | Apache-2.0 |

No benchmark set nullpii reports on was used for training, and neither were datasets with non-commercial or gated licences (ai4privacy, Isotonic, bigcode-pii). Held-out slices of Isotonic (CC-BY-NC-4.0) and ai4privacy-300k are nullpii's tuning set: its thresholds and code changes were chosen on them. No weights were trained on them.

## Limits

- It misses some values: about 1 in 10 on coding-agent traffic. Do not make it your only privacy control.
- The fine-tuning text is mostly English. The base model covers six languages.
- It finds what is written out. It does not infer facts, such as a health condition, from indirect wording.
- nullpii replaces values with placeholders that it can reverse. This is pseudonymisation, not anonymisation, and not a compliance certification.

## Files

| File | Size | SHA-256 |
|---|---:|---|
| `model.onnx` | 1,157,108,162 bytes | `58b6d795693fc3e79f465134a8e5acd4fa58799c6d614f1b795df24d4253313a` |
| `model_fp16.onnx` | 579,679,746 bytes | `900b2b025915ca437515aa4154ee51467ab47805e67e6d883df37d69c1ae2065` |
| `tokenizer.json` | 16,034,824 bytes | `c5b8041501fcdee792b9b112dd592861f04391a24633a73fd9f05aaaf6e8eff1` |
| `gliner_config.json` | 2,219 bytes | `dec8f0f8a2d78af7d7c5553cf7144abc9bf06774170d9ebca6b831db6e542790` |
| `tokenizer_config.json` | 2,928 bytes | `c12b7b3bab6cd638f70b203daf1438bf7fedbeab4728a1e155728af9a5a55687` |

## Licence and attribution

Apache-2.0. If you redistribute the weights, keep the licence, the `NOTICE` file, and the attributions to NVIDIA (Nemotron-PII, CC-BY-4.0) and to the Allen Institute for AI and Common Crawl (C4, ODC-BY).

The base model is GLiNER: Zaratiana, Tomeh, Holat and Charnois, *GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer*, NAACL 2024.
