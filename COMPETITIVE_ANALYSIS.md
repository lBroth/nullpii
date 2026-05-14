# Bench methodology + bare-mode contract

Bench surface, bare-mode rules, and the `CLAIM-VERIFIER-01` finding behind nullpii's per-tool comparison numbers. Per-dataset F1 lives at [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv); README [`README.md`](README.md) summarises.

## Bench surface (`packages/eval/scripts/bench_full.py`)

6 tools × 16 datasets, single matrix, single code revision, IoU ≥ 0.5 macro F1, partial-match span scoring, fair-serial `--parallel-tools 1` cap=5 000. **Headline macro = 5 OOD multilingual datasets** (`nemotron-pii-test` excluded; `ai4privacy-300k-heldout` shown but excluded from the headline — see below).

| Tool | Wrapping |
|---|---|
| `nullpii` | local npm CLI (`node bin/nullpii.mjs scan --ndjson`) — canonical user-facing row |
| `presidio` | **Microsoft Presidio Analyzer** — bare upstream defaults |
| `nemotron-pii-raw` | **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`) — bare upstream + 55→8 label remap |
| `piiranha` | `iiiorg/piiranha-v1-detect-personal-information` — bare upstream defaults |
| `deberta` | `lakshyakh93/deberta_finetuned_pii` — community fine-tune of **Microsoft DeBERTa-v3** |
| `gliner-pii-large-v1` | `knowledgator/gliner-pii-large-v1.0` — bare HF |

## Bare-mode contract

No competitor row wraps `boundary_refined`, `never_pii_filter`, `url_filter`, `regex_pack`, `_normalize_for_detection` (NFKC + unidecode + zero-width strip + HTML entity decode + URL %XX decode + spaced-PII despace), or `base64-detector`. Each tool runs as its upstream project intends.

The only adapter glue applied uniformly to every row, including `nullpii`:

- **Chunking 1400/200 char stride** — every ML tool has a ~384-token context limit (nullpii's `MAX_SEQUENCE_LENGTH`), so long documents like TAB ECHR (avg 2000+ tokens) must be split + dedupe.
- **Per-tool label remap** to nullpii's 8-class schema. Microsoft Presidio emits `PERSON` / `EMAIL_ADDRESS` / `LOCATION`; NVIDIA Nemotron emits 55 fine-grained labels (`first_name`, `ssn`, `mrn`, …); Microsoft DeBERTa fine-tune emits `PER` / `LOC` / `ORG`. Bench predictor wrappers translate native labels to the 8-class schema **before** F1 comparison. Symmetric — every cross-tool NER bench needs it; not a nullpii advantage.

## Datasets in scope (16, canonical surface = 7 + 2 reference rows)

Canonical 7 datasets that contribute to the public macros:

`nullpii-bench` (unified 2 421-row project corpus: bundled OOD + 6 self-authored preprocessor-regression subsets + 5 TextAttack perturbation slices) · `tab-echr` · `presidio-synthetic` · `isotonic-{en,de,fr,it}-heldout` (offset 100k+, multilingual).

The unified v0.2 model is trained on a permissive-only corpus (Nemotron-PII CC-BY-4.0 + TAB/ECHR MIT + project Faker Apache-2.0 + Presidio synthetic MIT + cc-negative regularizer). 2 of the 7 are **in-distribution diagnostic** for nullpii: `nullpii-bench` ⚠ self-authored (project preprocessor regression / TextAttack on project PII pool — exercises the recognizer pack + adversarial preprocessor + base64 decoder, not OOD generalisation) and `tab-echr` (the unified adapter ingests the TAB train split). Per-row ⚠ flags in the README table; held-out OOD multilingual macro F1 (5 rows) = 0.7907.

Reference rows shown in the table but **excluded from every macro**:

- `ai4privacy-300k-heldout` †  — ai4privacy is licence-gated (commercial use requires `licensing@ai4privacy.com`) and is **excluded from v0.2 training entirely**. The model has zero exposure to its distribution. Score (0.3857) is shown for transparency; treat as ultra-OOD.
- `nemotron-pii-test` ⚠ — simultaneous self-bench for `nemotron-pii-raw` (same training distribution as that tool); the row reports both nullpii's number and the upstream baseline but cannot fairly enter a macro that compares them.

Full 16-dataset matrix (incl. `ai4privacy-{400k,300k}` raw splits, `isotonic-{en,de,fr,it}` raw splits, `argilla-pii`) lives at `packages/eval/results/overnight-local-20260514/matrix.csv`. Two known nullpii losses on that extended surface: `ai4privacy-400k` (piiranha 0.95 vs nullpii 0.59 — piiranha trained on it; nullpii did not, by licence) and `argilla-pii` (deberta 0.65 vs nullpii 0.56).

`presidio-synthetic` is also a self-bench for `presidio` (same generator) — § footnote in the README table.

## CLAIM-VERIFIER-01

Vendor F1 numbers `Presidio 0.85+` and `piiranha 0.99+` are **not reproducible** under standard span-NER methodology (IoU ≥ 0.5, label-agnostic boundary scoring, seqeval). The verification harness is at `packages/eval/scripts/verify_claims.py`. Both vendors quote per-token / per-class metrics that don't translate to span-level recall/precision.

Concretely, on `presidio-synthetic` (Presidio's own data), the v0.2 bench numbers are: `presidio` 0.5746 / `piiranha` 0.3828 / `gliner-pii-large-v1` 0.6319 / `nemotron-pii-raw` 0.6182 / `nullpii` **0.9184** — all the upstream baselines far below 0.85.

## Reproducer

```bash
NULLPII_MODEL_DIR=packages/eval/results/release/onnx-unified-aug2 \
python -u packages/eval/scripts/bench_full.py \
  --tools nullpii,deberta,piiranha,presidio,gliner-pii-large-v1,nemotron-pii-raw \
  --datasets all \
  --backend cpu --confusion \
  --out-dir packages/eval/results/$(date +%Y%m%d)-bench
```
