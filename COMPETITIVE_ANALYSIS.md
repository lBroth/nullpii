# Bench methodology + bare-mode contract

Bench surface, bare-mode rules, and the `CLAIM-VERIFIER-01` finding behind nullpii's per-tool comparison numbers. Per-dataset F1 lives at [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv); README [`README.md`](README.md) summarises.

## Bench surface (`packages/eval/scripts/bench_full.py`)

7 tools × 9 datasets, single matrix, single code revision, IoU ≥ 0.5 macro F1, partial-match span scoring, fair-serial `--parallel-tools 1` cap=5 000. **Headline macro = 8 datasets** (`nemotron-pii-test` excluded — see below).

| Tool | Wrapping |
|---|---|
| `nullpii` | local npm CLI (`node bin/nullpii.mjs scan --ndjson`) — canonical user-facing row |
| `presidio` | **Microsoft Presidio Analyzer** — bare upstream defaults |
| `nemotron-pii-raw` | **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`) — bare upstream + 55→8 label remap |
| `piiranha` | `iiiorg/piiranha-v1-detect-personal-information` — bare upstream defaults |
| `deberta` | `lakshyakh93/deberta_finetuned_pii` — community fine-tune of **Microsoft DeBERTa-v3** |
| `gliner-onnx-pii-fp32` | bare HF inference of `urchade/gliner_multi_pii-v1` (GLiNER, Zaratiana et al., NAACL 2024) |
| `gliner-pii-large-v1` | `knowledgator/gliner-pii-large-v1.0` — bare HF |

## Bare-mode contract

No competitor row wraps `boundary_refined`, `never_pii_filter`, `url_filter`, `regex_pack`, or `_normalize_for_detection` (NFKC + unidecode + zero-width strip + HTML entity decode + URL %XX decode + spaced-PII despace). Each tool runs as its upstream project intends.

The only adapter glue applied uniformly to every row, including `nullpii`:

- **Chunking 1400/200 char stride** — every ML tool has a ~512-token context limit, so documents like TAB ECHR (avg 2000+ tokens) must be split + dedupe.
- **Per-tool label remap** to nullpii's 8-class schema. Microsoft Presidio emits `PERSON` / `EMAIL_ADDRESS` / `LOCATION`; NVIDIA Nemotron emits 55 fine-grained labels (`first_name`, `ssn`, `mrn`, …); Microsoft DeBERTa fine-tune emits `PER` / `LOC` / `ORG`. Bench predictor wrappers translate native labels to the 8-class schema **before** F1 comparison. Symmetric — every cross-tool NER bench needs it; not a nullpii advantage.

## Datasets in scope (9)

`nullpii-bench` (unified 2 421-row project corpus: bundled OOD + 6 self-authored preprocessor-regression subsets + 5 TextAttack perturbation slices) · `tab-echr` · `nemotron-pii-test` · `presidio-synthetic` · `ai4privacy-300k-heldout` (offset 100k+) · `isotonic-{en,de,fr,it}-heldout` (offset 100k+, multilingual).

3 of these 9 rows are **in-distribution diagnostic** for nullpii (adapters trained on slices): `nullpii-bench` ⚠ self-authored, `tab-echr` (legal adapter trained on TAB train), `nemotron-pii-test` (enterprise adapter trained on Nemotron train). Per-row ⚠ flags in the README table; held-out OOD multilingual F1 (6 rows) = 0.7662.

`nemotron-pii-test` is **excluded from headline macro** (double disqualification: in-distribution for nullpii AND simultaneous self-bench for `nemotron-pii-raw`). Headline macro = 8 datasets. `nullpii-bench` and `tab-echr` remain in the diagnostic aggregate with explicit ⚠ disclosure.

`presidio-synthetic` is also a self-bench for `presidio` (same generator). `nemotron-pii-test` is a self-bench for `nemotron-pii-raw` (same training distribution).

## CLAIM-VERIFIER-01

Vendor F1 numbers `Presidio 0.85+` and `piiranha 0.99+` are **not reproducible** under standard span-NER methodology (IoU ≥ 0.5, label-agnostic boundary scoring, seqeval). The verification harness is at `packages/eval/scripts/verify_claims.py`. Both vendors quote per-token / per-class metrics that don't translate to span-level recall/precision.

Concretely, on `presidio-synthetic` (Presidio's own data), bench numbers are: `presidio` 0.5737 / `nullpii` 0.6050 / `nemotron-pii-raw` 0.6184 / `gliner-pii-large-v1` 0.6323 — all far below 0.85.

## Reproducer

```bash
NULLPII_MODEL_DIR=/tmp/nullpii-stack-test \
python -u packages/eval/scripts/bench_full.py \
  --tools nullpii,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1 \
  --datasets nullpii-bench,tab-echr,nemotron-pii-test,presidio-synthetic,ai4privacy-300k-heldout,isotonic-en-heldout,isotonic-de-heldout,isotonic-fr-heldout,isotonic-it-heldout \
  --backend cpu --confusion --max-per-dataset 5000 --parallel-tools 1 \
  --out-dir packages/eval/results/$(date +%Y%m%d)-bench
```
