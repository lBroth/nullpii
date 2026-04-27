# nullpii examples

Self-contained scripts. Run any example after building once:

```bash
npm install
npm run build
npx tsx examples/<name>.ts
```

| File | What it shows |
| ---- | ------------- |
| `01-basic.ts`              | Programmatic `sanitize` → `restore` round-trip |
| `02-anthropic.ts`          | `withNullPii(client)` for `@anthropic-ai/sdk` |
| `03-multi-turn.ts`         | `conversationKey` keeps the vault across turns |
| `04-streaming.ts`          | Streaming response with cross-chunk placeholder buffer |
| `05-recognizers.ts`        | Custom regex recognizer + finance/cloud packs |
| `06-rag.ts`                | Sanitize a corpus before indexing for RAG |
| `07-prefetch-ci.ts`        | Programmatic prefetch from CI / Docker build |
