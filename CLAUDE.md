# NULLPII

Open-source Apache-2.0 stack for local PII sanitization. The core npm
library (`nullpii`) wraps a GLiNER ONNX detection model
(`urchade/gliner_multi_pii-v1` base) + a recognizer pack + an
adversarial-input preprocessor + a reversible in-memory vault. The
companion `@lbroth/nullpii-gateway` package is an HTTP proxy that drops in
front of the Anthropic Messages API and OpenAI-compatible Chat
Completions APIs. Backends: CPU, MPS, CUDA.

## Commands

- `npm run build` — TS compile of the core into `dist/` (the gateway compiles in its own `prepublishOnly` and in its Dockerfile)
- `npm test` / `npm test -- <pattern>` — vitest (covers `test/` and `packages/gateway/test/`; the real-ONNX suite in `test/e2e/` runs only with `npm run test:e2e`)
- `npm run lint` — biome
- `npm run typecheck` — tsc --noEmit (core, gateway, and their tests)
- `npm run gateway:dev` — gateway in tsx watch mode
- `npm run docs:build` — the VitePress site under `docs/`
- The mod's tests: `claude plugin test packages/claude-code-mod`

## Architecture

Monorepo. `nullpii` (root) is the core library — sources `src/`, tests
`test/`. `@lbroth/nullpii-gateway` lives under `packages/gateway/` (Fastify;
exports `buildServer`, `startServer`, `loadConfig`, `printBanner`; its
Docker image is built from `packages/gateway/Dockerfile`).
`packages/claude-code-mod/` is the Claude Code mod, which talks to the
gateway's sidecar API. `onnxruntime-node` is the only optional peer at
runtime for the core. Two recognizer-pack subpackages that used to live
under `packages/recognizers-*/` were folded into core defaults in v0.3.
`docs/` is the documentation site: its pages include the READMEs,
METHOD, SECURITY and the CHANGELOG rather than copy them.

`packages/eval/` is a Python research kit — tracked: `scripts/`, `src/`,
`datasets/`, `published-bench/`, `METHOD.md`, `README.md`,
`pyproject.toml` and the `requirements-*.txt` files; `results/`,
`private/`, `tests/`, `v10-weights/` are gitignored. The public method is
`METHOD.md`; the maintainers' working protocol and log stay in
`private/ab/` and are not published.

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
- Deps: MIT/Apache-2.0/BSD/ISC/CC0 only. One exception, for the eval kit's pipeline lock only (`packages/eval/requirements-pipeline*.txt`, never shipped in a package): `certifi` (MPL-2.0), which huggingface-hub needs through httpx.

## Security

- Never log PII values (counts/short-ids only).
- Never persist vault to disk.
- Sandbox user-provided file paths.
