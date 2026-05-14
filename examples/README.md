# nullpii examples

Self-contained scripts. Run any example after building once:

```bash
npm install
npm run build
npx tsx examples/<name>.ts
```

| File | What it shows |
| ---- | ------------- |
| `01-basic.ts`        | Programmatic `sanitize` → `restore` round-trip |
| `02-recognizers.ts`  | Custom regex recognizer + finance/cloud packs |
| `03-rag.ts`          | Sanitize a corpus before indexing for RAG |
| `04-prefetch-ci.ts`  | Programmatic prefetch from CI / Docker build |
| `05-local-model.ts`  | Load the model from a local directory (air-gapped, CI pin, eval) |

## Loading from a local model directory

`NullPii({ modelDir })` skips the HuggingFace download entirely and loads
the unified ONNX from disk. The directory must contain the four-file
manifest the runtime expects:

```
<dir>/
├── model.onnx                 # merged GLiNER, ~1.16 GB FP32
├── tokenizer.json             # GLiNER tokenizer (CLS/SEP/<<ENT>>/<<SEP>>)
├── gliner_config.json
└── tokenizer_config.json
```

CLI equivalents:

```bash
node bin/nullpii.mjs scan      --model-dir /path/to/model "your text"
node bin/nullpii.mjs sanitize  --model-dir /path/to/model "your text"
```

Set `NULLPII_MODEL_DIR=/path/to/model` to override the default location
at runtime (`examples/05-local-model.ts` reads it, the Python bench's
`nullpii_runtime_predictor` reads the same env).
