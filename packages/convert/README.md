# nullpii-convert

Build-time pipeline that **fetches** and **verifies** the upstream
`openai/privacy-filter` model at a pinned revision. **No own conversion**:
upstream already publishes ONNX (fp32, fp16, int8, int4, int4+fp16), and the
model uses a custom architecture without public modeling code, so re-converting
is unnecessary and adds risk.

## Layout

```
packages/convert/
├── pyproject.toml
├── src/nullpii_convert/
│   ├── config.py        # MODEL_ID, UPSTREAM_REVISION (pinned SHA), tolerances
│   ├── checksums.py     # SHA256 helpers and sidecars
│   ├── fetch.py         # HF snapshot_download at pinned revision
│   ├── manifest.py      # produce manifest.json (revision + per-file SHA256)
│   ├── verify.py        # SHA256 vs manifest + sigstore best-effort
│   ├── smoke.py         # ORT InferenceSession on each ONNX variant
│   ├── consistency.py   # quantized vs fp32 macro-F1 on dataset slice
│   ├── mirror.py        # HF upload (DEFERRED — see TODO_PUBLISH.md)
│   └── pipeline.py      # click CLI orchestrator
├── tests/
└── artifacts/           # fetched model + manifest.json (gitignored)
```

## Setup (Python 3.12)

```bash
cd packages/convert
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
# full pipeline
python -m nullpii_convert.pipeline all

# stages
python -m nullpii_convert.pipeline fetch
python -m nullpii_convert.pipeline manifest
python -m nullpii_convert.pipeline verify
python -m nullpii_convert.pipeline smoke
python -m nullpii_convert.pipeline consistency
```

## Validation strategy

- **Integrity**: SHA256 of every fetched file recorded in `manifest.json`,
  re-verified by `verify`. If `model.sig` is present and the `sigstore` CLI is
  installed, signature is checked.
- **Smoke**: every ONNX variant is loaded with `onnxruntime.InferenceSession`
  and run against a fixed prompt; output rank/shape/label-count must match
  `id2label` from `config.json`.
- **Consistency**: every quantized variant is scored vs the fp32 baseline on
  50 samples from `ai4privacy/pii-masking-300k`. Macro-F1 divergence must be
  ≤ `MAX_F1_DIVERGENCE` (0.005).

There is **no** torch baseline F1 — the upstream model uses a custom
architecture (`OpenAIPrivacyFilterForTokenClassification`) without public
modeling code, so it cannot be loaded standalone. We trust the upstream
weights and verify cryptographically.

## Tests

```bash
pytest -q
```

## Publish

`mirror.py` uploads to HuggingFace `nullpii/privacy-filter-onnx`. Refuses to
run without both `HUGGING_FACE_HUB_TOKEN` env var and the `--confirm-publish`
flag. Tracked in `TODO_PUBLISH.md`.
