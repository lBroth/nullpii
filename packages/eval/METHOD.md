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
- **F2 decides; F1 and F0.5 are reported next to it.** F2 counts recall as twice as important as precision (β = 2), the product's priority, and it rewards over-masking. A mask-everything row shows the floor.
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

nullpii 0.5 (H3b weights, the release build) in its core regime, measured on CUDA (output identical to the CPU's). Competitors at their default and tuned operating points; each row shows a tool's better one. The R3 sets were first scored on 20 October with the candidate build; these numbers are the re-measurement after the pre-release fixes, which moved nullpii's macro by −0.001.

**Gated sets** (macro char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | REDACT | Tonic | PIILO | eu-clinical | traces-v3 | Macro | LODO |
|---|---:|---:|---:|---:|---:|---:|---:|
| rizzo-pii (default) | 0.818 | 0.849 | 0.623 | 0.840 | 0.718 | 0.770 | 0.750–0.806 |
| **nullpii** | 0.847 | 0.871 | 0.407 | 0.887 | 0.769 | 0.756 | 0.723–0.844 |
| nullpii, default configuration on the core labels | 0.827 | 0.872 | 0.402 | 0.880 | 0.757 | 0.747 | 0.714–0.834 |
| nemotron-pii (adapter) | 0.779 | 0.833 | 0.442 | 0.875 | 0.672 | 0.720 | 0.681–0.790 |
| OpenMed privacy-filter-multilingual-v2 | 0.784 | 0.874 | 0.480 | 0.725 | 0.725 | 0.717 | 0.678–0.777 |
| pii-identifier | 0.796 | 0.879 | 0.492 | 0.632 | 0.706 | 0.701 | 0.657–0.753 |
| ettin-68m | 0.805 | 0.844 | 0.483 | 0.647 | 0.713 | 0.699 | 0.662–0.752 |
| openai privacy-filter | 0.814 | 0.872 | 0.611 | 0.442 | 0.723 | 0.693 | 0.648–0.755 |
| OpenMed PII Large | 0.784 | 0.869 | 0.528 | 0.589 | 0.642 | 0.682 | 0.635–0.721 |
| OpenMed PII Small | 0.777 | 0.866 | 0.478 | 0.609 | 0.635 | 0.673 | 0.625–0.722 |
| gliner-pii-large | 0.844 | 0.801 | 0.191 | 0.863 | 0.582 | 0.656 | 0.604–0.772 |
| piiranha | 0.784 | 0.760 | 0.239 | 0.857 | 0.617 | 0.651 | 0.600–0.755 |
| gliner_multi_pii (ONNX) | 0.817 | 0.795 | 0.163 | 0.913 | 0.551 | 0.648 | 0.581–0.769 |
| Presidio | 0.706 | 0.779 | 0.280 | 0.729 | 0.645 | 0.628 | 0.590–0.715 |
| nemotron-pii (NVIDIA server) | 0.651 | 0.755 | 0.252 | 0.801 | 0.498 | 0.591 | 0.539–0.676 |
| gliner-stream-pii | 0.732 | 0.769 | 0.141 | 0.559 | 0.640 | 0.568 | 0.518–0.675 |
| deberta PII (default) | 0.507 | 0.761 | 0.260 | 0.298 | 0.493 | 0.464 | 0.389–0.515 |
| mask everything | 0.370 | 0.278 | 0.004 | 0.272 | 0.374 | 0.260 | 0.231–0.324 |

**Reported sets** (macro char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | RedactionBench | mama-deid | traces-v3, distractors ignored | Macro | LODO |
|---|---:|---:|---:|---:|---:|
| **nullpii** | 0.735 | 0.715 | 0.880 | 0.777 | 0.725–0.807 |
| nullpii, default configuration on the core labels | 0.717 | 0.666 | 0.870 | 0.751 | 0.692–0.793 |
| openai privacy-filter | 0.727 | 0.701 | 0.804 | 0.744 | 0.714–0.765 |
| ettin-68m | 0.738 | 0.591 | 0.818 | 0.716 | 0.665–0.778 |
| rizzo-pii | 0.632 | 0.648 | 0.824 | 0.701 | 0.640–0.736 |
| OpenMed privacy-filter-multilingual-v2 | 0.691 | 0.591 | 0.821 | 0.701 | 0.641–0.756 |
| pii-identifier | 0.753 | 0.541 | 0.808 | 0.700 | 0.647–0.780 |
| nemotron-pii (adapter) | 0.658 | 0.610 | 0.746 | 0.671 | 0.634–0.702 |
| gliner-stream-pii | 0.561 | 0.605 | 0.697 | 0.621 | 0.583–0.651 |
| gliner_multi_pii (ONNX) | 0.426 | 0.768 | 0.602 | 0.599 | 0.514–0.685 |
| gliner-pii-large | 0.419 | 0.729 | 0.604 | 0.584 | 0.512–0.667 |
| piiranha | 0.380 | 0.696 | 0.651 | 0.576 | 0.516–0.674 |
| OpenMed PII Small | 0.456 | 0.571 | 0.700 | 0.576 | 0.514–0.635 |
| OpenMed PII Large | 0.437 | 0.584 | 0.705 | 0.575 | 0.510–0.644 |
| nemotron-pii (NVIDIA server) | 0.490 | 0.645 | 0.562 | 0.565 | 0.526–0.603 |
| Presidio (default) | 0.353 | 0.414 | 0.682 | 0.483 | 0.384–0.548 |
| deberta PII (default) | 0.344 | 0.429 | 0.546 | 0.440 | 0.386–0.488 |
| mask everything | 0.266 | 0.364 | 0.407 | 0.346 | 0.315–0.386 |

**Gated sets, English documents only** (macro char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | REDACT | Tonic | PIILO | traces-v3 | Macro | LODO |
|---|---:|---:|---:|---:|---:|---:|
| openai privacy-filter | 0.783 | 0.872 | 0.611 | 0.717 | 0.746 | 0.704–0.791 |
| rizzo-pii (default) | 0.768 | 0.849 | 0.623 | 0.729 | 0.742 | 0.707–0.782 |
| OpenMed privacy-filter-multilingual-v2 (default) | 0.791 | 0.868 | 0.507 | 0.704 | 0.717 | 0.667–0.788 |
| pii-identifier (default) | 0.771 | 0.858 | 0.575 | 0.654 | 0.714 | 0.667–0.761 |
| **nullpii** | 0.790 | 0.871 | 0.407 | 0.784 | 0.713 | 0.661–0.815 |
| ettin-68m | 0.783 | 0.844 | 0.483 | 0.712 | 0.706 | 0.659–0.780 |
| nullpii, default configuration on the core labels | 0.768 | 0.872 | 0.402 | 0.773 | 0.704 | 0.648–0.804 |
| OpenMed PII Large | 0.772 | 0.869 | 0.528 | 0.630 | 0.700 | 0.643–0.757 |
| OpenMed PII Small | 0.766 | 0.866 | 0.478 | 0.623 | 0.683 | 0.622–0.751 |
| nemotron-pii (adapter) | 0.746 | 0.833 | 0.442 | 0.666 | 0.672 | 0.618–0.748 |
| Presidio | 0.688 | 0.779 | 0.280 | 0.646 | 0.598 | 0.538–0.705 |
| piiranha | 0.770 | 0.760 | 0.239 | 0.605 | 0.593 | 0.534–0.711 |
| gliner-pii-large | 0.792 | 0.801 | 0.191 | 0.577 | 0.590 | 0.520–0.723 |
| gliner_multi_pii (ONNX) | 0.798 | 0.795 | 0.163 | 0.552 | 0.577 | 0.503–0.715 |
| gliner-stream-pii | 0.724 | 0.769 | 0.141 | 0.637 | 0.568 | 0.501–0.710 |
| deberta PII (default) | 0.646 | 0.761 | 0.260 | 0.505 | 0.543 | 0.470–0.638 |
| nemotron-pii (NVIDIA server) (default) | 0.619 | 0.751 | 0.291 | 0.501 | 0.540 | 0.470–0.624 |
| mask everything | 0.323 | 0.278 | 0.004 | 0.393 | 0.249 | 0.202–0.331 |

**Comparisons (gated sets, F2).** nullpii is significantly ahead of every tool but one, at that tool's better row: the narrowest margins are nemotron-pii [+0.024, +0.050] and OpenMed privacy-filter-multilingual-v2 [+0.030, +0.048]. rizzo-pii at its default is significantly ahead of nullpii, [−0.021, −0.005], all of it on PIILO. No dataset has a tool with significantly higher recall at matched or better precision. At F0.5 the order largely reverses.

**Sensitivity checks** (reported, none decides):
- without the documents any OpenMed row returned no output for (77 gated documents, for every tool): conclusions unchanged;
- every set resampled by its recorded clusters: conclusions unchanged (rizzo-pii [−0.022, −0.004]);
- nullpii's default configuration on the core labels (0.747) as the baseline: ahead of the same 13 tools, behind rizzo-pii.

**OpenMed's texts with no output.** `deidentify` refused or failed on 7 traces-v3 transcripts (refusals) and, at the tuned points, on up to 84 mama-deid and 41 Tonic texts (the package's own safety-sweep check); they score as no spans.

**PIIMB** (`sentences` subset, 150,022 texts, the leaderboard's own scoring; nullpii's default configuration): average F2 0.851, first of 36; OpenMed privacy-filter-multilingual-v2 0.836, OpenMed PII SuperClinical Large 0.835. Per task, nullpii's F2: ai4privacy-en 0.960, ai4privacy-multilingual 0.940, nemotron-pii 0.953 (in nullpii's training family), Gretel 0.962, privy 0.713, mapa-eur-lex 0.580.

**Latency** is in the README; it is measured on idle machines, every tool on the same corpus of coding-agent text.

## Limits

- F2 rewards over-masking. nullpii ranks on recall: at F0.5 most compared tools rank above it.
- Five gated datasets is a small sample of the world, and only English, the main EU languages and Greek are covered.
- Gold labels differ in scope between datasets. PIILO leaves many names, dates and places unlabelled, so masking them counts against a tool.
- The tuning set is close to nullpii's training distribution and partly to some competitors' (it is used to choose, never to claim).
- Latency depends on hardware and load; it is measured on idle machines, every tool on the same corpus.

## Reproduce

`scripts/bench_full.py` runs any tool on any dataset and writes per-document predictions; `scripts/ab/char_metrics.py` scores them (`--cluster-rows` and `--exclude` for the sensitivity checks); `scripts/ab/r2_verdict.py` applies the comparison rules; `scripts/ab/tune_operating_point.py` tunes a competitor; `scripts/ab/score_capture.mjs` captures nullpii's spans; `scripts/ab/piimb_score.py` scores PIIMB; `scripts/ab/competitor_latency.py` and `scripts/ab/harness.mjs` time the tools.
