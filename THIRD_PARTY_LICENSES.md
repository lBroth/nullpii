# Third-party licenses

The dependency tree is **100% permissive** (MIT / Apache-2.0 / BSD /
ISC / CC0). Verified by `npm run license-check` in CI — the script
fails the build on the first non-permissive license.

## How to regenerate the full list

```bash
npm run license-list   # writes THIRD_PARTY_LICENSES.csv
```

`license-checker` runs against the production dependency closure
(`--production --excludePrivatePackages`) and emits a CSV with one
row per package: name, version, license, repository, license file
path. Open the CSV in any viewer for human review.

The CSV is intentionally **not committed** — it goes stale every
`package-lock.json` bump. Generate on demand.

## Why no curated table here

The previous hand-curated table drifted out of date with every dep
bump. The CI `license-check` script is the source of truth: a build
either passes (all permissive) or fails (someone introduced a
copyleft dep — fix or remove). For attribution detail, use the CSV
output above + `LICENSE` / `NOTICE` at the repo root.
