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

The frozen inputs (the sets, every tool's per-document predictions, the published run's scoring outputs) are in a private Hugging Face dataset, pinned in `scripts/pipeline/settings.py` to a revision and to the SHA-256 of its manifest, so every step uses a copy only when each of its files is the pinned one, wherever the copy came from (`fetch` without `--download` says it checked a local copy, and a copy whose manifest is not the pinned one is refused as unpinned); it holds real secrets and data that may not be passed on, so no step prints a row. Install the extra with `pip install -e '.[pipeline]'`, and give a token with read access (`HF_TOKEN`, or `hf auth login`).

```bash
python scripts/bench_pipeline.py fetch --frozen F --download          # download, check every file's SHA-256, link the sets under results/ for bench_full.py's loaders
python scripts/bench_pipeline.py reproduce --frozen F --work W         # the published run, scored again from its frozen predictions: must match exactly (see below)
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group recognizers
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group r3 --preset default   # and ab1, piimb; and --preset everything; --resume continues an interrupted one
python scripts/bench_pipeline.py score --frozen F --work W
python scripts/bench_pipeline.py reference --frozen F --out R          # the published outputs, for a first comparison
python scripts/bench_pipeline.py compare --new W/out --reference R --published-names --report report.md   # later: --reference <an earlier run's out>, without --published-names
```

Paths may be relative: each is taken from the directory the command runs in. `fetch` links the sets under `results/` only for `bench_full.py`'s loaders, which check each set's SHA-256 (the text capture and R3's scorer read them there); every other step hands the scorers the files of the copy it has just checked, never what `results/` holds.

`reproduce` scores the published run again from the frozen predictions and checks that each output they give is the published one: AB-1's three score files (against `published-bench/ab1/`), R3's 14 reports and 6 verdicts (against the run's own outputs), and PIIMB from nullpii's published spans (against `published-bench/piimb/`). It first checks that the recipe declares exactly the R3 reports and verdicts the published run has: the 11 reports and 5 verdicts `score` writes, and the 3 reports and the verdict of the core regime (every category masked scored on core labels only), which are no longer published, so `score` does not write them and a first `compare` lists them as dropped. AB-1's recognizer coverage and the mask-restore round trip come from running nullpii itself, so no frozen prediction can check them.

`compare` judges nullpii's numbers at the precision the docs print them, in their own direction (a lower leak rate is better, a lower keep rate worse): on AB-1 the rates and their breakdowns, the leak rates on secrets the recognizer pack covers and on the others, and the round trip; on R3 per-set F2, recall and precision, macro F2, F1, F0.5, recall and precision, the leave-one-out range and each leave-one-out report's macro F2; on PIIMB the average and per-task F2, the place on the leaderboard, and the average and place without nemotron-pii, the task from nullpii's training family. It judges the claims derived from the other tools too: nullpii's rank (on R3 by macro F2 and F0.5, by macro F0.5, recall and precision at each tool's best-F2 row as the matrix shows them, by F2 on each set, and by macro F2 leaving each set out; on AB-1, among each other tool's tuned `+agent` row as the README's table shows them, by leak rate, keep rate and leak rate per category, on each set), the sign of each paired interval of nullpii minus a tool and its two bounds as printed (AB-1 leak and keep, R3 F2), keyed by the nullpii row it is against, and the text of each R3 verdict (a changed text is moved: its intervals are judged as claims). Counts with no better direction (how many secrets the pack covers, which also splits every other tool's coverage cells, and how many documents had something masked) are reported as moved. What the docs print and `compare` does not judge is listed, with why, in `NOT_COMPARED` (`scripts/pipeline/compare.py`) and at the end of every report: the other tools' own numbers (frozen), gaps and counts of tools that follow from a compared number or rank, the split of CredData's leaks into UUIDs and other secrets (no output holds it), F1 and F0.5 intervals (never printed), latency, one-off measurements, dataset facts and history.

Only like is compared with like. It exits 0 when nothing moved, 3 when something moved, is new or is dropped, and 4 when something got worse or is not measured any more (the reference has a number or claim the run no longer gives, and the code does not declare it dropped). It fails, rather than compare less, when a directory does not exist, when either side lacks an output file (a published reference may lack only the PIIMB report of the default), lacks a nullpii row, or holds a nullpii row that is neither measured now nor declared.

`reference --frozen F --out R` lays out the published outputs for a first comparison, with `compare --published-names`: AB-1 and PIIMB from `published-bench/`, R3's reports and verdicts from the published run. nullpii is published as `default` and `everything` from now on, so the published rows are read like for like only: the 0.5 agent default is `nullpii-default` on AB-1, and every category masked (`nullpii-rel-cuda-default`, all its spans) is `nullpii-everything` on R3 and PIIMB (PIIMB's published 0.851 is every category masked, so a drop there is worse). The published core regime (R3's headline row `nullpii-rel-cuda-core`, and every category masked scored on core labels only) has no configuration measured now: its rows, the intervals and verdicts against it, and its own reports are listed as "dropped (core regime no longer published)", never as better or worse, and the run's `default` rows, intervals and verdicts on R3 are new. Earlier rows the docs never printed (`settings.PUBLISHED_UNPRINTED`) are not compared. `reference` writes into an empty directory or over a previous reference (it leaves a `REFERENCE.json` listing its files), and refuses any other non-empty `--out` unless given `--force`, which replaces only the files a reference writes; it never removes anything else, and refuses an `--out` that overlaps `published-bench/` or the frozen copy.

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
