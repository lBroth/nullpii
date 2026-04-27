# Third-party licenses

Auto-collated for human review. Regenerate with:

```bash
npx license-checker --production --excludePrivatePackages --csv > /tmp/js.csv
cd packages/convert && .venv/bin/pip-licenses --format=csv > /tmp/py.csv
```

## Status legend

| Status | Meaning                                                              |
| ------ | -------------------------------------------------------------------- |
| ✅     | Permissive (MIT / Apache-2.0 / BSD / ISC / CC0 / PSF / 0BSD)         |
| 🟡     | Weak copyleft (MPL-2.0) — file-level, commercial use OK              |
| ⚠️     | LGPL — dynamic linking only, attribution required                    |
| ⛔     | GPL / AGPL / SSPL — **forbidden** in this project                    |

Quick scan: every entry must be ✅ or 🟡. Any ⚠️ blocks merge to main.
Any ⛔ blocks release.

---

## JavaScript runtime — `dependencies` + reachable peer transitive (41)

The list end-users actually receive when they `npm install nullpii`,
plus the optional peers `onnxruntime-node`, `@anthropic-ai/sdk`,
`@anthropic-ai/sdk`. **100% permissive.** Zero LGPL.

| Package                                          | License             | Status |
| ------------------------------------------------ | ------------------- | ------ |
| `@anthropic-ai/sdk@0.91.1`                       | MIT                 | ✅     |
| `@anush008/tokenizers@0.6.0`                     | MIT                 | ✅     |
| `@anush008/tokenizers-darwin-universal@0.6.0`    | MIT                 | ✅     |
| `@babel/runtime@7.29.2`                          | MIT                 | ✅     |
| `@types/node@22.19.17`                           | MIT                 | ✅     |
| `adm-zip@0.5.17`                                 | MIT                 | ✅     |
| `ansi-regex@5.0.1`                               | MIT                 | ✅     |
| `boolean@3.2.0`                                  | MIT                 | ✅     |
| `chalk@5.6.2`                                    | MIT                 | ✅     |
| `cli-progress@3.12.0`                            | MIT                 | ✅     |
| `commander@14.0.3`                               | MIT                 | ✅     |
| `debug@4.4.3`                                    | MIT                 | ✅     |
| `define-data-property@1.1.4`                     | MIT                 | ✅     |
| `define-properties@1.2.1`                        | MIT                 | ✅     |
| `detect-node@2.1.0`                              | MIT                 | ✅     |
| `emoji-regex@8.0.0`                              | MIT                 | ✅     |
| `es-define-property@1.0.1`                       | MIT                 | ✅     |
| `es-errors@1.3.0`                                | MIT                 | ✅     |
| `es6-error@4.1.1`                                | MIT                 | ✅     |
| `escape-string-regexp@4.0.0`                     | MIT                 | ✅     |
| `global-agent@3.0.0`                             | BSD-3-Clause        | ✅     |
| `globalthis@1.0.4`                               | MIT                 | ✅     |
| `gopd@1.2.0`                                     | MIT                 | ✅     |
| `has-property-descriptors@1.0.2`                 | MIT                 | ✅     |
| `is-fullwidth-code-point@3.0.0`                  | MIT                 | ✅     |
| `json-schema-to-ts@3.1.1`                        | MIT                 | ✅     |
| `json-stringify-safe@5.0.1`                      | ISC                 | ✅     |
| `matcher@3.0.0`                                  | MIT                 | ✅     |
| `ms@2.1.3`                                       | MIT                 | ✅     |
| `object-keys@1.1.1`                              | MIT                 | ✅     |
| `onnxruntime-common@1.24.3`                      | MIT                 | ✅     |
| `onnxruntime-node@1.24.3`                        | MIT                 | ✅     |
| `roarr@2.15.4`                                   | BSD-3-Clause        | ✅     |
| `semver@7.7.4`                                   | ISC                 | ✅     |
| `semver-compare@1.0.0`                           | MIT                 | ✅     |
| `serialize-error@7.0.1`                          | MIT                 | ✅     |
| `sprintf-js@1.1.3`                               | BSD-3-Clause        | ✅     |
| `string-width@4.2.3`                             | MIT                 | ✅     |
| `strip-ansi@6.0.1`                               | MIT                 | ✅     |
| `ts-algebra@2.0.0`                               | MIT                 | ✅     |
| `type-fest@0.13.1`                               | MIT OR CC0-1.0      | ✅     |
| `undici-types@6.21.0`                            | MIT                 | ✅     |

---

## Python — `packages/convert/` build-time pipeline (66)

Used only by maintainers running the conversion / verification pipeline.
**Not shipped to end-users.**

All permissive except two file-level MPL-2.0 components (🟡):
- `certifi` — TLS root certificates. MPL-2.0 imposes obligation only on
  modifications to `certifi`'s own source files, which we don't make.
- `tqdm` — dual-licensed MPL-2.0 AND MIT; we use under MIT.

Full list rendered from `pip-licenses` (66 packages):
see `/tmp/py-licenses.csv` after regeneration. Highlights:

| Package                       | License                                   | Status |
| ----------------------------- | ----------------------------------------- | ------ |
| `huggingface_hub@0.36.2`      | Apache-2.0                                | ✅     |
| `tokenizers@0.22.2`           | Apache-2.0                                | ✅     |
| `transformers@4.57.6`         | Apache-2.0                                | ✅     |
| `onnx@1.21.0`                 | Apache-2.0                                | ✅     |
| `onnxruntime@1.25.0`          | MIT                                       | ✅     |
| `optimum@2.1.0`               | Apache-2.0                                | ✅     |
| `coremltools@9.0`             | BSD                                       | ✅     |
| `torch@2.11.0`                | BSD-3-Clause                              | ✅     |
| `numpy@2.2.6`                 | BSD                                       | ✅     |
| `scipy@1.17.1`                | BSD                                       | ✅     |
| `scikit-learn@1.8.0`          | BSD-3-Clause                              | ✅     |
| `pandas@3.0.2`                | BSD                                       | ✅     |
| `pyarrow@24.0.0`              | Apache-2.0                                | ✅     |
| `protobuf@7.34.1`             | BSD-3-Clause                              | ✅     |
| `safetensors@0.7.0`           | Apache-2.0                                | ✅     |
| `requests@2.33.1`             | Apache-2.0                                | ✅     |
| `httpx@0.28.1`                | BSD                                       | ✅     |
| `aiohttp@3.13.5`              | Apache-2.0 AND MIT                        | ✅     |
| `regex@2026.4.4`              | Apache-2.0 AND CNRI-Python                | ✅     |
| `Jinja2@3.1.6`                | BSD                                       | ✅     |
| `MarkupSafe@3.0.3`            | BSD-3-Clause                              | ✅     |
| `click@8.3.3`                 | BSD-3-Clause                              | ✅     |
| `pytest@9.0.3`                | MIT                                       | ✅     |
| `ruff@0.15.12`                | MIT                                       | ✅     |
| `certifi@2026.4.22`           | MPL-2.0                                   | 🟡     |
| `tqdm@4.67.3`                 | MPL-2.0 AND MIT                           | 🟡 (use MIT) |
| (~40 more)                    | MIT / Apache-2.0 / BSD / ISC / PSF / PD   | ✅     |

---

## Model

| Artifact               | License    | Source                                         | Status |
| ---------------------- | ---------- | ---------------------------------------------- | ------ |
| `openai/privacy-filter`| Apache-2.0 | https://huggingface.co/openai/privacy-filter   | ✅     |

---

## What to look at

1. **Run `npm run license-check`** (CI also runs it on every push).
   Should report success with no LGPL/GPL output.
2. **Confirm every JS row is ✅** — runtime tree is now 100% permissive.
3. **Two Python entries (🟡)** are MPL-2.0 build-time only:
   - `certifi`: TLS roots, no source modifications by us.
   - `tqdm`: dual-licensed; we use under MIT.
4. **Model**: `openai/privacy-filter` Apache-2.0 confirmed.

## Removed before 1.0

- **`@huggingface/transformers`** (Apache-2.0) → removed because its
  transitive `sharp` → `@img/sharp-libvips-*` is **LGPL-3.0-or-later**.
  Eliminating it dropped the runtime tree from 68 packages to 41 and
  brought it to 100% permissive. Side-effect: WebGPU backend removed
  from the public API. May return when an LGPL-free browser ONNX path
  is available.
