# nullpii eval

The benchmark kit behind nullpii's published numbers. Python 3.12. Not part of the npm packages.

How the benchmark works, what it shows and what it does not: [`METHOD.md`](METHOD.md). This page is about running it.

## Setup

```bash
cd packages/eval
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Some competitors pin library versions that conflict, so they run from their own environments: Presidio from [`requirements-presidio.txt`](requirements-presidio.txt), OpenMed from [`requirements-openmed.txt`](requirements-openmed.txt), and the GLiNER tools from an environment with `gliner` 0.2.29 and `transformers` 5.

## Run a tool on a dataset

```bash
python scripts/bench_full.py --tools gliner-pii-large-v1 --datasets r3-redact --backend cuda --out-dir results/run
```

`bench_full.py` writes one checkpoint of per-document spans per tool and dataset (`results/run/checkpoints/<tool>-<dataset>.jsonl`). nullpii itself is captured from its npm build with `scripts/ab/score_capture.mjs`, so the scored spans are exactly what the library returns.

The report-set datasets are rebuilt from their publishers by `scripts/r3/build_r3.py` and checked against the SHA-256 recorded in `bench_full.py`; the selection rules are in [`scripts/r3/CRITERIA.md`](scripts/r3/CRITERIA.md). The coding-agent traces come from `scripts/r3/traces_v3_gen/`, which regenerates the frozen file from its seed.

## Score and compare

```bash
python scripts/ab/char_metrics.py --results results/run --datasets r3-redact,r3-tonic-human,r3-piilo,r3-eu-clinical,r3-traces-v3 \
  --baseline nullpii --mask-all --out char.json
python scripts/ab/r2_verdict.py --report char.json --baseline nullpii --better-row
```

- `char_metrics.py`: character-level recall, precision and F-scores with paired bootstrap CIs; `--language`, `--cluster-rows` and `--exclude` for the breakdowns and sensitivity checks.
- `core_filter.py`: nullpii with every category masked, filtered to the core labels.
- `tune_operating_point.py` and `threshold_sim.py`: a competitor's operating point on the tuning set.
- `openmed_no_output.py`: the texts OpenMed returned no output for.
- `overlap_check.py`: shingle overlap between a dataset and training or tuning text.
- `piimb_score.py`: PIIMB with the leaderboard's own scoring.

## Benchmark pipeline

`scripts/bench_pipeline.py` scores nullpii again on AB-1, R3 and PIIMB, in its two published configurations (`default`, what a user gets without configuring anything, and `everything`, every category masked), next to every other tool's predictions from the published run, which are frozen rather than run again. It uses the scorers above with the published run's own recipe (`scripts/pipeline/recipe.py`).

The frozen inputs (the sets, every tool's per-document predictions, the published run's scoring outputs) are in a private Hugging Face dataset, pinned to a revision in `scripts/pipeline/settings.py`; it holds real secrets and data that may not be passed on, so no step prints a row. Install the extra with `pip install -e '.[pipeline]'`, and give a token with read access (`HF_TOKEN`, or `hf auth login`).

```bash
python scripts/bench_pipeline.py fetch --frozen F --download          # download, check every file's SHA-256, install the sets under results/
python scripts/bench_pipeline.py reproduce --frozen F --work W         # the published run, scored again from its frozen predictions: must match exactly
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group recognizers
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group r3 --preset default   # and ab1, piimb; and --preset everything
python scripts/bench_pipeline.py score --frozen F --work W
python scripts/bench_pipeline.py compare --new W/out --reference R --report report.md
```

`compare` judges every nullpii number at the precision the docs print it, in its own direction (a lower leak rate is better, a lower keep rate worse), and the claims derived from the other tools too: nullpii's rank, and the sign of each paired interval of nullpii minus a tool. It exits 0 when nothing moved, 3 when something did, and 4 when something got worse. `reference --frozen F --out R` lays out the published outputs for a first comparison, with `compare --published-names`.

## Latency

```bash
node scripts/ab/harness.mjs dump-corpus --out corpus.jsonl     # the inputs every tool is timed on
node scripts/ab/harness.mjs latency --dist <nullpii dist> --out nullpii.json
python scripts/ab/competitor_latency.py --inputs corpus.jsonl --tools <tool> --backend cpu --out tools.json
```

The harness builds its corpus from files of this repository at a fixed commit, so run it from a git clone. `--plan short` (on both `dump-corpus` and `latency`) times one text of each kind at 2k and 30k characters and three at 100k, once: the plan the CPU table uses, since the full plan (three rounds of 77 texts) takes hours per tool on CPU.

## Bundled datasets

`datasets/`: see [`datasets/README.md`](datasets/README.md). The published benchmark does not use them; they hold the runtime's regression set and earlier benchmark files.

## Model card

[`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii): intended use, limitations, licence.
