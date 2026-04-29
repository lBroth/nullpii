# TODO — Deferred publish & gated tests

All external publishes deferred until local build + test of full project
complete. Do NOT execute until user explicitly approves.

## npm — automated by `release.yml` on tag push

The `release.yml` workflow gates → publishes to npm with provenance →
creates GitHub Release. Trigger by pushing a `v*.*.*` tag whose value
matches `package.json` `version` (workflow asserts this and refuses
otherwise).

- [ ] Bump `package.json` `version` to `1.0.0`
- [ ] Update `CHANGELOG.md` — replace `[Unreleased]` with `[1.0.0] — YYYY-MM-DD`
- [ ] Create + push tag: `git tag v1.0.0 && git push origin v1.0.0`
- [ ] Watch `Actions` tab — `release.yml` will publish + create the Release

## GitHub

- [ ] Push branch + tags to `lBroth/nullpii`
- [ ] Create GitHub Release v1.0.0 with the CHANGELOG entry as body
- [ ] Repo Settings → **Pages** → Source: **GitHub Actions** (one-time)
      — `docs.yml` then auto-deploys on every push to `main` that
      touches `docs/**` or `README.md`. Final URL:
      `https://lbroth.github.io/nullpii/` (matches
      `vitepress.config.ts > base: '/nullpii/'`)
- [ ] Repo Settings → **Secrets**: add `HF_TOKEN`, `NPM_TOKEN`
- [ ] Manually run `model-convert` workflow when ready to mirror

## HuggingFace

- [ ] Create org/repo `nullpii/privacy-filter-onnx`
- [ ] Mirror upstream artifacts: ONNX (fp32/fp16/int8/int4/int4f16),
      tokenizer.json, config.json, viterbi_calibration.json + SHA256 sidecars
- [ ] Verify pinned revision still resolves to the mirrored repo
- [ ] Publish `lBroth/nullpii-gliner-pii-v2` (PT + ONNX FP32 + ONNX INT4 +
      tokenizer + model card). Recipe under
      `scripts/release/push-to-hf.sh`.

## Gated tests (require hardware / browser / external host)

- [ ] **CUDA backend**: integration test on Linux + NVIDIA runner
- [ ] **ROCm backend**: integration test on Linux + AMD runner
- [ ] **MPS backend benchmark**: ONNX op coverage in `CoreMLExecutionProvider`
      improves → re-bench, expect MPS to overtake CPU
- [ ] **Full v2 bench (n≥5k per dataset)**: graduate the multilingual F1
      preview from `eval-results.md` to a stable bench row with
      confidence intervals.

## Verification post-publish

- [ ] `npm view nullpii` shows 1.0.0 and the right `exports` map
- [ ] `npm install nullpii` works clean
- [ ] Docs site live
- [ ] README badges resolve
