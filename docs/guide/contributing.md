# Contributing

See [CONTRIBUTING.md](https://github.com/lBroth/nullpii/blob/main/CONTRIBUTING.md)
in the repository root for the canonical guide. The short version:

```bash
nvm use            # Node 24 LTS
npm install
npm run build
npm test
npm run lint && npm run typecheck
```

PRs need: green CI, coverage above thresholds (85% lines / 80% branches),
JSDoc on new public APIs, an entry in `CHANGELOG.md` under `[Unreleased]`,
and a Conventional Commits message.

The architecture rules under "Code quality" in `CLAUDE.md` are
non-negotiable: no regex for PII, no cloud calls in the detection step,
no `console.log` in library code, no `any`, no circular imports,
permissive licenses only.
