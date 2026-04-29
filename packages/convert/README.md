# nullpii-convert

Build-time pipeline that **fetches** and **verifies** the upstream
`openai/privacy-filter` model at a pinned commit SHA. We don't run our
own conversion: upstream already publishes the ONNX variants and the
model architecture has no public modeling code, so re-converting adds
risk for no gain.

## Run

```bash
cd packages/convert
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m nullpii_convert.pipeline all     # fetch + manifest + verify + smoke + consistency
python -m nullpii_convert.pipeline fetch   # individual stages
```

## What each stage does

- **fetch** — `huggingface_hub.snapshot_download` at the pinned SHA.
- **manifest** — write `manifest.json` (revision + per-file SHA256).
- **verify** — re-hash everything against the manifest. If `model.sig` is present and the `sigstore` CLI is installed, signature is checked.
- **smoke** — load every ONNX variant with `onnxruntime.InferenceSession` and run a fixed prompt. Output rank/shape/label-count must match `id2label`.
- **consistency** — score every quantized variant vs the fp32 baseline on 50 samples from `ai4privacy/pii-masking-300k`. Macro-F1 divergence must be ≤ `MAX_F1_DIVERGENCE` (0.005).

There is **no** torch baseline F1 — the upstream architecture
(`OpenAIPrivacyFilterForTokenClassification`) has no public modeling
code, so we trust the weights and verify cryptographically.

## Tests

```bash
pytest -q
```

## Publish (deferred)

`mirror.py` can upload to a HuggingFace mirror; refuses to run without
both `HUGGING_FACE_HUB_TOKEN` and `--confirm-publish`. Run when ready.
