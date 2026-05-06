# NULLPII

Open-source npm library (Apache 2.0) that sanitizes PII from text locally using `urchade/gliner_multi_pii-v1` GLiNER + 5 per-domain LoRA adapters, with a reversible in-memory vault. Backends: CPU, MPS, CUDA.

## Commands

- `npm run build` — TS compile
- `npm test` / `npm test -- <pattern>` — vitest
- `npm run lint` — biome
- `npm run typecheck` — tsc --noEmit

## Architecture

Single npm package `nullpii`. Sources `src/`, tests `test/`. Subpath conditional exports per backend (`nullpii/backend/{cpu,mps,cuda}`). `onnxruntime-node` is the only optional peerDep at runtime. `packages/eval/` is the Python research kit (gitignored, not published).

- **Detection**: ML model first, recognizer pack post-pass for known formats. No regex-only detection.
- **Execution**: fully local, no cloud calls.
- **Vault**: in-memory only, never serialized.
- **Modules**: ESM, TS strict mode (`NodeNext`, relative imports use `.js`).

## Code rules

- Fail loud — never swallow exceptions silently.
- Short functions, one responsibility.
- Early returns over deep nesting (max 3 levels).
- Named constants — no magic numbers/strings inline.
- No `any`, no global mutable state.
- `debug` package, not `console.log`.
- Defaults in `src/defaults.ts`. `process.env` via typed helpers in `src/config.ts` only.
- Conventional Commits. Named exports only in `index.ts`. JSDoc on public functions. SPDX header in source files.
- Deps: MIT/Apache-2.0/BSD/ISC/CC0 only.

## Workflow

**Never commit.** User runs git themselves — do not run `git commit`, `git add`, or `git push`.

## Security

- Never log PII values (counts/short-ids only).
- Never persist vault to disk.
- Sandbox user-provided file paths.
