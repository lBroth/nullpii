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

The frozen inputs (the sets, every tool's per-document predictions, the published run's scoring outputs, under `published-0.5/` for AB-1 and PIIMB) are in a private Hugging Face dataset, pinned in `scripts/pipeline/settings.py` to a revision and to the SHA-256 of its manifest, so every step uses a copy only when each of its files is the pinned one, wherever the copy came from (`fetch` without `--download` says it checked a local copy, and a copy whose manifest is not the pinned one is refused as unpinned); it holds real secrets and data that may not be passed on, so no step prints a row. Install the extra with `pip install -e '.[pipeline]'` (or the pinned `pip install -r requirements-pipeline.txt` that CI uses), and give a token with read access (`HF_TOKEN`, or `hf auth login`). `fetch --sets-only` downloads and checks the sets alone, all a capture reads; `score` and `reproduce` need the whole copy.

```bash
python scripts/bench_pipeline.py fetch --frozen F --download          # download, check every file's SHA-256, link the sets under results/ for bench_full.py's loaders
python scripts/bench_pipeline.py reproduce --frozen F --work W         # the published run, scored again from its frozen predictions: must match exactly (see below)
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group recognizers
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group r3 --preset default   # and ab1, piimb; and --preset everything; --resume continues an interrupted one
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group roundtrip            # the mask-restore round trip over AB-1, default preset
python scripts/bench_pipeline.py capture --frozen F --work W --dist <nullpii dist> --group r3 --preset default --shard 2/8   # one of 8 parts of a group (CI splits every group this way)
python scripts/bench_pipeline.py score --frozen F --work W             # puts the parts together, refuses to start until every capture is there
python scripts/bench_pipeline.py reference --frozen F --out R          # the published outputs, for a first comparison
python scripts/bench_pipeline.py compare --new W/out --reference R --published-names --report report.md   # later: --reference <an earlier run's out>, without --published-names
python scripts/bench_pipeline.py compare --new W/out --published-bench --frozen F --report report.md      # against what published-bench/ holds, whichever it is (bench.yml)
python scripts/bench_pipeline.py render --run W/out                   # published-bench/, then every rendered region of the docs and the figures, from it
python scripts/bench_pipeline.py render --run published-bench --check # writes nothing; exits 5 listing what differs (CI runs it)
python scripts/bench_pipeline.py propose --report report.md --compare-exit 3 --commit SHA --run-url URL --model REF --runner TEXT --title-out T --body-out B   # after render: bench.yml's numbers PR
python scripts/bench_pipeline.py model-card --tag v0.6.0             # the card is this release's; --upload puts it on Hugging Face (release.yml)
```

Every capture of texts runs on one shard of its group (`--shard K/N`, default `1/1`): a contiguous run of the group's texts in capture order, balanced by characters, so a CI job each captures a long group within its time limit. Each writes a part, `W/parts/<group>-<preset>-<K>-of-<N>/`, and, once its output has been read back (offsets, labels, scores and counts only, a row for every text of the shard), its `PART.json`. `score` puts the parts together where the scorers read them, only when every shard of every capture is there, each once, with every row once, and names what is missing or wrong otherwise. `--limit N` keeps the first N texts of each set, for a dry run of the capture on a few texts: the work directory and its parts are marked, and `score` refuses them.

Paths may be relative: each is taken from the directory the command runs in. `fetch` links the sets under `results/` only for `bench_full.py`'s loaders, which check each set's SHA-256 (the text capture and R3's scorer read them there); every other step hands the scorers the files of the copy it has just checked, never what `results/` holds.

`reproduce` scores the published run again from the frozen predictions and checks that each output they give is the published one: AB-1's three score files and B1's UUID split (against the published run's own, the frozen copy's `published-0.5/ab1/`), R3's 14 reports and 6 verdicts (against the run's own outputs), and PIIMB from nullpii's published spans (against `published-0.5/piimb/`). It reads nothing from `published-bench/`, which a run of the pipeline replaces. It first checks that the recipe declares exactly the R3 reports and verdicts the published run has: the 11 reports and 5 verdicts `score` writes, and the 3 reports and the verdict of the core regime (every category masked scored on core labels only), which are no longer published, so `score` does not write them and a first `compare` lists them as dropped. AB-1's recognizer coverage and the mask-restore round trip come from running nullpii itself, so no frozen prediction can check them.

`compare` judges nullpii's numbers at the precision the docs print them, in their own direction (a lower leak rate is better, a lower keep rate worse): on AB-1 the rates and their breakdowns, the leak rates on secrets the recognizer pack covers and on the others, B1's leaks on the secrets CredData labels `UUID` and on the other secrets (`ab1/kind_split.py`, as counts too, since the docs print them and one leak among 1,706 need not move the rate's printed digit), and the round trip; on R3 per-set F2, recall and precision, macro F2, F1, F0.5, recall and precision, the leave-one-out range and each leave-one-out report's macro F2; on PIIMB the average and per-task F2, the place on the leaderboard overall and on each task ("trails on the ai4privacy, nemotron-pii and Gretel tasks"), and the average and place without nemotron-pii, the task from nullpii's training family. It judges the claims derived from the other tools too: nullpii's rank (on R3 by macro F2 and F0.5, by macro F0.5, recall and precision at each tool's best-F2 row as the matrix shows them, by F2 on each set among the same rows, and by macro F2 leaving each set out; on AB-1, among each other tool's tuned `+agent` row as the README's table shows them, by leak rate, keep rate and leak rate per category, on each set, and on B1 by the leak rate on the secrets other than UUIDs), the sign of each paired interval of nullpii minus a tool and its two bounds as printed (AB-1 leak and keep, R3 F2), keyed by the nullpii row it is against. Every sentence of the gated R3 verdicts is judged as a claim from the raw intervals, against both rows of each tool as `r2_verdict.py --better-row` tests them: S1 is the macro F2 signs above; S2 is judged per report, set and tool row (a tool with significantly higher recall at a precision not significantly lower is a breach, and a new breach is worse); the F1 / F0.5 reversals are the per-set F2, F1 and F0.5 signs and the macro F1 and F0.5 signs. The text of each verdict is compared too, and a changed text is moved. Counts with no better direction (how many secrets the pack covers, which also splits every other tool's coverage cells, how many secrets each side of B1's UUID split holds, and how many documents had something masked) are reported as moved. What the docs print and `compare` does not judge is listed, with why, in `NOT_COMPARED` (`scripts/pipeline/compare.py`) and at the end of every report: the other tools' own numbers (frozen), gaps and counts of tools that follow from a compared number or rank, the bounds of the F1, F0.5 and per-set intervals (never printed; their signs are judged), a verdict's table at four decimals, latency, one-off measurements, dataset facts and history.

Only like is compared with like. It exits 0 when nothing moved, 3 when something moved, is new or is dropped, and 4 when something got worse or is not measured any more (the reference has a number or claim the run no longer gives, and the code does not declare it dropped). It fails, rather than compare less, when a directory does not exist, when either side lacks an output file (a published reference may lack only the PIIMB report of the default), lacks a nullpii row, or holds a nullpii row that is neither measured now nor declared.

`reference --frozen F --out R` lays out the published outputs for a first comparison, with `compare --published-names`: AB-1 and PIIMB from the frozen copy's `published-0.5/`, R3's reports and verdicts from the published run. nullpii is published as `default` and `everything` from now on, so the published rows are read like for like only: the 0.5 agent default is `nullpii-default` on AB-1, and every category masked (`nullpii-rel-cuda-default`, all its spans) is `nullpii-everything` on R3 and PIIMB (PIIMB's published 0.851 is every category masked, so a drop there is worse). The published core regime (R3's headline row `nullpii-rel-cuda-core`, and every category masked scored on core labels only) has no configuration measured now: its rows, the intervals and verdicts against it, and its own reports are listed as "dropped (core regime no longer published)", never as better or worse, and the run's `default` rows, intervals and verdicts on R3 are new. Earlier rows the docs never printed (`settings.PUBLISHED_UNPRINTED`) are not compared. `reference` writes into an empty directory or over a previous reference (it leaves a `REFERENCE.json` listing its files), and refuses any other non-empty `--out` unless given `--force`, which replaces only the files a reference writes; it never removes anything else, and refuses an `--out` that overlaps `published-bench/` or the frozen copy.

`render --run R` writes `published-bench/` from a set of outputs (a run's `out`, a `reference`, or `published-bench/` itself), then renders from `published-bench/` every marked region of `README.md`, `METHOD.md` and `MODEL_CARD.md` and the README's figures with their alternative texts (`scripts/pipeline/docs.py` lists the regions; a region is the Markdown between `<!-- name:begin -->` and `<!-- name:end -->`, each on a line of its own). `published-bench/` keeps the files a run's `out` holds, byte for byte, and `OUTPUTS.json`, which lists them, says in whose row names they are (`published` for a reference, read as `compare --published-names` reads them) and which nullpii version they measured; the core regime's own reports are not kept. Every claim a region states (which tools let fewer through, nullpii's place, the sign of an interval, the S2 sentence, the weakest categories, the bold best value of each column) is worded from the data. A claim the data stops supporting is reworded, which `--check` lists as a difference, or refused, so the step fails naming it, where the block has no wording for it (a tie, for one). Intervals are read only against a configuration measured now: the published run's are against its core regime, so the published outputs render none. The split of CredData's leaks into UUIDs and other secrets is `score`'s `ab1/kind-split-ab1-b1.json`, so it is rendered from every run. `render --check` writes nothing and exits 5 listing each file, region and figure that differs; CI runs it on `published-bench/`, so the docs always say what `published-bench/` holds. Latency is still kept by hand: the README's `latency` region, which the latency chart is drawn from. A run's docs say what it is: rendered from a run of the pipeline, the README's benchmark introduction and METHOD's Results paragraph say nullpii's rows are a CPU re-measurement of the version measured, and the published 0.5 run's rows were measured on CUDA (`docs.py`, `bench-intro` and `results-measured`).

## Benchmark workflow

[`.github/workflows/bench.yml`](https://github.com/lBroth/nullpii/blob/main/.github/workflows/bench.yml) runs the pipeline on GitHub-hosted CPU runners (`ubuntu-24.04`) and proposes the new numbers as a pull request. Its numbers are CPU re-measurements: the published 0.5 run measured nullpii on CUDA, and nullpii's CUDA and CPU outputs differ on 37 of the 14,701 tuning-set documents (see [`METHOD.md`](METHOD.md), Results). Every PR it opens says so, with the commit it measured, the frozen revision and the model, and the docs it renders say so too.

**What starts it.** A push to `main` that changes something nullpii's numbers depend on: the library's sources (`src/`, the model pin included), `package.json`, `package-lock.json`, the build's TypeScript configuration, the eval kit's scripts and dataset loaders (`packages/eval/scripts/`, `packages/eval/src/`, but not their tests, the approval gate or the model-card step), `requirements-pipeline.txt`, or the workflow itself. Also a manual run (`workflow_dispatch`) on `main`; on any other branch its jobs are skipped. Never a pull request. A numbers PR changes only `published-bench/`, the docs' rendered regions and the README's figures (`propose` refuses anything else, and a test checks that none of these is a path the workflow runs on), so merging one starts no run; its README, METHOD and figures redeploy the site (`docs.yml`). Two runs never overlap: a run that starts while one is going waits, and only the latest waiting one is kept.

**What it runs.** `build` builds nullpii and fetches its pinned model (cached by model revision; the model is public). 35 `capture` jobs then run in parallel: AB-1 in 4 parts, R3 in 8 and PIIMB in 3, each in both presets, the round trip over AB-1 in 4, and the recognizer pack. A part is about 5M characters, about 20 minutes at a laptop CPU's 25 s per 100,000 characters, so even a much slower runner ends well within the 6-hour limit of a hosted job (each stops at 5 hours). `reproduce` checks that the published run still reproduces from its frozen predictions. `score` puts the parts together, scores, and compares with what `published-bench/` holds (`compare --published-bench`): while it holds the published 0.5 run (the first time), the published outputs laid out from the frozen copy and read like for like (`--published-names`); after that, the run it holds. Every run's report is in its summary. When nothing moved (exit 0) it stops there. When something moved (3) or got worse (4), `propose` renders the run (`render --run`), checks the change (`propose`), commits it on `bench/run-<run id>`, sets the commit status `bench/compare` (success when numbers only moved, failure when something got worse), and opens the PR with the bench GitHub App's token, labelled `bench` (and `bench-worse`). The body is the commit measured, the frozen revision, the model, the CPU label and compare's report.

**What it handles carefully.** The frozen inputs hold real secrets and data that may not be passed on. Each job that needs them downloads them with `HF_TOKEN` into the runner's temp directory, outside the workspace, and they are never cached (pull requests can read the Actions cache); a capture job downloads the sets alone (`fetch --sets-only`). Artifacts hold offsets, labels, scores and counts only: each capture reads its output back and refuses anything else, and each upload names a part's own directory, never the texts or the frozen copy. No step prints a row.

**What the owner configures** (once; none of it is in this repository):

- Repository secrets: `HF_TOKEN`, a Hugging Face token that can read `lBroth/nullpii-bench-private` (best a fine-grained token that can read that repository and nothing else); `BENCH_APP_ID` and `BENCH_APP_PRIVATE_KEY`, the bench GitHub App, installed on this repository with the repository permissions Contents: read and write and Pull requests: read and write (the token it gets asks for those two only).
- The required check, so a worse result cannot be merged: Settings → Rules → Rulesets → the ruleset for `main` (or Settings → Branches → the rule for `main`) → "Require status checks to pass" → add `bench/approval`, with GitHub Actions as its source, so a status set any other way does not count. GitHub offers the check there once it has been reported in the past week: open any PR after this workflow is on `main` first. Without that rule a worse PR shows a red check but can still be merged.
- For the model card at release: `HF_MODEL_CARD_TOKEN`, below.

**How approval works.** [`bench-approval.yml`](https://github.com/lBroth/nullpii/blob/main/.github/workflows/bench-approval.yml) sets `bench/approval` on the head of every PR to `main`, whenever one is opened, reopened, pushed to, labelled or unlabelled, from the PR's state as the API reports it (`scripts/pipeline/approval.py`): success on any PR that is not a numbers PR (branch `bench/run-<id>`); on a numbers PR, success when `bench/compare`, as the Actions bot set it on that very head, is a success, and when it is a failure only while the label `bench-accept-worse` is on the PR and the repository owner added it last. A label added by anyone else accepts nothing, removing it takes the acceptance back, and a push to the branch makes it a failure (what would be merged is no longer what was measured: run the workflow again instead). A numbers PR that only moved numbers still needs the normal review. It runs on `pull_request_target` so that it can set the status on a fork's PR too; it checks out `approval.py` alone from the base branch and runs nothing from the PR. A run by hand (`workflow_dispatch` on `main`, with the PR's number) decides again, e.g. after an API failure. The gate trusts what branch protection trusts: anyone who can push to the repository can also set statuses.

The owner merges a numbers PR (`gh pr merge <number> --repo lBroth/nullpii --squash`); nothing merges it automatically, and it is never auto-merged. A newer numbers PR replaces an older one, which can be closed.

**The model card.** The model card is uploaded at release only: [`release.yml`](https://github.com/lBroth/nullpii/blob/main/.github/workflows/release.yml)'s `model-card` job, after both packages are published, runs `bench_pipeline.py model-card --tag <tag> --upload`, which uploads `MODEL_CARD.md` of the tagged commit as the `README.md` of [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) and reads it back, but only when the tag is the package's version, the card's Files table is exactly the files and SHA-256 `src/defaults.ts` pins (and the model repository holds them at the pinned revision), and its rendered regions say what `published-bench/` holds. A pre-release does not replace the card. Its token is the secret `HF_MODEL_CARD_TOKEN`, which the owner creates on huggingface.co as a fine-grained token with write access to `lBroth/nullpii` only (not the frozen inputs' `HF_TOKEN`); without it the job fails and says so.

**What it never does.** It measures no latency (shared runners are too noisy; latency is timed by hand on quiet machines, and the docs' latency is left as it is). It never rewrites the CHANGELOG. It never merges, never enables auto-merge, never pushes to `main`. It runs no other tool again.

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
