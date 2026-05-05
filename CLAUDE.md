# NULLPII

Open-source npm library (Apache 2.0) that sanitizes PII from text locally using the `urchade/gliner_multi_pii-v1` GLiNER backbone + 5 per-domain LoRA adapters, with a reversible in-memory vault to restore original values from downstream responses. Backends: CPU, MPS, CUDA.

## Commands

- `npm run build` — build library
- `npm test` — run tests (vitest)
- `npm run lint` — biome
- `npm run typecheck` — tsc --noEmit
- `npm test -- <pattern>` — run single test file

## Architecture

Single npm package `nullpii`. Sources under `src/`, tests under `test/`.
Subpath conditional exports for backends:

```
nullpii                     → core API (sanitize/restore/types/errors)
nullpii/backend/cpu         → CpuBackend (onnxruntime-node)
nullpii/backend/mps         → MpsBackend (CoreMLExecutionProvider)
nullpii/backend/cuda        → CudaBackend
```

`onnxruntime-node` is the only optional peerDependency for runtime.

`packages/eval/` is the Python research kit (eval + training, gitignored — not published to npm).

Internal source layout (strict, no circular):

```
src/types/* → src/{errors,labels-bioes,paths,tokenizer,viterbi}.ts
            → src/backend/{ort-backend,variant}.ts
            → src/backend/{cpu,mps,cuda}-backend.ts → src/cli/*
```

- **PII detection**: ML model only, no regex
- **Execution**: fully local, no cloud calls
- **Vault**: in-memory only, never serialized to disk
- **Modules**: ESM, TypeScript strict mode (`NodeNext`, relative imports use `.js`)

## Code quality

- No hidden errors — fail loud, never swallow exceptions silently
- No duplication — extract shared logic immediately, reuse don't copy
- Short functions — one responsibility, split if doing more than one thing
- Short files — focused modules, split when scope grows
- Structured layout — clear module boundaries, no circular deps
- Early returns over deep nesting (max 3 levels)
- Named constants — no magic numbers/strings
- No `any`, no global mutable state
- Use `debug` package, not `console.log`
- **Defaults centralized** in `src/defaults.ts`. Never write `?? 'auto'`,
  `?? <magic>`, `= 'auto'` inline in feature modules — import from
  `defaults.ts`. Exception: TS `noUncheckedIndexedAccess` fallbacks
  (`arr[i] ?? 0`) are type-system necessities, not user defaults.
- **`process.env` only in `src/config.ts`**. Other modules import typed
  helpers (`hasCudaPath`, `huggingFaceToken`). One file, one audit point.

## Conventions

- TDD: tests before implementation
- Public function: happy path + edge case + error case
- Conventional Commits (feat/fix/test/refactor/docs/chore/perf)
- Named exports only in `index.ts`
- JSDoc on public functions (@param, @returns, @throws, @example)
- SPDX header in source files
- Dependencies: MIT/Apache-2.0/BSD/ISC/CC0 only — never GPL/LGPL/AGPL/SSPL

## Workflow

Status tracked in `PROGRESS.md`. Update it when something material changes.

**Never commit.** User runs git themselves. Do not run `git commit`, `git add`, or `git push`.

## Security

- Never log PII values (log char/span counts only)
- Never persist vault to disk
- Sandbox user-provided file paths
