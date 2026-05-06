# Contributing

## Setup

```bash
nvm use            # Node 24 LTS (.nvmrc)
npm install
npm run build
npm test
npm run lint && npm run typecheck
```

Eval kit (Python 3.12, gitignored from npm publish): `cd packages/eval && python3.12 -m venv .venv && pip install -e ".[presidio]"`. See `packages/eval/README.md`.

## Architecture rules

Non-negotiable — PRs that violate these will not be merged.

- **ML-first detection, regex as post-pass.** GLiNER is the primary detector; recognizers run after, never replace.
- **No cloud calls** for detection.
- **No `console.log`** in library code — use `debug` namespaced loggers (counts/ids only, never PII values).
- **No `any`.** TS strict mode + `exactOptionalPropertyTypes`.
- **No global mutable state.**
- **No circular imports.** `npm run circular-check` in CI + pre-commit.
- **Defaults centralised in `src/defaults.ts`.** `process.env` only via typed helpers in `src/config.ts`.
- **Apache-2.0 / MIT / BSD / ISC / CC0 deps only.** `npm run license-check` in CI.

## Tests

- TDD — tests before implementation.
- Public function = happy path + edge case + error case.
- Coverage thresholds (CI-enforced): 85% lines, 80% branches.
- Hardware-gated tests (CUDA/MPS) auto-skip when probe fails.

## Commits + PR

Conventional Commits (`feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`).

PR gate: `lint`, `typecheck`, `test`, `build`, `license-check`, `circular-check`, `sbom` — all must pass. New public API needs JSDoc (`@param`, `@returns`, `@throws`, `@example`).

## Bug reports

Open an issue with: minimal repro, platform / Node version, nullpii version, redacted input. **Do not** attach raw PII.

## Security issues

See [SECURITY.md](SECURITY.md). Use the GitHub Security Advisory channel — do not open a public issue.
