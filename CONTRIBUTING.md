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

## Release checklist

Before tagging a new version:

1. **Version bump.** `package.json.version` matches the topmost section of `CHANGELOG.md`. Bump SemVer per breaking / feature / fix.
2. **Clean build.** `npm run clean && npm run build` (the `prebuild` hook runs `clean` automatically). Confirms no orphan `dist/*.js` from deleted `src/` files.
3. **Pack inspection.** `npm pack --dry-run`. Verify every shipped file is intentional:
   - Only `dist/`, `src/`, `README.md`, `LICENSE`, `NOTICE`, `bin/` are listed (the `package.json:files` whitelist).
   - `dist/backend/` contains **only** `unified-backend.{js,d.ts,*.map}`.
   - No compiled outputs from removed modules (`distiluse-encoder`, `router-embedding`, `multi-backend`, `cpu/mps/cuda-backend`, `ort-backend`, `variant`, `router`).
   - `tarball size` under 1 MB (sanity — model weights ship via HF, not npm).
4. **Full quality bar.** `npm run lint && npm run typecheck && npm test && npm run license-check && npm run circular-check`. All must pass on the release commit.
5. **SBOM refresh.** `npm run sbom` regenerates `bom.json` with the current dep tree + timestamp.
6. **Bench refresh.** If the runtime pipeline changed (recognizer pack, normalize, base64 decoder, dedupe, vault), rerun `packages/eval/scripts/bench_full.py` with the canonical tool set and copy the matrix/confusion into `packages/eval/published-bench/`. Update the README headline F1 if the number moved.
7. **Tag + publish.** `git tag vX.Y.Z` then `npm publish --provenance` (the `publishConfig.provenance: true` in `package.json` requires running from a supported CI provider).
