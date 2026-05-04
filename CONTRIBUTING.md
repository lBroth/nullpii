# Contributing

Thanks for considering a contribution to **nullpii**.

## Local setup

```bash
# Node 24 LTS (see .nvmrc)
nvm use

# Install JS deps
npm install

# Build
npm run build

# Run tests
npm test

# Lint + typecheck (matches CI)
npm run lint
npm run typecheck
```

The eval / training kit (Python 3.12, gitignored) lives under
`packages/eval/`. See `packages/eval/README.md` for setup.

## Architecture rules

These are non-negotiable; PRs that violate them will not be merged.

- **ML-first detection, regex as post-pass.** GLiNER (or `openai/privacy-filter`) is the primary detector. Regex recognizers (`src/recognizers.ts`, `packages/recognizers-*`) run as a post-pass for known formats with low ML coverage (cloud keys, IBAN, Italian CF/PIVA). They never replace the ML pass.
- **No cloud calls** for the detection step. Everything must be offline.
- **No `console.log` in library code.** Use `debug` namespaced loggers; logs carry counts and short ids, never PII values.
- **No `any`.** TypeScript strict mode + `exactOptionalPropertyTypes`.
- **No global mutable state.** Encapsulate state in classes.
- **Short functions, short files.** Split if a function does more than one thing.
- **No circular imports.** `npm run circular-check` runs in CI and in the pre-commit hook.
- **Apache-2.0 / MIT / BSD / ISC / CC0** dependencies only. `npm run license-check` runs in CI.
- **Defaults centralized in `src/defaults.ts`.** Import typed helpers from `src/config.ts` for env access (`hasCudaPath`, `huggingFaceToken`); other modules never touch `process.env` directly.

## Adding a backend

A new ORT-based backend is typically ~20 lines. Extend `OrtBackend`:

```ts
// src/backend/<name>-backend.ts
const MY_CONFIG: BackendConfig = {
  name: 'mybackend',
  executionProviders: [{ name: 'myEP' }, 'cpu'],
  autoVariant: 'fp16',
};
export class MyBackend extends OrtBackend {
  constructor(modelDir: string, variant: ModelVariant = 'auto') {
    super(MY_CONFIG, modelDir, variant);
  }
  async isAvailable(): Promise<boolean> { /* probe driver */ }
}
```

Then:
1. Add a subpath in `package.json` `exports`.
2. Add a `loadBackend` case in `src/router.ts`.
3. Write unit tests under `test/backend/` (lifecycle + platform check).
4. Document in `README.md` (Backends section).

## Tests

- TDD: tests before implementation.
- Every public function needs at least: happy path + edge case + error case.
- Coverage thresholds (CI-enforced): **85% lines, 80% branches**.
- No `test.skip` or `test.only` on `main`.
- Integration tests that need real model artifacts are **gated** on the
  artifact dir existing; they auto-skip in CI.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(backend): add Vulkan execution provider
fix(vault): restore returned wrong replacement count
docs(readme): clarify peerDeps
test(viterbi): cover invalid-transition edge case
chore(deps): bump onnxruntime-node 1.20 → 1.21
refactor(adapters): extract shared chunking helper
perf(tokenizer): cache loaded Tokenizer per modelDir
```

## PR checklist

- [ ] `npm run lint && npm run typecheck && npm test && npm run build` all pass
- [ ] `npm run license-check && npm run circular-check` pass
- [ ] New / changed public APIs have JSDoc with `@param` / `@returns` / `@throws` / `@example`
- [ ] Coverage stays above thresholds
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No PII (real or synthetic-looking) in test output, logs, or fixtures

## Reporting bugs

Open an issue with: a minimal reproduction, the platform / Node version,
the `nullpii` version, and a redacted sample of the input that caused the
issue. **Do not** attach raw PII.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open a public issue for security
problems — use a private channel.
