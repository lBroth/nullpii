# NULLPII

Open-source Apache-2.0 stack for local PII sanitization. The core npm
library (`nullpii`) wraps a GLiNER ONNX detection model
(`urchade/gliner_multi_pii-v1` base) + a recognizer pack + an
adversarial-input preprocessor + a reversible in-memory vault. The
companion `@lbroth/nullpii-gateway` package is an HTTP proxy that drops in
front of the Anthropic Messages API. Backends: CPU, MPS, CUDA.

## Commands

- `npm run build` — TS compile (root + gateway)
- `npm test` / `npm test -- <pattern>` — vitest (covers `test/` and `packages/gateway/test/`)
- `npm run lint` — biome
- `npm run typecheck` — tsc --noEmit
- `npm run gateway:dev` — gateway in tsx watch mode

## Architecture

Monorepo. `nullpii` (root) is the core library — sources `src/`, tests
`test/`. `@lbroth/nullpii-gateway` lives under `packages/gateway/` (Fastify;
exports `buildServer`, `startServer`, `RestoreStream`). `onnxruntime-node`
is the only optional peer at runtime for the core. Two recognizer-pack
subpackages that used to live under `packages/recognizers-*/` were
folded into core defaults in v0.3.

`packages/eval/` is a Python research kit — only `scripts/`, `src/`,
`datasets/`, `published-bench/`, top-level READMEs are tracked;
`results/`, `private/`, `tests/`, `v10-weights/` are gitignored.

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
- Defaults in `src/defaults.ts`. Env reads go through `readEnvVar(NAME)` in `src/config.ts` only — declare the env-var name as an exported `const` in `src/config.ts`, never inline `process.env.X` at call sites. One-line per-var wrappers are unnecessary duplication; pass the const to `readEnvVar` instead.
- Conventional Commits. Named exports only in `index.ts`. JSDoc on public functions. SPDX header in source files.
- Deps: MIT/Apache-2.0/BSD/ISC/CC0 only.

## Security

- Never log PII values (counts/short-ids only).
- Never persist vault to disk.
- Sandbox user-provided file paths.
