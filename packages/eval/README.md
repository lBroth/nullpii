# nullpii eval

Internal research kit. Python 3.12, gitignored — not part of the npm publish surface. Powers the v10 release bench (see [`docs/v10/V10_PLAN.md`](../../docs/v10/V10_PLAN.md)) and per-domain LoRA training.

## Setup

```bash
cd packages/eval
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
```

## Bench

`scripts/bench_full.py` runs a `tool × dataset` matrix with checkpoint resume. Output: `matrix.json` (per-cell F1 / wall / throughput) + `matrix.csv` (pivot).

```bash
# Release-candidate routers across 19 PII-native datasets (default caps).
python -u scripts/bench_full.py \
  --tools nullpii-v10-router-embedding,nullpii-v10-router-xlmr \
  --datasets all \
  --backend cpu \
  --out-dir results/bench-v10-release-local
```

Override caps with `--max-per-dataset N` (global cap) or `--no-cap` (full).

### Tool surface

Two nullpii routers + nine bare baselines + three opt-in cloud rows. None of the bare rows wrap nullpii post-processing. See [`COMPETITIVE_ANALYSIS.md`](../../COMPETITIVE_ANALYSIS.md) for the full list and methodology.

### Dataset surface

19 PII-native canonical datasets. Listed in [`docs/v10/V10_PLAN.md`](../../docs/v10/V10_PLAN.md) "Release gating" with rationale for the 5 excluded rows (wikiann × 3, adversarial-decoys, composite nullpii-adversarial).

## Other scripts

| Script | Purpose |
|---|---|
| `scripts/bench_latency.py` | Per-tool latency p50/p95 measurements |
| `scripts/bench_openai_decoders.py` | naive HF / BIOES / Viterbi delta on `openai/privacy-filter` |
| `scripts/failure_analysis.py` | Top-K FN/FP per label per tool |
| `scripts/report_per_class.py` | Per-label precision/recall breakdown |
| `scripts/generate_adversarial_bench.py` | Synthesize `nullpii-adversarial.jsonl` |
| `scripts/generate_textattack_adversarial.py` | TextAttack-perturbed corpus from ai4privacy 0–500 |
| `scripts/generate_dev_paste_synth.py` | Faker-based dev-paste synthetic train data |
| `scripts/sample_cc_negative.py` | Common Crawl negative-class sampler |
| `scripts/meddocan_loader.py` | MEDDOCAN loader (medical Spanish) |
| `scripts/train/prepare_v10_corpora.py` | Build per-domain training corpora |
| `scripts/train/build_router_embeddings.py` | Build distiluse prototype vectors |
| `scripts/train/build_nemotron_corpus.py` | Convert `nvidia/Nemotron-PII` train → GLiNER format |
| `scripts/train/build_us_formats_corpus.py` | Faker-based US-format synthetic corpus |
| `scripts/train/qualitative_compare.py` | Side-by-side span comparison across tools |

## Bundled datasets

`datasets/` (Apache 2.0, project-internal):

| File | n | Notes |
|---|--:|---|
| `nullpii-bench.jsonl` | 264 | Project-bundled OOD bench (curated + long real-world prompts) |
| `tab-echr-test.jsonl` | 127 | TAB ECHR test split (legal, EU court rulings) |
| `nullpii-adversarial.jsonl` | 480 | 6 subsets: typo / unicode / whitespace / encoding / decoys / code |
| `nullpii-adversarial-textattack.jsonl` | 1670 | TextAttack-perturbed ai4privacy 0–500 |
| `dev-paste-synth-train.jsonl` | ~30k | Synthetic dev-paste training corpus (Faker) |
| `cc-negative-25k.jsonl` | 25k | Common Crawl negative-class samples |
| `cc-negative-200-test.jsonl` | 200 | CC-neg validation slice |

External datasets (loaded on demand by `nullpii_eval.public_datasets`): `ai4privacy/pii-masking-300k`, `ai4privacy/pii-masking-400k`, `Isotonic/pii-masking-200k`, `argilla/textcat-tokencat-pii-per-domain`, `nvidia/Nemotron-PII`, `presidio-research/presidio-synthetic`.

## v10 LoRA training

Per-domain adapters (~3.4 MB each) trained on `urchade/gliner_multi_pii-v1` with `peft` LoRA targeting `q_proj`/`k_proj`/`v_proj` of the inner mDeBERTa encoder. See [`docs/v10/V10_JOURNAL.md`](../../docs/v10/V10_JOURNAL.md) for the full training recipe and lessons learned.
