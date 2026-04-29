# Third-party licenses

Dependency tree is **100% permissive** (MIT / Apache-2.0 / BSD / ISC /
CC0). `npm run license-check` enforces this in CI — any non-permissive
license fails the build.

## Generate the full list on demand

```bash
npm run license-list   # writes THIRD_PARTY_LICENSES.csv
```

CSV has one row per package: name, version, license, repository,
license file path. Not committed (regenerate after `package-lock.json`
changes).

For attribution, see also `LICENSE` and `NOTICE` at the repo root.
