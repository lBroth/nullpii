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
| `05-recognizers.ts`  | Custom regex recognizer + finance/cloud packs |
| `06-rag.ts`          | Sanitize a corpus before indexing for RAG |
| `07-prefetch-ci.ts`  | Programmatic prefetch from CI / Docker build |
