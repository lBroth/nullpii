# How nullpii is measured

This page says how the numbers in the README are produced and what they do and do not show. The scripts are in `scripts/`; the dataset selection rules for the report set are in [`scripts/r3/CRITERIA.md`](scripts/r3/CRITERIA.md), committed before any of its texts was opened (it cites the maintainers' working protocol and log, which are not published; this page is their public summary).

## What is tested

nullpii masks personal data and secrets before text reaches an LLM, so the main question is how much personal data it lets through, and at what cost in over-masking. It is compared with every machine-learning PII detector we could run locally, each the way its authors ship it.

## Data

- **Tuning set.** Held-out slices of Isotonic (en, de, fr, it), ai4privacy-300k, and a set of synthetic coding-agent traces. Every choice is made on this set: nullpii's changes and thresholds, and every competitor's operating point. It is close to nullpii's home distribution, which is why nothing is claimed from it.
- **Report set (R3), gated.** Five public datasets chosen by written criteria (licence, independence from every compared tool's declared training data, domain and language coverage) and frozen by SHA-256 before any tool ran on them:
  - REDACT (EU-language and English records of its locked test split);
  - TonicAI's human-annotated Privacy-Bench;
  - PIILO (student essays);
  - eu-clinical (Greek clinical notes and German letters);
  - traces-v3: coding-agent transcripts from a generator written by an agent that saw only a written spec, never this project's generators, corpora or tuning sets.
- **Reported, not gated:** RedactionBench (untyped gold), mama-deid's validation split (gold checked only by models), and traces-v3 with its distractor regions ignored.
- **Overlap check.** Before any tool was scored, each set was compared, with 10-word shingles, with nullpii's training corpus and tuning texts and with the public datasets the compared tools declare as training data (Nemotron-PII, the ai4privacy sets, Isotonic, and the synthetic sets named in their cards). No set reaches 1% overlap with any of them.
- **PIIMB.** The public PIIMB leaderboard's `sentences` subset, scored with the leaderboard's own protocol, is reported separately.

## Metric

- **Character level, label-agnostic.** A personal-data character counts as protected if any predicted span covers it, whatever label the tool gave. This is what a user cares about (what reaches the model unmasked), and it removes label-mapping differences between tools.
  - recall = covered gold characters / gold characters (1 − leak rate);
  - precision = covered gold characters / masked characters (1 − over-masking).
- **F2 decides; F1 and F0.5 are reported next to it.** F2 weighs recall four times as much as precision, the product's priority, and it rewards over-masking. A mask-everything row shows the floor.
- **Core label space.** Scores use the categories every dataset labels (persons, contact details, addresses, dates, identifiers, URLs, IPs, secrets). nullpii's extended categories (organisations, occupations, demographic and sensitive attributes, titles) are on by default; its default configuration is reported both raw and filtered to the core labels.
- **Macro over datasets**, with a leave-one-dataset-out range so one dataset cannot carry the result.
- **Paired bootstrap, 95% CIs** of nullpii minus each tool, resampled by source document or conversation where several rows share one. As a sensitivity check every set is also resampled by its recorded clusters.

## Competitors, run as shipped

- Each tool runs through its authors' inference path: their library or app pipeline, chunker, decoder and rule layers, the label strings of their card, and their recommended device and precision. Where the authors ship a product-level call it is used (rizzo-pii's app `analyze()`, OpenMed's `deidentify`, Presidio's multilingual engine with each text's language, the reference server NVIDIA's NeMo Guardrails calls for `nvidia/gliner-PII`). Third-party code is vendored verbatim where needed, with its licence.
- Model revisions are pinned.
- Every tool is shown at its default operating point and at one tuned on the tuning set with the same procedure nullpii's thresholds went through, using only the knobs its pipeline exposes. A claim against a tool is tested against its better row.
- Texts a tool refuses or fails on score as no output, and are counted. As a sensitivity check, scores are recomputed for every tool without those texts.

## Rules that keep the numbers honest

1. The report set never drives a decision. It is scored once, after every adapter and every candidate is frozen. A later re-measurement (for example after review fixes) is labelled as such.
2. No training on any benchmark row; training data comes only from permissively licensed sources ([`docs/WEIGHTS_PROVENANCE.md`](../../docs/WEIGHTS_PROVENANCE.md)).
3. A change to nullpii is kept only if, on the tuning set, it raises macro char-F2 with a CI above zero, lowers no label's recall, and keeps over-masking within a fixed cap; a correctness fix is kept when the property it targets holds and the output changes only where it was wrong.
4. Competitor settings change only symmetrically, and every change is disclosed.
5. Same hardware and inputs for every tool; raw per-document outputs are kept.

## Results

<!-- Filled from the final runs; see the README for the summary table. -->

## Limits

- F2 rewards over-masking. nullpii ranks on recall: at F0.5 most compared tools rank above it.
- Five gated datasets is a small sample of the world, and only English, the main EU languages and Greek are covered.
- Gold labels differ in scope between datasets. PIILO leaves many names, dates and places unlabelled, so masking them counts against a tool.
- The tuning set is close to nullpii's training distribution and partly to some competitors' (it is used to choose, never to claim).
- Latency depends on hardware and load; it is measured on idle machines, every tool on the same corpus.

## Reproduce

`scripts/bench_full.py` runs any tool on any dataset and writes per-document predictions; `scripts/ab/char_metrics.py` scores them (`--cluster-rows` and `--exclude` for the sensitivity checks); `scripts/ab/r2_verdict.py` applies the comparison rules; `scripts/ab/tune_operating_point.py` tunes a competitor; `scripts/ab/score_capture.mjs` captures nullpii's spans; `scripts/ab/piimb_score.py` scores PIIMB; `scripts/ab/competitor_latency.py` and `scripts/ab/harness.mjs` time the tools.
