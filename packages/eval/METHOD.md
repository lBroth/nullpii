# How nullpii is measured

This page explains how the numbers in the README are made, and what they show and do not show. The scripts are in `scripts/`. The rules for choosing the report set's datasets are in [`scripts/r3/CRITERIA.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/scripts/r3/CRITERIA.md), committed before any of its texts was opened. That file cites the maintainers' working protocol and log, which are not published; this page is their public summary.

## Results at a glance

![Agent traffic, 966 documents, leak rate and keep rate per tool: rizzo-pii 8.1% and 44.5%, nullpii 0.5 9.5% and 85.4%, then openai privacy-filter 14.5% and 77.9%; every other tool lets 15.7% to 55.1% through. The table below has every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/ab1-agent-traffic.svg)

![Documents, macro char-F2 per tool over five sets and over English documents only: rizzo-pii 0.770 and 0.742, nullpii 0.758 and 0.714, nvidia/gliner-PII 0.720 and 0.672, OpenMed privacy-filter-multilingual-v2 0.717 and 0.717, openai privacy-filter 0.693 and 0.746. The table below has every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/r3-documents.svg)

![GPU latency at 30,000 characters, median milliseconds per call: from ettin-68m at 157 to NVIDIA's nemotron server pipeline at 2,835; nullpii 463 with its core labels and 489 with every category masked, seventh of 13 tools. The tables below have every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/latency-gpu.svg)

| What | Result for nullpii 0.5 |
|---|---|
| Agent traffic (AB-1 A): lets through / keeps readable | 9.5% / 85.4% (only rizzo-pii lets fewer through, 8.1%, keeping 44.5%) |
| Agent traffic on CredData (B1) / GitHub issues (B2): lets through | 24.5% / 11.5% (B1: 13.0% without the items CredData labels `UUID`) |
| Documents (R3), macro char-F2 over five held-out sets | 0.758, second of 15 (rizzo-pii 0.770); English only 0.714 |
| Scored with the PIIMB leaderboard's method | 0.851 average F2 |
| Latency on GPU (RTX 4070 Ti), 30,000 characters | 463 ms; every category masked 489 ms |
| Latency on CPU (Core i7-13700KF), 30,000 characters | 6,984 ms |

The sections below say how each number is made, with every tool's row.

## What is tested

nullpii masks personal data and secrets before text reaches an LLM. So the main question is how much personal data it lets through, and how much it over-masks to get there. It is compared with every machine-learning PII detector we could run locally, each run the way its authors ship it. The job nullpii's default is built for is a coding agent's traffic, where some values must be hidden and others must stay readable. AB-1 measures that job separately ([Agent-traffic benchmark (AB-1)](#agent-traffic-benchmark-ab-1)).

## Agent-traffic benchmark (AB-1)

AB-1 is pre-registered. Its specification was written on 2026-10-23, after the 0.5 model was chosen and before any set was built or any tool ran on it. So it cannot steer a training or selection decision: it is reported, never used to choose. Where the work departs from the specification, the change was logged, before any tool ran unless the entry says otherwise. Each one is listed under [Departures from the specification](#departures-from-the-specification).

### What it measures, and why

nullpii's default is built for a coding agent's traffic (Claude Code): prompts, file reads, shell output, logs, tool-call arguments, tickets. A masker in front of that traffic has to hide what is dangerous to hand over: secrets and credentials, contact details and addresses, identifiers and account numbers, person names. It has to leave readable what the agent needs to work: dates, versions, paths, hostnames of public services, placeholders, code identifiers. The R3 report set measures document anonymisation (PIILO is student essays, rizzo-pii is a document anonymiser), which is a different job. AB-1 measures the agent job, per category and with no single combined score: the **leak rate** on the items that must be masked, and the **keep rate** on the items that must stay readable. Scoring ignores labels: an item counts as masked when a tool masks its characters, whatever label the tool gave them. A key masked as `PASSWORD` or as `ID` has still been protected. AB-1 does not measure latency.

### Data

- **A. Agent traffic.** 1,200 documents an agent sees (dev 200, test 1,000), with fictional values put in and the items to keep annotated. An agent built them from the AB-1 specification alone, working outside every nullpii repository. The generator, the value lists and the gold are Apache-2.0 and are in [`datasets/ab1/`](https://github.com/lBroth/nullpii/blob/main/packages/eval/datasets/ab1); carrier text keeps its dataset's licence. There are six kinds, each split 1/6 dev and 5/6 test:
  - user prompts to a coding agent (20%, en/it/de/fr/es in equal shares);
  - file reads of source, `.env`, YAML/JSON/TOML config, Dockerfile and CI files (20%, en);
  - shell output: `git log`, `git diff`, `curl -v`, `env`, `docker`/`kubectl` output, test runs (20%, en);
  - logs and stack traces with home paths (15%, en);
  - tool-call arguments as JSON (10%, en);
  - issue or ticket text pasted into the agent (15%, en/it/de/fr/es).

  Half of every kind, and of every language of prompts and tickets, starts from real material (a carrier). The other half starts from templates the builder wrote.
- **A, carriers.** [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) (CC BY 4.0, revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`): tool calls, bash output and diffs from OpenHands runs on public repositories. [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) (MIT, revision `facf45600d625510b98222ec584a8c9ac59272a2`): real user sessions. [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) (ODC-BY 1.0, revision `7d6490e462285cf85d91eabea0f9a954fbddcd1f`): the first user turn of it/de/fr/es conversations. And GitHub issues fetched on 2026-10-24, each keeping the SPDX licence its repository had at that moment. Excerpts are cut at line boundaries, 300–6,000 characters long, and the carrier id and offsets are recorded. The GitHub carriers also record the issue URL and the licence, so the text can be fetched again and the document rebuilt. 600 of the 1,200 documents are carrier documents (SWE-rebench 343, openhands-feedback 89, WildChat-1M 96, GitHub issues 72).
- **A, values and items.** Values go where they really occur: `.env` lines, `Authorization: Bearer` headers, DB connection strings, `git log` author lines, `/Users/<name>/` and `/home/<name>/` paths in tracebacks, `From:`/`To:` lines, log fields (`user=`, `email=`, `customer_id=`), config blocks. 20% of documents get no value (clean documents). 5% of the values appear a second time, base64- or URL-encoded (a `kubectl get secret -o yaml` payload, a query string), as their own item linked to the original. Every value is fictional, generated by the builder's code with recorded seeds, and has a valid format: Luhn-valid card numbers, mod-97 IBANs, national ids with valid check characters, provider keys with the provider's published prefix, length and character set. Key formats are drawn uniformly from the 221 usable rules of [gitleaks](https://github.com/gitleaks/gitleaks) v8.30.1 (MIT), so no one who knows nullpii chose them. Names and addresses come from public-domain or permissively licensed lists (Wikidata, GeoNames), not from Faker. Items are annotated in two passes, a carrier pass before the values go in and a keep pass after, and they never overlap. The classes are MUST_MASK, MUST_KEEP and AMBIGUOUS. AMBIGUOUS covers real PII-like strings already in the carriers, names in licence headers, public figures, maintainers' handles, role addresses, internal hosts and RFC 1918 addresses, order numbers, birth dates and dummy credentials; it is annotated but never scored either way. A generated value found in the carrier material is blocklisted and drawn again (three, all usernames).
- **A, counts.** As built, test split: 3,482 MUST_MASK, 6,002 MUST_KEEP and 423 AMBIGUOUS items, and 200 clean documents; both splits: 4,002 values put in and 200 encoded copies. Scored, after the audit corrections and the leak check: 966 test documents (prompt 199, file 199, shell 181, log 141, tool-call JSON 96, ticket 150), with 3,386 MUST_MASK, 5,676 MUST_KEEP and 439 AMBIGUOUS items.
- **B1. CredData** ([Samsung/CredData](https://github.com/Samsung/CredData), Apache-2.0, commit `c49ed106…`, values obfuscated upstream). With seed 0: 2,000 true secrets (102 categories) and 2,000 labelled non-secrets (49 categories), stratified by CredData's `Category` (largest remainder). A document is the candidate's line or lines, with 5 lines of context on each side. There is one item per document: a true secret is MUST_MASK `secret`, and a labelled non-secret is MUST_KEEP, with its CredData category as its kind. The span convention is CredData's own, taken from its scripts. Rows with label `X` (4,082), offsets outside the line (1) or an empty value (4) are dropped and counted. An independent script rebuilt all 4,000 documents and found them identical.
- **B2. Issue secrets** ([Zenodo record 17430335](https://zenodo.org/records/17430335), CC BY 4.0; paper [arXiv 2410.23657](https://arxiv.org/abs/2410.23657)). Every true secret plus an equal seeded sample of labelled non-secrets: 5,803 + 5,803 = 11,606 documents. The record's `main_data.csv` holds 5,873 true secrets, not the 5,881 the specification quoted; 70 are dropped by the rules below. A document is the issue body around the candidate, 1,000 characters on each side, cut at whitespace. The scored item is the candidate's core value: its longest run of `[A-Za-z0-9+/_\-.~%=]`, at least 8 characters, without a leading `name=`. This is because the labelled candidate sometimes carries the key name, quotes or the next line, which no masker is expected to hide. Candidates not found in the body, shorter runs and exact duplicate documents are dropped and counted. Where the value after `name=` is shorter than 8 characters, the item is AMBIGUOUS and scored neither way (27 secrets, 152 non-secrets). So 5,776 secrets and 5,651 non-secrets are scored. These secrets are real: only aggregates are published, never a document or a value.
- **B3, not run.** A third slice, bigcode/bigcode-pii-dataset (real code with crowd-annotated personal data), was planned before any run. Its access request was not granted, so AB-1 has no B3.

### How it was built and frozen

- **Order of work.** An agent built the data from the specification alone, outside every nullpii repository. Then: a 10% audit by fresh agents without the gold (Cohen's kappa per class; if more than 5% of items are wrong, fix the cause and audit again) → freeze by SHA-256 (the files of A, the B1/B2 id lists, the scorer) → leak check → every tool run once → scored once.
- **Freeze.** Before any tool runs, the log records the SHA-256 of every file of A (code, lists, gold, README), of B1/B2's sampled id lists and of the scorer, with the canary string `AB1-CANARY-6f3a1c9e-nullpii-agentbench-2026-10-23`. The canary is placed in A's README and gold.
- **Audit.** Three fresh agents, without the gold, annotated 40 documents each (120, 10% of A, with 1,026 gold items). Cohen's kappa over 28,745 tokens: MUST_MASK 0.9985, MUST_KEEP 0.8743, AMBIGUOUS 0.8544, overall 0.9042. Wrong or missing: 3 of 1,026 gold items (0.29%, threshold 5%), that is two MUST_KEEP items contradicted and one MUST_MASK item missing. No gold MUST_MASK item was contradicted. The corrections are under [Departures](#departures-from-the-specification).
- **Leak check** (after the freeze, before any tool runs). Every document of A, both splits, carrier and template, is compared with the shipped model's training corpus (100,982 rows), by 13-token shingles as exact sets. A document is flagged when Jaccard ≥ 0.8, or when ≥ 80% of a training row's shingles occur in it, or when ≥ 80% of its own occur in one training row. A MUST_MASK value that was put in is a hit when its token sequence occurs in any training row. Single-token values that are bare given names or surnames from the generator's name lists are exempt, and counted. This is stricter than the pre-registered test (MinHash Jaccard on carrier excerpts), which would miss a training row contained in a longer document. The one exception is the name exemption: common names occur in any large corpus, so a bare name from the generator's lists is not a hit; the exempted values are counted and published. Flagged test documents are dropped and counted, and nothing is added back. All 1,200 documents were compared: 34 test documents were flagged (29 contain a training row, 5 hold a value found in the training data), and 5 dev documents. No document passed the Jaccard or the document-in-training-row threshold, and 112 single-token names were exempt. Dropping the 34 test documents leaves 966.
- **Runs.** The specification has one run of the test split per release, for every tool, with every number published, including the ones nullpii loses. The tables below are the published numbers; the first scoring (before the punctuation rule was corrected, see Departures) and nullpii's 25 October rows are no longer in the tree, and are in the repository at 230ce9f ([`published-bench/ab1/strict-rule/`](https://github.com/lBroth/nullpii/tree/230ce9fd1933f5df5263ca9c87d248e064eddc77/packages/eval/published-bench/ab1/strict-rule), [25 October rows](https://github.com/lBroth/nullpii/blob/230ce9fd1933f5df5263ca9c87d248e064eddc77/packages/eval/METHOD.md?plain=1#L361)). Frozen on 25 October 2026, before any tool ran on a test set: A's file manifest `390e4ca5f658f745f23ff883c586c5fc007fcd6c0ac14cc7f1f3f58dcdf6e8ac`, scored test gold `baa5305f7999d1ef04c63831ef51408522b3d2ca6de2818d9947f76c03be7a26`, B1 `c0fb7082ae95ab1f277ebf59ff0363c23c756b572ff7a002df98aa98cd407106`, scorer `1c81d4455f8fba99cd7396c45b43df88ff9a171fc8863e3af9de9d1e739c13a2`. Two files changed later, both listed under Departures: B2's gold, rebuilt before any score was read (`41f144c66a247bf8f01826008621aef26f4769dba8836b011150687c6f08b1bb`), and the scorer, corrected after the scores were first read (`edd49ff03c3eaeb06ac84b85d63c49d37b3adb17f572fb0f01ab41d6bc84a7b8`). Every tool ran on 25 October 2026, and the run was redone once for every tool after an adapter fix (see Departures). nullpii's rows were measured again on 26 October, after three rules from end-to-end testing (described at the end of [Results](#results)).

### Metrics

- A MUST_MASK item is masked when every letter and digit of its value is masked, whatever the label. Whitespace, punctuation and `\n`/`\r`/`\t` layout escapes inside the item do not count. So a tool that masks a private key line by line, or an address as street and city with the comma between them left, has masked it. A letter or digit left unmasked is a leak. The same rule applies to every tool. Punctuation was excepted after the scores were first read (see [Departures](#departures-from-the-specification)).
- A MUST_KEEP item is kept when no character of it is masked. AMBIGUOUS items are scored neither way.
- These rates are over items, not over characters; that is the difference from the R3 metric below. A tool's leak rate and keep rate are reported per category and overall, with no combined score.
- Also reported:
  - documents with at least one leak;
  - the share of clean documents (no MUST_MASK item) with anything masked;
  - characters masked outside every item, per 1,000 characters;
  - the encoded leak rate, on the base64/URL-encoded copies alone;
  - whether JSON documents still parse after masking;
  - whether diff hunks still have a consistent line count after masking (the carriers' pre-images are not shipped, so `git apply --check` is not possible);
  - the secrets' leak rate split by whether nullpii's recognizer pack covers their key format. This split was computed after the freeze, from the pack itself (`recognizer_spans.mjs`, `secret_coverage.py`), and is only reported.
- Uncertainty: paired bootstrap over documents, 1,000 resamples, seed 0. It gives 95% intervals of each tool's overall leak and keep rates, and of nullpii minus each tool (not per category). A difference counts as a win or a loss only when its interval excludes 0.
- Baseline: nullpii 0.5 in its agent default, with the categories the agent policy leaves readable turned off (dates, organisations, occupations, titles, demographic and sensitive attributes).

### Competitors

- The tools of the README's document table, through the same adapters and full upstream pipelines. Each runs at its default operating point and at the one tuned on the tuning set, never on AB-1.
- Each row also has a `+agent` variant: the tool's spans, minus those whose mapped label is in the readable set above. For a tool whose categories map onto nullpii's, this is the same as turning those categories off. That is why it is the agent-policy row.
- Labels a tool emits that have no nullpii mapping are kept (`--keep-unmapped-labels`), because scoring ignores labels: a tool that masks a secret under a label outside nullpii's schema has masked it. Such spans stay in the `+agent` row. The document benchmark's numbers were produced without this option, and it does not change them.
- Thresholds are not tuned on AB-1, and adapters are not changed after the first run. A fix that is needed applies to every tool, is logged, and the whole run is redone.
- If CredSweeper is run on B1, its row is marked in-distribution, because its model is trained on CredData.

### Departures from the specification

Each was decided and logged before any tool ran on any AB-1 set, unless the entry says otherwise.

- **Carriers.** The specification names two carrier datasets, both English. WildChat-1M prompts and GitHub issues were added, so that prompts and tickets in it/de/fr/es also start from real material half the time. A first build without them had 20% carriers for those two kinds, and was rebuilt. A second agent (DeepSeek V4.1 Flash) chose the added material and extended the generator, following the maintainers' written instructions, also without access to any nullpii repository.
- **Masked item: whitespace.** The specification counts any unmasked character as a leak. Whitespace and `\n`/`\r`/`\t` layout escapes inside an item are not counted, so masking a key line by line is not a leak.
- **Masked item: punctuation (decided after the scores were first read).** A value counts as masked when every letter and digit of it is masked; the commas and dots between the pieces of an address that a tool masks separately reveal nothing, so they are not counted. Keep rates do not change, since an item is kept when no character of it is masked. The change helps the other tools more than nullpii: with the first rule nullpii had the lowest leak rate on A, with this one rizzo-pii has. Where the rule can be too lenient: a password whose symbols are left between masked pieces counts as masked.
- **Diff structure.** Hunk line counts are checked after masking, instead of `git apply --check`, because the carriers' pre-images are not shipped.
- **Rows.** The specification has two rows per tool: default, and the agent policy where the tool can turn categories off. Instead, each tool is shown at its default and at its tuned operating point (tuned on the tuning set, as in the document benchmark), each raw and with the agent-policy post-filter, which works for every tool.
- **Unmapped labels** are kept, as scoring that ignores labels requires (see Competitors).
- **B2 item.** The scored item is the candidate's core value, not the labelled candidate string, and 70 true secrets are dropped (see Data). The first build kept a leading `name=` inside the value (347 secrets and 416 non-secrets in the set, mostly the record's generic `key=value` pattern), so a tool that masked only the value was counted as leaking it. The final review found this after the tools had run and before any score was read. The gold was rebuilt with the name cut off, with the documents and their order unchanged, so no tool was run again, only scored again.
- **Leak check.** Stricter than specified, with the name exemption described above.
- **Canary.** The canary string is in A's README and in `data/CANARY` next to the gold, not inside the gold's rows.
- **GLiNER windows capped in tokens (during the first run, before any score was read).** The first run of gliner-pii-large ran out of memory on a B1 document. The adapter cut windows by words only, and a few B1 code files (minified lines, long blobs) made windows of up to 60,025 subword tokens (gliner-pii-large) and 75,903 (gliner-stream-pii). Every tool run through the GLiNER adapter now also caps a window at 4,096 subword tokens, a cap chosen from the window sizes, not from any score. Documents changed only where a window had been longer, all in B1 (gliner-pii-large 6, gliner-stream-pii 15, nemotron-pii as a library 5, gliner_multi_pii 4). No window of A or B2 was longer than 1,961 tokens. As the specification requires, the whole run was then redone for every tool.
- **Rerun determinism.** The seven tools that had finished before the cap do not use the GLiNER adapter, so their rerun was compared with their first run, row by row. deberta, piiranha, ettin-68m, rizzo-pii and pii-identifier gave the same spans on every row. openai's privacy-filter and OpenMed privacy-filter-multilingual-v2, served by the same `opf` runtime on CUDA one text at a time, are not bit-deterministic: at most 1.5% of a set's documents differ (privacy-filter tuned on A, 14 of 966), with about as many spans added as dropped. The tables use the rerun.
- **Audit corrections.** The audit's wrong-or-missing share was below the 5% threshold, so no new audit was required. Two annotation rules it exposed were corrected in the generator before the freeze (a UUID right after a session-like key, and an encoded dummy credential, are AMBIGUOUS; 24 items in all). Nothing else changed.

### Results

Every tool ran on the frozen sets; the tables use the run redone after the adapter fix, scored with the corrected rule. Rows are sorted by leak rate, then by keep rate. Intervals are paired bootstrap 95% intervals of nullpii minus the tool, in percentage points: a negative leak difference or a positive keep difference favours nullpii. The aggregates are in [`published-bench/ab1/`](https://github.com/lBroth/nullpii/blob/main/packages/eval/published-bench/ab1). nullpii's rows are from the release build, which includes the three rules described at the end of these results. nullpii's round trip, run with the same build: all 16,572 documents, 13,704 of them with something masked, came back as their exact original text after masking and restoring.

**A. Agent traffic** — one row per tool per operating point, plus its `+agent` variant.

<!-- ab1-a:begin -->
966 documents, 3,386 items that must be masked and 5,676 that must stay readable.

| Tool | Leak rate | Keep rate | Docs with a leak | nullpii − tool, leak | nullpii − tool, keep |
|---|---:|---:|---:|---|---|
| rizzo-pii (tuned, +agent) | 8.1% | 44.5% | 25.1% | [−0.0, +2.6] | [+38.7, +43.4] |
| rizzo-pii (tuned) | 8.1% | 32.6% | 25.1% | [−0.0, +2.6] | [+50.2, +55.6] |
| **nullpii 0.5 (agent default)** | 9.5% | 85.4% | 27.0% | — | — |
| openai privacy-filter (tuned) | 14.2% | 71.8% | 32.9% | [−6.6, −3.0] | [+10.5, +16.6] |
| openai privacy-filter (tuned, +agent) | 14.5% | 77.9% | 33.6% | [−6.9, −3.2] | [+5.0, +9.9] |
| OpenMed PII Large (tuned) | 15.6% | 70.1% | 39.2% | [−8.1, −4.3] | [+13.1, +17.5] |
| OpenMed PII Large (tuned, +agent) | 15.7% | 82.2% | 39.7% | [−8.2, −4.4] | [+1.6, +5.0] |
| gliner-pii-large (tuned) | 15.9% | 78.2% | 37.8% | [−8.5, −4.3] | [+5.0, +9.6] |
| OpenMed PII Small (tuned) | 15.9% | 70.9% | 39.8% | [−8.1, −4.8] | [+12.3, +16.8] |
| gliner-pii-large (tuned, +agent) | 15.9% | 85.5% | 37.8% | [−8.5, −4.4] | [−1.9, +1.6] |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 16.0% | 75.8% | 42.8% | [−8.2, −4.9] | [+7.7, +11.9] |
| nemotron-pii, NVIDIA's server (tuned) | 16.0% | 67.3% | 42.8% | [−8.2, −4.9] | [+15.6, +20.7] |
| OpenMed PII Small (tuned, +agent) | 16.1% | 83.0% | 40.4% | [−8.3, −4.9] | [+0.8, +4.1] |
| gliner-stream-pii (tuned) | 16.3% | 56.2% | 43.3% | [−9.0, −4.9] | [+26.7, +31.8] |
| gliner-stream-pii (tuned, +agent) | 16.4% | 67.5% | 43.3% | [−9.0, −4.9] | [+15.9, +19.9] |
| nemotron-pii, library (tuned, +agent) | 17.6% | 68.4% | 47.9% | [−9.9, −6.3] | [+14.6, +19.4] |
| nemotron-pii, library (tuned) | 17.6% | 62.8% | 47.9% | [−9.9, −6.3] | [+20.0, +25.3] |
| ettin-68m (tuned) | 17.6% | 52.4% | 43.6% | [−10.1, −6.2] | [+30.7, +35.5] |
| ettin-68m (tuned, +agent) | 17.7% | 65.3% | 43.6% | [−10.1, −6.3] | [+18.0, +22.4] |
| pii-identifier (tuned) | 18.7% | 64.5% | 52.5% | [−11.0, −7.6] | [+18.3, +23.6] |
| pii-identifier (tuned, +agent) | 18.8% | 77.7% | 52.5% | [−11.0, −7.7] | [+5.7, +9.8] |
| gliner_multi_pii (ONNX) (tuned) | 19.0% | 48.6% | 44.2% | [−11.4, −7.8] | [+34.1, +39.5] |
| gliner_multi_pii (ONNX) (tuned, +agent) | 19.2% | 56.9% | 44.2% | [−11.6, −7.9] | [+26.0, +31.2] |
| nemotron-pii, NVIDIA's server (default, +agent) | 19.4% | 80.5% | 48.8% | [−11.6, −8.4] | [+3.1, +6.9] |
| nemotron-pii, NVIDIA's server (default) | 19.4% | 69.6% | 48.8% | [−11.6, −8.4] | [+13.1, +18.4] |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 20.1% | 81.6% | 48.3% | [−12.0, −9.1] | [+2.2, +5.6] |
| OpenMed privacy-filter-multilingual-v2 (tuned) | 20.1% | 69.8% | 48.3% | [−12.0, −9.1] | [+13.4, +18.1] |
| nemotron-pii, library (default, +agent) | 20.9% | 80.8% | 52.1% | [−13.2, −9.6] | [+2.6, +6.7] |
| nemotron-pii, library (default) | 20.9% | 70.1% | 52.1% | [−13.2, −9.6] | [+12.7, +18.1] |
| OpenMed privacy-filter-multilingual-v2 (default, +agent) | 22.7% | 84.4% | 52.1% | [−14.8, −11.7] | [−0.6, +2.7] |
| OpenMed privacy-filter-multilingual-v2 (default) | 22.7% | 73.2% | 52.1% | [−14.8, −11.7] | [+10.2, +14.5] |
| piiranha (tuned, +agent) | 23.8% | 68.8% | 56.5% | [−16.5, −12.3] | [+14.5, +18.8] |
| piiranha (tuned) | 23.8% | 62.3% | 56.5% | [−16.5, −12.3] | [+20.6, +25.5] |
| openai privacy-filter (default) | 24.8% | 86.2% | 48.4% | [−17.8, −13.0] | [−3.1, +1.4] |
| openai privacy-filter (default, +agent) | 24.9% | 89.3% | 48.8% | [−18.0, −13.2] | [−5.8, −1.9] |
| OpenMed PII Large (default) | 25.6% | 59.7% | 59.6% | [−18.2, −14.1] | [+23.6, +28.3] |
| OpenMed PII Large (default, +agent) | 25.6% | 70.6% | 59.8% | [−18.2, −14.1] | [+12.7, +17.3] |
| OpenMed PII Small (default) | 26.1% | 57.5% | 58.6% | [−18.6, −14.7] | [+25.6, +30.8] |
| OpenMed PII Small (default, +agent) | 26.2% | 68.8% | 58.9% | [−18.6, −14.7] | [+14.4, +19.1] |
| gliner-pii-large (default) | 30.0% | 87.1% | 55.1% | [−23.2, −18.0] | [−3.3, −0.1] |
| gliner-pii-large (default, +agent) | 30.1% | 90.3% | 55.1% | [−23.2, −18.0] | [−6.3, −3.4] |
| gliner-stream-pii (default, +agent) | 30.2% | 88.3% | 64.0% | [−23.3, −18.4] | [−4.5, −1.3] |
| gliner-stream-pii (default) | 30.2% | 76.9% | 64.0% | [−23.3, −18.4] | [+6.6, +10.6] |
| pii-identifier (default) | 31.8% | 70.3% | 69.5% | [−24.6, −20.4] | [+13.0, +17.4] |
| pii-identifier (default, +agent) | 31.9% | 83.2% | 69.6% | [−24.6, −20.5] | [+0.7, +3.8] |
| rizzo-pii (default) | 32.6% | 65.5% | 68.6% | [−25.7, −20.9] | [+17.3, +22.6] |
| rizzo-pii (default, +agent) | 32.6% | 78.3% | 68.6% | [−25.8, −21.0] | [+5.1, +9.0] |
| ettin-68m (default, +agent) | 33.6% | 80.6% | 65.2% | [−26.6, −21.8] | [+3.0, +6.7] |
| ettin-68m (default) | 33.6% | 67.7% | 65.2% | [−26.6, −21.8] | [+15.5, +20.0] |
| deberta PII (default) | 35.8% | 48.9% | 60.8% | [−29.9, −22.7] | [+33.3, +40.0] |
| deberta PII (default, +agent) | 35.9% | 53.1% | 60.8% | [−29.9, −22.8] | [+29.0, +35.6] |
| gliner_multi_pii (ONNX) (default) | 36.2% | 79.9% | 67.9% | [−29.3, −24.5] | [+3.7, +7.6] |
| gliner_multi_pii (ONNX) (default, +agent) | 36.3% | 86.1% | 67.9% | [−29.4, −24.6] | [−2.3, +0.9] |
| Presidio (default) | 40.3% | 61.8% | 77.5% | [−33.0, −28.8] | [+21.2, +26.1] |
| Presidio (tuned) | 40.4% | 71.6% | 77.6% | [−33.0, −28.8] | [+11.7, +16.2] |
| Presidio (default, +agent) | 40.5% | 72.5% | 77.7% | [−33.2, −29.0] | [+10.6, +15.5] |
| Presidio (tuned, +agent) | 40.6% | 82.3% | 77.9% | [−33.2, −29.0] | [+1.4, +5.1] |
| piiranha (default, +agent) | 48.0% | 97.1% | 83.8% | [−40.7, −36.5] | [−13.1, −10.2] |
| piiranha (default) | 48.0% | 97.0% | 83.8% | [−40.7, −36.5] | [−13.1, −10.2] |
| deberta PII (tuned) | 55.1% | 60.0% | 81.2% | [−48.7, −42.3] | [+22.2, +28.6] |
| deberta PII (tuned, +agent) | 55.1% | 64.2% | 81.2% | [−48.7, −42.4] | [+18.0, +24.3] |

| Tool | Clean docs with anything masked | Masked outside items, per 1,000 chars | Encoded leak rate | JSON still parses | Diff hunks consistent |
|---|---:|---:|---:|---:|---:|
| rizzo-pii (tuned, +agent) | 99.5% | 63.64 | 14.5% | 50.0% | 0.0% |
| **nullpii 0.5 (agent default)** | 61.1% | 10.87 | 2.0% | 91.2% | 100.0% |
| openai privacy-filter (tuned, +agent) | 61.7% | 19.15 | 17.1% | 90.2% | 90.9% |
| OpenMed PII Large (tuned, +agent) | 71.0% | 8.90 | 28.3% | 99.0% | 100.0% |
| gliner-pii-large (tuned, +agent) | 87.0% | 39.55 | 53.3% | 100.0% | 90.9% |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 90.2% | 39.96 | 63.8% | 93.1% | 81.8% |
| OpenMed PII Small (tuned, +agent) | 71.5% | 10.13 | 27.6% | 99.0% | 90.9% |
| gliner-stream-pii (tuned, +agent) | 100.0% | 84.67 | 47.4% | 96.1% | 18.2% |
| nemotron-pii, library (tuned, +agent) | 96.4% | 72.39 | 71.1% | 81.4% | 9.1% |
| ettin-68m (tuned, +agent) | 91.2% | 14.91 | 20.4% | 96.1% | 100.0% |
| pii-identifier (tuned, +agent) | 85.0% | 10.66 | 53.3% | 99.0% | 100.0% |
| gliner_multi_pii (ONNX) (tuned, +agent) | 97.4% | 65.05 | 52.6% | 95.1% | 0.0% |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 80.3% | 13.42 | 11.8% | 96.1% | 100.0% |
| piiranha (tuned, +agent) | 94.8% | 44.39 | 42.8% | 71.6% | 90.9% |
| Presidio (tuned, +agent) | 84.5% | 17.58 | 33.6% | 83.3% | 100.0% |
| deberta PII (tuned, +agent) | 91.7% | 142.52 | 4.6% | 72.5% | 18.2% |

Leak rate per category (items in brackets):

| Tool | account (194) | address (158) | card (53) | driver_license (9) | email (536) | iban (76) | ip (431) | mac (104) | national_id (31) | passport (12) | person (969) | phone (169) | secret (585) | url (59) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rizzo-pii (tuned, +agent) | 0.5% | 1.9% | 0.0% | 0.0% | 0.7% | 0.0% | 3.5% | 32.7% | 0.0% | 0.0% | 6.2% | 4.7% | 25.5% | 0.0% |
| **nullpii 0.5 (agent default)** | 11.3% | 3.8% | 0.0% | 0.0% | 0.0% | 0.0% | 2.3% | 7.7% | 0.0% | 0.0% | 23.5% | 0.0% | 4.8% | 30.5% |
| openai privacy-filter (tuned, +agent) | 17.0% | 10.1% | 3.8% | 0.0% | 1.1% | 1.3% | 32.9% | 28.8% | 6.5% | 0.0% | 22.3% | 3.0% | 5.5% | 8.5% |
| OpenMed PII Large (tuned, +agent) | 34.0% | 17.1% | 1.9% | 0.0% | 2.6% | 5.3% | 0.9% | 9.6% | 9.7% | 25.0% | 10.1% | 42.0% | 34.7% | 49.2% |
| gliner-pii-large (tuned, +agent) | 20.6% | 10.8% | 1.9% | 0.0% | 6.3% | 7.9% | 12.1% | 70.2% | 12.9% | 0.0% | 22.9% | 1.2% | 9.4% | 57.6% |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 8.2% | 10.1% | 5.7% | 0.0% | 7.3% | 9.2% | 28.5% | 14.4% | 3.2% | 8.3% | 17.9% | 2.4% | 17.4% | 69.5% |
| OpenMed PII Small (tuned, +agent) | 25.8% | 36.1% | 3.8% | 11.1% | 3.7% | 5.3% | 0.9% | 9.6% | 9.7% | 33.3% | 16.9% | 43.8% | 20.9% | 50.8% |
| gliner-stream-pii (tuned, +agent) | 10.3% | 24.7% | 7.5% | 0.0% | 13.6% | 34.2% | 7.2% | 31.7% | 6.5% | 0.0% | 20.0% | 12.4% | 10.4% | 84.7% |
| nemotron-pii, library (tuned, +agent) | 4.6% | 14.6% | 15.1% | 0.0% | 41.6% | 7.9% | 16.9% | 26.0% | 3.2% | 0.0% | 9.6% | 1.8% | 12.6% | 94.9% |
| ettin-68m (tuned, +agent) | 32.0% | 8.9% | 24.5% | 0.0% | 1.7% | 47.4% | 20.6% | 26.9% | 16.1% | 33.3% | 7.2% | 16.6% | 32.8% | 81.4% |
| pii-identifier (tuned, +agent) | 16.0% | 7.0% | 47.2% | 22.2% | 6.7% | 27.6% | 6.3% | 26.9% | 16.1% | 0.0% | 20.2% | 7.7% | 33.8% | 71.2% |
| gliner_multi_pii (ONNX) (tuned, +agent) | 7.2% | 9.5% | 17.0% | 0.0% | 6.3% | 2.6% | 24.4% | 57.7% | 3.2% | 0.0% | 29.5% | 2.4% | 18.1% | 23.7% |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 20.1% | 38.6% | 5.7% | 0.0% | 7.3% | 42.1% | 4.9% | 18.3% | 3.2% | 8.3% | 30.4% | 1.2% | 26.7% | 16.9% |
| piiranha (tuned, +agent) | 13.9% | 5.7% | 0.0% | 0.0% | 7.1% | 82.9% | 9.5% | 80.8% | 0.0% | 50.0% | 3.0% | 0.6% | 76.6% | 100.0% |
| Presidio (tuned, +agent) | 59.8% | 94.9% | 17.0% | 55.6% | 0.7% | 0.0% | 0.0% | 0.0% | 51.6% | 50.0% | 51.6% | 13.6% | 93.2% | 0.0% |
| deberta PII (tuned, +agent) | 68.0% | 63.9% | 49.1% | 0.0% | 47.4% | 46.1% | 41.1% | 9.6% | 48.4% | 0.0% | 74.2% | 44.4% | 49.7% | 54.2% |
<!-- ab1-a:end -->

**B1. CredData** — aggregates only. **B2. Issue secrets** — aggregates only, and no document or value is ever printed.

<!-- ab1-b1:begin -->
4,000 documents, 2,000 items that must be masked and 2,000 that must stay readable.

| Tool | Leak rate | Keep rate | Docs with a leak | nullpii − tool, leak | nullpii − tool, keep |
|---|---:|---:|---:|---|---|
| openai privacy-filter (tuned, +agent) | 13.2% | 77.1% | 13.2% | [+9.0, +13.7] | [−14.7, −10.1] |
| openai privacy-filter (tuned) | 13.2% | 77.0% | 13.2% | [+9.0, +13.7] | [−14.6, −9.9] |
| nemotron-pii, library (tuned, +agent) | 14.5% | 34.0% | 14.5% | [+8.0, +12.0] | [+28.2, +33.1] |
| nemotron-pii, library (tuned) | 14.5% | 32.8% | 14.5% | [+8.0, +12.0] | [+29.4, +34.3] |
| gliner-pii-large (tuned, +agent) | 16.7% | 61.1% | 16.7% | [+6.0, +9.7] | [+1.1, +6.3] |
| gliner-pii-large (tuned) | 16.7% | 59.8% | 16.7% | [+6.0, +9.7] | [+2.4, +7.6] |
| gliner-stream-pii (tuned) | 17.7% | 22.5% | 17.7% | [+4.9, +8.6] | [+39.7, +44.7] |
| gliner-stream-pii (tuned, +agent) | 17.8% | 23.1% | 17.8% | [+4.7, +8.5] | [+39.0, +44.1] |
| gliner_multi_pii (ONNX) (tuned, +agent) | 20.5% | 16.1% | 20.5% | [+2.0, +5.8] | [+46.2, +51.1] |
| gliner_multi_pii (ONNX) (tuned) | 20.5% | 14.5% | 20.5% | [+2.0, +5.8] | [+47.8, +52.7] |
| rizzo-pii (tuned, +agent) | 20.6% | 49.8% | 20.6% | [+1.6, +6.1] | [+12.6, +17.4] |
| rizzo-pii (tuned) | 20.6% | 48.4% | 20.6% | [+1.6, +6.1] | [+13.9, +18.7] |
| openai privacy-filter (default) | 21.1% | 92.7% | 21.1% | [+0.9, +6.1] | [−30.0, −25.8] |
| openai privacy-filter (default, +agent) | 21.1% | 92.7% | 21.1% | [+0.9, +6.1] | [−30.0, −25.8] |
| nemotron-pii, library (default, +agent) | 21.6% | 58.1% | 21.6% | [+0.7, +5.2] | [+4.4, +9.1] |
| nemotron-pii, library (default) | 21.6% | 56.5% | 21.6% | [+0.7, +5.2] | [+5.8, +10.7] |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 21.9% | 53.7% | 21.9% | [+0.4, +5.1] | [+8.5, +13.6] |
| nemotron-pii, NVIDIA's server (tuned) | 21.9% | 52.3% | 21.9% | [+0.4, +5.1] | [+9.7, +15.0] |
| gliner-pii-large (default, +agent) | 24.3% | 76.2% | 24.3% | [−1.6, +2.1] | [−14.1, −9.1] |
| gliner-pii-large (default) | 24.3% | 75.4% | 24.3% | [−1.6, +2.1] | [−13.3, −8.1] |
| **nullpii 0.5 (agent default)** | 24.5% | 64.8% | 24.5% | — | — |
| nemotron-pii, NVIDIA's server (default, +agent) | 32.1% | 68.2% | 32.1% | [−10.0, −4.9] | [−5.9, −1.0] |
| nemotron-pii, NVIDIA's server (default) | 32.1% | 66.8% | 32.1% | [−10.0, −4.9] | [−4.6, +0.5] |
| OpenMed PII Large (tuned, +agent) | 32.2% | 83.7% | 32.2% | [−10.0, −5.3] | [−21.2, −16.7] |
| OpenMed PII Large (tuned) | 32.2% | 82.1% | 32.2% | [−10.0, −5.3] | [−19.6, −15.0] |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 42.9% | 76.6% | 42.9% | [−20.9, −15.6] | [−14.2, −9.4] |
| OpenMed privacy-filter-multilingual-v2 (tuned) | 42.9% | 75.1% | 42.9% | [−20.9, −15.6] | [−12.7, −7.9] |
| OpenMed PII Small (tuned, +agent) | 43.8% | 78.8% | 43.8% | [−22.0, −16.5] | [−16.4, −11.9] |
| OpenMed PII Small (tuned) | 43.8% | 77.3% | 43.8% | [−22.0, −16.5] | [−15.0, −10.5] |
| ettin-68m (tuned, +agent) | 45.4% | 64.0% | 45.4% | [−23.6, −18.0] | [−1.5, +2.8] |
| ettin-68m (tuned) | 45.4% | 63.0% | 45.4% | [−23.6, −18.0] | [−0.5, +4.0] |
| gliner-stream-pii (default) | 46.6% | 63.5% | 46.6% | [−24.6, −19.6] | [−1.3, +3.8] |
| gliner-stream-pii (default, +agent) | 46.7% | 64.5% | 46.7% | [−24.7, −19.6] | [−2.4, +2.7] |
| OpenMed privacy-filter-multilingual-v2 (default, +agent) | 46.8% | 82.0% | 46.8% | [−24.8, −19.6] | [−19.5, −14.9] |
| OpenMed privacy-filter-multilingual-v2 (default) | 46.8% | 80.5% | 46.8% | [−24.8, −19.6] | [−18.0, −13.4] |
| OpenMed PII Large (default, +agent) | 52.4% | 74.6% | 52.4% | [−30.5, −25.4] | [−12.6, −7.0] |
| OpenMed PII Large (default) | 52.4% | 73.3% | 52.4% | [−30.5, −25.4] | [−11.3, −5.7] |
| deberta PII (default, +agent) | 54.4% | 63.4% | 54.4% | [−32.3, −27.5] | [−1.5, +4.2] |
| deberta PII (default) | 54.4% | 63.3% | 54.4% | [−32.3, −27.5] | [−1.4, +4.3] |
| pii-identifier (tuned, +agent) | 54.5% | 78.5% | 54.5% | [−32.9, −27.2] | [−16.3, −11.4] |
| pii-identifier (tuned) | 54.5% | 77.5% | 54.5% | [−32.9, −27.2] | [−15.2, −10.4] |
| deberta PII (tuned, +agent) | 58.3% | 74.2% | 58.3% | [−36.1, −31.2] | [−12.3, −6.6] |
| deberta PII (tuned) | 58.3% | 74.0% | 58.3% | [−36.1, −31.2] | [−12.0, −6.5] |
| gliner_multi_pii (ONNX) (default, +agent) | 61.2% | 39.0% | 61.2% | [−39.2, −34.2] | [+23.1, +28.5] |
| gliner_multi_pii (ONNX) (default) | 61.2% | 37.4% | 61.2% | [−39.2, −34.2] | [+24.5, +30.1] |
| OpenMed PII Small (default, +agent) | 62.6% | 68.7% | 62.6% | [−40.9, −35.4] | [−6.5, −1.4] |
| OpenMed PII Small (default) | 62.6% | 67.4% | 62.6% | [−40.9, −35.4] | [−5.2, −0.1] |
| ettin-68m (default, +agent) | 63.6% | 82.0% | 63.6% | [−42.0, −36.4] | [−19.5, −15.0] |
| ettin-68m (default) | 63.6% | 81.2% | 63.6% | [−42.0, −36.4] | [−18.7, −14.1] |
| piiranha (tuned, +agent) | 72.2% | 63.2% | 72.2% | [−50.3, −45.3] | [−0.9, +4.0] |
| piiranha (tuned) | 72.2% | 61.7% | 72.2% | [−50.3, −45.3] | [+0.6, +5.6] |
| pii-identifier (default, +agent) | 74.9% | 88.5% | 74.9% | [−52.9, −47.8] | [−26.0, −21.7] |
| pii-identifier (default) | 74.9% | 87.8% | 74.9% | [−52.9, −47.8] | [−25.3, −20.9] |
| piiranha (default) | 85.2% | 95.0% | 85.2% | [−62.9, −58.6] | [−32.3, −28.0] |
| piiranha (default, +agent) | 85.2% | 95.0% | 85.2% | [−62.9, −58.6] | [−32.3, −28.0] |
| rizzo-pii (default, +agent) | 89.2% | 85.2% | 89.2% | [−66.8, −62.4] | [−22.8, −18.1] |
| rizzo-pii (default) | 89.2% | 84.2% | 89.2% | [−66.8, −62.4] | [−21.7, −17.1] |
| Presidio (default) | 94.2% | 63.5% | 94.2% | [−71.8, −67.6] | [−1.6, +4.2] |
| Presidio (tuned) | 94.3% | 74.5% | 94.3% | [−71.9, −67.7] | [−12.2, −7.1] |
| Presidio (default, +agent) | 94.8% | 65.6% | 94.8% | [−72.3, −68.2] | [−3.6, +2.1] |
| Presidio (tuned, +agent) | 95.0% | 76.6% | 95.0% | [−72.4, −68.4] | [−14.3, −9.4] |
<!-- ab1-b1:end -->

<!-- ab1-b2:begin -->
11,606 documents, 5,776 items that must be masked and 5,651 that must stay readable.

| Tool | Leak rate | Keep rate | Docs with a leak | nullpii − tool, leak | nullpii − tool, keep |
|---|---:|---:|---:|---|---|
| openai privacy-filter (tuned, +agent) | 8.2% | 74.6% | 8.2% | [+2.5, +4.2] | [+1.2, +4.1] |
| openai privacy-filter (tuned) | 8.2% | 74.5% | 8.2% | [+2.5, +4.2] | [+1.3, +4.2] |
| **nullpii 0.5 (agent default)** | 11.5% | 77.2% | 11.5% | — | — |
| openai privacy-filter (default, +agent) | 13.5% | 86.2% | 13.5% | [−3.0, −0.9] | [−10.3, −7.6] |
| openai privacy-filter (default) | 13.5% | 86.2% | 13.5% | [−3.0, −0.9] | [−10.2, −7.6] |
| rizzo-pii (tuned) | 19.5% | 52.9% | 19.5% | [−9.2, −6.8] | [+23.0, +25.9] |
| rizzo-pii (tuned, +agent) | 19.5% | 53.0% | 19.5% | [−9.2, −6.8] | [+22.8, +25.8] |
| gliner-pii-large (tuned, +agent) | 21.3% | 66.7% | 21.3% | [−10.9, −8.6] | [+9.0, +12.0] |
| gliner-pii-large (tuned) | 21.3% | 66.6% | 21.3% | [−10.9, −8.6] | [+9.0, +12.1] |
| gliner-stream-pii (tuned) | 24.3% | 58.2% | 24.3% | [−13.9, −11.6] | [+17.5, +20.7] |
| gliner-stream-pii (tuned, +agent) | 24.4% | 58.5% | 24.4% | [−14.0, −11.7] | [+17.1, +20.4] |
| nemotron-pii, NVIDIA's server (tuned) | 30.4% | 54.5% | 30.4% | [−20.2, −17.5] | [+21.2, +24.5] |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 30.4% | 54.6% | 30.4% | [−20.2, −17.5] | [+21.0, +24.4] |
| gliner_multi_pii (ONNX) (tuned) | 31.0% | 45.0% | 31.0% | [−20.7, −18.2] | [+30.6, +33.9] |
| gliner_multi_pii (ONNX) (tuned, +agent) | 31.1% | 45.2% | 31.1% | [−20.9, −18.3] | [+30.3, +33.7] |
| OpenMed PII Small (tuned) | 31.9% | 79.5% | 31.9% | [−21.6, −19.0] | [−3.4, −1.0] |
| OpenMed PII Small (tuned, +agent) | 31.9% | 79.9% | 31.9% | [−21.6, −19.0] | [−3.8, −1.5] |
| nemotron-pii, library (tuned) | 32.3% | 54.4% | 32.3% | [−22.1, −19.5] | [+21.2, +24.4] |
| nemotron-pii, library (tuned, +agent) | 32.3% | 54.6% | 32.3% | [−22.1, −19.5] | [+21.0, +24.3] |
| ettin-68m (tuned) | 33.0% | 54.9% | 33.0% | [−22.7, −20.1] | [+20.8, +23.8] |
| ettin-68m (tuned, +agent) | 33.0% | 55.1% | 33.0% | [−22.7, −20.1] | [+20.7, +23.7] |
| OpenMed privacy-filter-multilingual-v2 (tuned) | 35.6% | 65.0% | 35.6% | [−25.4, −22.7] | [+10.7, +13.8] |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 35.6% | 65.1% | 35.6% | [−25.4, −22.7] | [+10.6, +13.6] |
| pii-identifier (tuned) | 37.4% | 75.6% | 37.4% | [−27.3, −24.6] | [+0.2, +2.9] |
| pii-identifier (tuned, +agent) | 37.4% | 75.9% | 37.4% | [−27.3, −24.6] | [−0.1, +2.7] |
| OpenMed PII Large (tuned) | 39.4% | 77.9% | 39.4% | [−29.3, −26.4] | [−1.9, +0.7] |
| OpenMed PII Large (tuned, +agent) | 39.5% | 78.2% | 39.5% | [−29.4, −26.6] | [−2.3, +0.3] |
| OpenMed privacy-filter-multilingual-v2 (default) | 40.2% | 69.8% | 40.2% | [−30.0, −27.4] | [+6.0, +9.0] |
| OpenMed privacy-filter-multilingual-v2 (default, +agent) | 40.2% | 69.9% | 40.2% | [−30.1, −27.4] | [+5.9, +8.8] |
| nemotron-pii, library (default) | 40.7% | 69.9% | 40.7% | [−30.5, −27.9] | [+5.9, +8.8] |
| nemotron-pii, library (default, +agent) | 40.7% | 70.1% | 40.7% | [−30.5, −27.9] | [+5.7, +8.6] |
| nemotron-pii, NVIDIA's server (default) | 42.5% | 64.8% | 42.5% | [−32.3, −29.5] | [+11.0, +14.0] |
| nemotron-pii, NVIDIA's server (default, +agent) | 42.5% | 64.9% | 42.5% | [−32.3, −29.5] | [+10.8, +13.8] |
| gliner-pii-large (default) | 42.9% | 72.7% | 42.9% | [−32.6, −30.1] | [+3.2, +5.8] |
| gliner-pii-large (default, +agent) | 42.9% | 72.8% | 42.9% | [−32.6, −30.1] | [+3.2, +5.8] |
| deberta PII (default) | 50.9% | 69.7% | 50.9% | [−40.9, −37.7] | [+5.9, +9.2] |
| deberta PII (default, +agent) | 50.9% | 70.2% | 50.9% | [−41.0, −37.8] | [+5.5, +8.7] |
| deberta PII (tuned) | 55.0% | 78.8% | 55.0% | [−45.1, −41.8] | [−3.0, −0.1] |
| deberta PII (tuned, +agent) | 55.0% | 79.2% | 55.0% | [−45.1, −41.8] | [−3.5, −0.5] |
| OpenMed PII Small (default) | 57.4% | 54.4% | 57.4% | [−47.4, −44.5] | [+21.2, +24.5] |
| OpenMed PII Small (default, +agent) | 57.4% | 54.7% | 57.4% | [−47.4, −44.5] | [+20.9, +24.2] |
| ettin-68m (default, +agent) | 64.8% | 65.9% | 64.8% | [−54.5, −51.9] | [+9.9, +12.9] |
| ettin-68m (default) | 64.8% | 65.7% | 64.8% | [−54.5, −51.9] | [+10.0, +13.0] |
| gliner-stream-pii (default) | 64.8% | 80.4% | 64.8% | [−54.7, −52.0] | [−4.5, −1.7] |
| gliner-stream-pii (default, +agent) | 64.9% | 80.7% | 64.9% | [−54.7, −52.0] | [−4.8, −2.0] |
| gliner_multi_pii (ONNX) (default) | 68.2% | 75.0% | 68.2% | [−58.0, −55.4] | [+0.7, +3.7] |
| gliner_multi_pii (ONNX) (default, +agent) | 68.3% | 75.2% | 68.3% | [−58.0, −55.4] | [+0.5, +3.5] |
| rizzo-pii (default) | 75.0% | 68.1% | 75.0% | [−64.8, −62.1] | [+7.6, +10.7] |
| rizzo-pii (default, +agent) | 75.0% | 68.3% | 75.0% | [−64.8, −62.2] | [+7.5, +10.5] |
| pii-identifier (default) | 76.7% | 70.7% | 76.7% | [−66.3, −64.0] | [+5.1, +8.0] |
| pii-identifier (default, +agent) | 76.7% | 70.9% | 76.7% | [−66.4, −64.0] | [+5.0, +7.9] |
| Presidio (default) | 77.2% | 55.1% | 77.2% | [−66.9, −64.4] | [+20.5, +23.9] |
| Presidio (default, +agent) | 77.8% | 55.5% | 77.8% | [−67.5, −65.0] | [+20.1, +23.5] |
| OpenMed PII Large (default) | 77.8% | 55.8% | 77.8% | [−67.6, −65.0] | [+19.8, +23.2] |
| OpenMed PII Large (default, +agent) | 77.9% | 56.1% | 77.9% | [−67.6, −65.1] | [+19.5, +22.8] |
| Presidio (tuned) | 78.4% | 66.9% | 78.4% | [−68.1, −65.6] | [+8.8, +11.9] |
| Presidio (tuned, +agent) | 79.1% | 67.3% | 79.1% | [−68.7, −66.3] | [+8.4, +11.6] |
| piiranha (tuned, +agent) | 92.3% | 72.9% | 92.3% | [−81.8, −79.7] | [+2.8, +5.9] |
| piiranha (tuned) | 92.3% | 72.7% | 92.3% | [−81.8, −79.7] | [+2.9, +6.1] |
| piiranha (default) | 99.1% | 98.1% | 99.1% | [−88.4, −86.7] | [−22.0, −19.7] |
| piiranha (default, +agent) | 99.1% | 98.1% | 99.1% | [−88.4, −86.7] | [−22.0, −19.7] |
<!-- ab1-b2:end -->

**Secrets by recognizer coverage.** The secrets' leak rate, in each set, on the items nullpii's recognizer pack covers and on the rest. An item is covered when the pack, run alone on the raw text without the model or the base64 pass, masks every letter and digit of the value. This split was computed after the freeze, from the pack itself, and is only reported. Items: A 88 covered of 585, B1 125 of 2,000, B2 1,979 of 5,776 (the release build's pack no longer has the UUID recognizer).

<!-- ab1-coverage:begin -->
| Tool | A covered (88) | A not covered (497) | B1 covered (125) | B1 not covered (1,875) | B2 covered (1,979) | B2 not covered (3,797) |
|---|---:|---:|---:|---:|---:|---:|
| rizzo-pii (tuned, +agent) | 20.5% | 26.4% | 44.0% | 19.0% | 12.1% | 23.4% |
| **nullpii 0.5 (agent default)** | 0.0% | 5.6% | 0.8% | 26.1% | 0.7% | 17.2% |
| openai privacy-filter (tuned, +agent) | 6.8% | 5.2% | 8.0% | 13.5% | 4.3% | 10.2% |
| OpenMed PII Large (tuned, +agent) | 20.5% | 37.2% | 66.4% | 29.9% | 51.0% | 33.5% |
| gliner-pii-large (tuned, +agent) | 15.9% | 8.2% | 51.2% | 14.4% | 17.6% | 23.2% |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 30.7% | 15.1% | 60.0% | 19.3% | 45.8% | 22.4% |
| OpenMed PII Small (tuned, +agent) | 15.9% | 21.7% | 59.2% | 42.7% | 45.3% | 24.9% |
| gliner-stream-pii (tuned, +agent) | 10.2% | 10.5% | 63.2% | 14.8% | 22.2% | 25.5% |
| nemotron-pii, library (tuned, +agent) | 29.5% | 9.7% | 59.2% | 11.6% | 55.2% | 20.4% |
| ettin-68m (tuned, +agent) | 39.8% | 31.6% | 52.0% | 44.9% | 19.6% | 40.0% |
| pii-identifier (tuned, +agent) | 45.5% | 31.8% | 72.8% | 53.3% | 28.0% | 42.3% |
| gliner_multi_pii (ONNX) (tuned, +agent) | 19.3% | 17.9% | 50.4% | 18.5% | 28.7% | 32.4% |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 30.7% | 26.0% | 50.4% | 42.3% | 40.0% | 33.3% |
| piiranha (tuned, +agent) | 94.3% | 73.4% | 88.8% | 71.1% | 96.3% | 90.3% |
| Presidio (tuned, +agent) | 90.9% | 93.6% | 61.6% | 97.2% | 45.9% | 96.3% |
| deberta PII (tuned, +agent) | 65.9% | 46.9% | 86.4% | 56.4% | 45.6% | 59.9% |
<!-- ab1-coverage:end -->

**Three rules from end-to-end testing.** Real Claude Code sessions showed values an agent works with being masked: UUIDs as account numbers (a recognizer and the model both labelled them so), IPv4 addresses as phone or account numbers (so the documentation, private and loopback ranges the IP recognizer leaves readable were masked too), and "Claude" as a person. Three rules fix them (`src/uuid-filter.ts`, `src/ip-filter.ts`, `src/product-names.ts`): a UUID labelled an account number stays readable, unless a credential-named key comes right before it on its line; an IPv4 address is left to the IP recognizer; "Claude" alone or with a product word is not a person. Each was decided from the label schema and from this benchmark's specification (written and frozen before the run, it lists UUIDs, documentation addresses, `127.0.0.1` and product names as text to keep), before any score was read. They were added after the first run, so nullpii's rows are from the release code; the other tools' rows are unaffected.

On A they leave the leak rate where it was and raise the keep rate: UUIDs kept readable 97.9%, reserved addresses (`example.com` and `.test` addresses, `127.0.0.1`, `0.0.0.0`, `::1`, documentation IPs) 57.5%. On B1, 268 of nullpii's leaks are items CredData labels `UUID`: B1 inherits CredData's labels, and CredData counts 294 UUIDs as credentials, mostly after keys that name ids (`id`, `uid`, `_postman_id`, `collectionId`) or after no key; this specification lists UUIDs as text to keep. nullpii lets 268 of those 294 through, and 222 of B1's other 1,706 secrets (13.0%). As an analysis made after the scores were read (it changes no published row): with every item of kind `UUID` removed from B1's gold, nullpii lets 13.0% through, the fewest of all tools (openai privacy-filter 13.6%, nemotron-pii as a library 16.2%).

### Limits

- The values put into A are fictional and generated. They have valid formats, drawn from real providers' layouts, but a generated key is not a leaked key: AB-1 measures whether a masker finds the shapes, not whether a real credential of that shape still works.
- A's file, shell and log carriers are English. Only the prompt and ticket kinds cover it/de/fr/es, and their non-English material comes from chat-assistant prompts (WildChat-1M) and GitHub issues.
- The WildChat-1M prompts are written to a chat assistant, not to a coding agent: they are real non-English programming questions, one model of what a user types, not agent traffic.
- A is one specification's view of agent traffic, built by one agent and audited on 10% of its documents. Claude Code-style tools are the model: another agent's traffic (different tool schemas, different file kinds) is not represented.
- B1 and B2 hold secrets and secret-looking non-secrets only: they say nothing about names, contact details or the other categories.
- Real names already in carrier text (for example a signature at the end of a GitHub issue) are not annotated, because the builder's carrier pass finds emails, phones, IPs and key-like strings, not names. Masking one counts only in the masked-outside-items figure, never in the leak or keep rate. The audit found one in its 120 documents.
- The components are scored separately and are not averaged into one AB-1 score; a tool can lead on one and trail on another.

### Licences and attribution

- Component A's carriers: [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) CC BY 4.0; [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) MIT; [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) ODC-BY 1.0, cited as Zhao, Ren, Hessel, Cardie, Choi, Deng, "WildChat: 1M ChatGPT Interaction Logs in the Wild", ICLR 2024; each GitHub issue keeps the SPDX licence of its repository, recorded per document. Repositories were found through GitHub's Multilingual Repositories Dataset (CC0-1.0, commit `3d63dbdb61f69663486309a1f8805a1c8eb4a353`), which was used only to find repositories.
- The published gold of A does not redistribute GitHub issue text: it holds the issue URL and the offsets, with a script to rebuild the text.
- Value lists: Wikidata (CC0) and GeoNames (CC BY 4.0); key formats: gitleaks v8.30.1, commit `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` (MIT).
- B1: Samsung/CredData (Apache-2.0), source files under their repositories' own licences, published as aggregates only. B2: Zenodo record 17430335 (CC BY 4.0), aggregates only.
- Component A's generator, its handmade lists and its gold are Apache-2.0; carrier excerpts keep their dataset's or repository's licence.

### Reproduce

The AB-1 scripts are published under `packages/eval/scripts/ab1/`: `agent_metrics.py` (the scorer), `b1_build.py`, `b2_build.py`, `leak_check.py`, `recognizer_spans.mjs` and `secret_coverage.py` (the coverage split), `roundtrip.mjs` and `render_ab1.py` (the tables). Component A's generator, value lists, gold and freeze manifest are in [`datasets/ab1/`](https://github.com/lBroth/nullpii/blob/main/packages/eval/datasets/ab1), with the builder's README. The scorer was written and hashed before the first run, and corrected once after the scores were first read (see Departures).

## Data

- **Tuning set.** Held-out slices of Isotonic (en, de, fr, it), ai4privacy-300k, and a set of synthetic coding-agent traces. Every choice is made on this set: nullpii's changes and thresholds, and every competitor's operating point. It is close to nullpii's home distribution, which is why nothing is claimed from it.
- **Report set (R3), gated.** Five datasets: four public sets and a synthetic coding-agent trace set. They were chosen by written criteria (licence, independence from every compared tool's declared training data, domain and language coverage) and frozen by SHA-256 before any tool ran on them:
  - REDACT (EU-language and English records of its locked test split);
  - TonicAI's human-annotated Privacy-Bench;
  - PIILO (student essays);
  - eu-clinical (Greek clinical notes and German letters);
  - traces-v3: coding-agent transcripts from a generator written by an agent that saw only a written spec, never this project's generators, corpora or tuning sets. The maintainers wrote the spec. It uses nullpii's label names, and it treats public URLs, placeholders and similar text as distractors, as nullpii's product scope does.
- **Reported, not gated:** RedactionBench (untyped gold), mama-deid's validation split (gold checked only by models), and traces-v3 with its distractor regions ignored.
- **Overlap check.** Before any tool was scored, each set was compared, using one in eight 10-word shingles, with nullpii's training corpus and tuning texts, the earlier trace sets, Nemotron-PII, the ai4privacy 200k, 400k and open-500k sets, Isotonic, urchade's synthetic PII set and both Gretel PII sets. The criteria written before the sets were built named 64-character windows. 10-word shingles of lowercased words (about 60 characters) were used instead, decided before any tool was scored, because nullpii's training corpus is stored tokenized and character windows would never line up with it. The 1% threshold is unchanged. No set reaches 1% overlap with any of them. The check covers declared, public training data only. Some tools declare none, or not all (openai's privacy-filter; rizzo-pii names two of its four sources). And three declared sources were not compared: openpii-1m, the Privy-style data on OpenMed privacy-filter-multilingual-v2's card, and the Italian sets behind rizzo-pii.
- **PIIMB.** The public PIIMB leaderboard's `sentences` subset, scored with the leaderboard's own protocol, is reported separately.

Two of the things compared here are built for documents. PIILO is a set of student essays, human-annotated for a Kaggle competition; among names, only the students' own are gold (`scripts/r3/CRITERIA.md`). rizzo-pii is a document anonymiser. The pipeline run here is the one its desktop app serves (`analyze()`, with PDF text extraction in the app), and its model and training corpus are Italian-first. Both are about document anonymisation. That is a different job from masking a coding agent's traffic (prompts, file reads, shell output, logs, tool-call arguments), which is the job nullpii's default is built for.

## Metric

- **Character level, labels ignored.** A personal-data character counts as protected if any predicted span covers it, whatever label the tool gave. This is what a user cares about (what reaches the model unmasked), and it removes differences in how tools' labels map.
  - recall = covered gold characters / gold characters (1 − leak rate);
  - precision = covered gold characters / masked characters (1 − over-masking).
- **F2 decides; F1 and F0.5 are reported next to it.** F2 counts recall as twice as important as precision (β = 2). That is the product's priority, and it rewards over-masking. A mask-everything row shows the floor.
- **Core label space.** Scores use the categories every dataset labels (persons, contact details, addresses, dates, identifiers, URLs, IPs, secrets). nullpii's extended categories (organisations, occupations, demographic and sensitive attributes, titles) were on by default before 0.5; the 0.5 default turns them off, and dates too. R3 reports nullpii with the five off (the core regime) and with every category masked (the old default), the latter both raw and filtered to the core labels.
- **Macro over datasets**, with a leave-one-dataset-out range so one dataset cannot carry the result.
- **Paired bootstrap, 95% CIs** of nullpii minus each tool, 1,000 resamples. Resampling is by document, except traces-v3, which is resampled by generator template. As a sensitivity check, every set is also resampled by its recorded source document or conversation. The test fixed before the run is this uncorrected 95% interval over the 14 tools. NVIDIA's reference server, added after the first look, is reported as a 15th comparison under the same test. Intervals corrected for those 15 comparisons (Bonferroni, 99.67%) were added after the run, as a check, and are reported next to them.

## Competitors, run as shipped

- Each tool runs through its authors' inference path: their library or app pipeline, chunker, decoder and rule layers, the label strings of their card, and their recommended device and precision. Where the authors ship a product-level call, it is used (rizzo-pii's app `analyze()`, OpenMed's `deidentify`, Presidio's multilingual engine with each text's language). Third-party code is copied verbatim where needed, with its licence.
- Departures from that path, each so that every tool reads the whole text:
  - the token classifiers (piiranha, deberta, ettin, pii-identifier, and rizzo-pii's model inside its app) run over token windows of their trained length, stitched by overlap, where their pipelines would truncate;
  - the GLiNER tools run over word windows of the model's `max_len`, where the library drops the words past it. On dense code a window can reach several thousand subword tokens, beyond the trained length (in AB-1 a window also holds at most 4,096 tokens; see its departures);
  - gliner_multi_pii runs as onnx-community's ONNX export of `urchade/gliner_multi_pii-v1`, on the CPU as the library does for ONNX; on 300 AB-1 documents its entities are identical to the original PyTorch weights' (1,777 of 1,777, largest score difference 0.0014);
  - gliner-stream-pii runs in 2,048-word windows, one at a time, because its card's whole-text mode ran out of GPU memory;
  - OpenMed runs with `lang='en'` on every text, because another language silently swaps its Small model;
  - `nvidia/gliner-PII` is shown as run through the GLiNER library with its card's labels and threshold. NVIDIA's reference server (the one NeMo Guardrails calls: 384-character chunks, one entity kept per value) was added after the first R3 look and scores lower (0.591).
- Model revisions are pinned. The pins were set after the runs. A rerun of 20 documents reproduced the spans of every tool but NVIDIA's server pipeline (added later), except two tools whose spans differ only because of how texts are batched.
- Every tool runs at its default operating point and at one tuned on the tuning set for macro char-F2. Tuning sets the threshold, a bias against the model's "no entity" class for token classifiers, and per-label score cuts. The kit applies them where the tool has no option for it, and uses the pipeline's own setting where it has one (OpenMed's `confidence_threshold`, the Viterbi background bias of openai's privacy-filter, the threshold of NVIDIA's server). nullpii's changes were also held to a per-label recall guard and an over-masking cap; the competitors' tuning was not. The tuned values are in `published-bench/r3/operating-points.json`.
- Tables show each tool at its better row, chosen on R3 itself; a claim against a tool is tested against that row, which can only favour the tool.
- Texts a tool refuses or fails on score as no output, and are counted. As a sensitivity check, scores are recomputed for every tool without those texts.

**Languages each model's card declares** (Hugging Face model card metadata and text, 25 Oct 2026). Every tool is run on every document, including those in languages its card does not claim; the English-only results in the README show the comparison without that.

| Tool | Model | Card languages |
|---|---|---|
| deberta | `lakshyakh93/deberta_finetuned_pii` | English |
| piiranha | `iiiorg/piiranha-v1-detect-personal-information` | en, it, fr, de, nl, es |
| ettin-68m | `kalyan-ks/ettin-68m-nemotron-pii` | English |
| rizzo-pii | `rizzoaiacademy/rizzo-pii-0.3B` | Italian-first; trained on 8 languages |
| pii-identifier | `antoniogr7/pii-identifier-v0.1` | English |
| openai privacy-filter | `openai/privacy-filter` | "Primarily English" |
| OpenMed privacy-filter-multilingual-v2 | `OpenMed/privacy-filter-multilingual-v2` | 16: ar, bn, de, en, es, fr, hi, it, ja, ko, nl, pt, te, tr, vi, zh |
| gliner-pii-large-v1 | `knowledgator/gliner-pii-large-v1.0` | English |
| gliner-stream-pii | `knowledgator/gliner-stream-pii-v1.0` | English |
| nemotron-pii (library and NVIDIA's server) | `nvidia/gliner-PII` | English |
| gliner_multi_pii | `urchade/gliner_multi_pii-v1` (ONNX export) | en, fr, de, es, pt, it |
| OpenMed small, large | `OpenMed/OpenMed-PII-SuperClinical-{Small-44M,Large-434M}-v1` | English (run with `lang='en'`) |
| Presidio | library, spaCy pipelines | the text's language, through the spaCy pipeline the kit loads for it |
| nullpii | fine-tuned from `urchade/gliner_multi_pii-v1` | the base's six; the fine-tuning text is mostly English (95% of the rows whose language a stopword count can tell; half the rows are code, records or too short to tell) |

## Rules that keep the numbers honest

1. The report set never drives a decision. It is scored once, after every adapter and every candidate is frozen. A later re-measurement (for example after review fixes) is labelled as such.
2. No training on any benchmark row. Training data comes only from permissively licensed sources ([`docs/WEIGHTS_PROVENANCE.md`](https://github.com/lBroth/nullpii/blob/main/docs/WEIGHTS_PROVENANCE.md)).
3. A change to nullpii is kept only if, on the tuning set, it raises macro char-F2 with a CI above zero, lowers no label's recall by more than 0.005 or significantly, and keeps over-masking within a fixed cap. A correctness fix is kept when the property it targets holds and the output changes only where it was wrong.
4. Competitor settings change only symmetrically, and every change is disclosed.
5. Same inputs for every tool, and for latency the same machine; raw per-document outputs are kept.

## Results

nullpii 0.5 (the release build and the published weights, in fp32), in its core regime, measured on CUDA. Its CUDA and CPU outputs agree on all but a few documents in a thousand (37 of the 14,701 tuning-set documents differ; release build, fp32 on both). The fp16 model that nullpii loads on CUDA by default scores the same macro F2 on these sets (0.7576 against 0.7575 in fp32), with the same macro recall (0.9577). It takes 14–15% less time at 30k and 100k characters (463 ms against 537 ms, and 1,650 ms against 1,945 ms; median per call on the RTX 4070 Ti). Competitors run at their default and tuned operating points, and each row shows a tool's better one. The rows are from the release build, which includes the three rules from end-to-end testing described under AB-1; they changed only documents holding a UUID, an IPv4 address, a loopback host or the word "Claude". The CUDA and CPU agreement above was measured on the build before those rules, and the timings were checked on the release build, which takes the same time (fp16 459 ms and 1,640 ms, fp32 535 ms and 1,909 ms at 30k and 100k characters).

**Gated sets** (char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | REDACT | Tonic | PIILO | eu-clinical | traces-v3 | Macro | LODO |
|---|---:|---:|---:|---:|---:|---:|---:|
| rizzo-pii (default) | 0.818 | 0.849 | 0.623 | 0.840 | 0.718 | 0.770 | 0.750–0.806 |
| **nullpii** | 0.850 | 0.871 | 0.407 | 0.887 | 0.772 | 0.758 | 0.725–0.845 |
| nullpii, every category masked, core labels only | 0.830 | 0.872 | 0.402 | 0.880 | 0.756 | 0.748 | 0.715–0.834 |
| nvidia/gliner-PII (library) | 0.779 | 0.833 | 0.442 | 0.875 | 0.672 | 0.720 | 0.681–0.790 |
| OpenMed privacy-filter-multilingual-v2 | 0.784 | 0.874 | 0.480 | 0.725 | 0.725 | 0.717 | 0.678–0.777 |
| pii-identifier | 0.796 | 0.879 | 0.492 | 0.632 | 0.706 | 0.701 | 0.657–0.753 |
| ettin-68m | 0.805 | 0.844 | 0.483 | 0.647 | 0.713 | 0.699 | 0.662–0.752 |
| openai privacy-filter | 0.814 | 0.872 | 0.611 | 0.442 | 0.723 | 0.693 | 0.648–0.755 |
| OpenMed PII Large | 0.784 | 0.869 | 0.528 | 0.589 | 0.642 | 0.682 | 0.635–0.721 |
| OpenMed PII Small | 0.777 | 0.866 | 0.478 | 0.609 | 0.635 | 0.673 | 0.625–0.722 |
| gliner-pii-large | 0.844 | 0.801 | 0.191 | 0.863 | 0.582 | 0.656 | 0.604–0.772 |
| nullpii, every category masked, all its spans | 0.789 | 0.793 | 0.136 | 0.796 | 0.753 | 0.653 | 0.618–0.783 |
| piiranha | 0.784 | 0.760 | 0.239 | 0.857 | 0.617 | 0.651 | 0.600–0.755 |
| gliner_multi_pii (ONNX) | 0.817 | 0.795 | 0.163 | 0.913 | 0.551 | 0.648 | 0.581–0.769 |
| Presidio | 0.706 | 0.779 | 0.280 | 0.729 | 0.645 | 0.628 | 0.590–0.715 |
| nvidia/gliner-PII (NVIDIA server) | 0.651 | 0.755 | 0.252 | 0.801 | 0.498 | 0.591 | 0.539–0.676 |
| gliner-stream-pii | 0.732 | 0.769 | 0.141 | 0.559 | 0.640 | 0.568 | 0.518–0.675 |
| deberta PII (default) | 0.507 | 0.761 | 0.260 | 0.298 | 0.493 | 0.464 | 0.389–0.515 |
| mask everything | 0.370 | 0.278 | 0.004 | 0.272 | 0.374 | 0.260 | 0.231–0.324 |

**Reported sets** (char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | RedactionBench | mama-deid | traces-v3, distractors ignored | Macro | LODO |
|---|---:|---:|---:|---:|---:|
| **nullpii** | 0.723 | 0.715 | 0.875 | 0.771 | 0.719–0.799 |
| openai privacy-filter | 0.727 | 0.701 | 0.804 | 0.744 | 0.714–0.765 |
| nullpii, every category masked, core labels only | 0.703 | 0.666 | 0.860 | 0.743 | 0.685–0.782 |
| nullpii, every category masked, all its spans | 0.679 | 0.655 | 0.856 | 0.730 | 0.667–0.768 |
| ettin-68m | 0.738 | 0.591 | 0.818 | 0.716 | 0.665–0.778 |
| rizzo-pii | 0.632 | 0.648 | 0.824 | 0.701 | 0.640–0.736 |
| OpenMed privacy-filter-multilingual-v2 | 0.691 | 0.591 | 0.821 | 0.701 | 0.641–0.756 |
| pii-identifier | 0.753 | 0.541 | 0.808 | 0.700 | 0.647–0.780 |
| nvidia/gliner-PII (library) | 0.658 | 0.610 | 0.746 | 0.671 | 0.634–0.702 |
| gliner-stream-pii | 0.561 | 0.605 | 0.697 | 0.621 | 0.583–0.651 |
| gliner_multi_pii (ONNX) | 0.426 | 0.768 | 0.602 | 0.599 | 0.514–0.685 |
| gliner-pii-large | 0.419 | 0.729 | 0.604 | 0.584 | 0.512–0.667 |
| piiranha | 0.380 | 0.696 | 0.651 | 0.576 | 0.516–0.674 |
| OpenMed PII Small | 0.456 | 0.571 | 0.700 | 0.576 | 0.514–0.635 |
| OpenMed PII Large | 0.437 | 0.584 | 0.705 | 0.575 | 0.510–0.644 |
| nvidia/gliner-PII (NVIDIA server) | 0.490 | 0.645 | 0.562 | 0.565 | 0.526–0.603 |
| Presidio (default) | 0.353 | 0.414 | 0.682 | 0.483 | 0.384–0.548 |
| deberta PII (default) | 0.344 | 0.429 | 0.546 | 0.440 | 0.386–0.488 |
| mask everything | 0.266 | 0.364 | 0.407 | 0.346 | 0.315–0.386 |

**Gated sets, English documents only** (char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | REDACT | Tonic | PIILO | traces-v3 | Macro | LODO |
|---|---:|---:|---:|---:|---:|---:|
| openai privacy-filter | 0.783 | 0.872 | 0.611 | 0.717 | 0.746 | 0.704–0.791 |
| rizzo-pii (default) | 0.768 | 0.849 | 0.623 | 0.729 | 0.742 | 0.707–0.782 |
| OpenMed privacy-filter-multilingual-v2 (default) | 0.791 | 0.868 | 0.507 | 0.704 | 0.717 | 0.667–0.788 |
| pii-identifier (default) | 0.771 | 0.858 | 0.575 | 0.654 | 0.714 | 0.667–0.761 |
| **nullpii** | 0.791 | 0.871 | 0.407 | 0.786 | 0.714 | 0.661–0.816 |
| ettin-68m | 0.783 | 0.844 | 0.483 | 0.712 | 0.706 | 0.659–0.780 |
| nullpii, every category masked, core labels only | 0.768 | 0.872 | 0.402 | 0.770 | 0.703 | 0.647–0.803 |
| OpenMed PII Large | 0.772 | 0.869 | 0.528 | 0.630 | 0.700 | 0.643–0.757 |
| OpenMed PII Small | 0.766 | 0.866 | 0.478 | 0.623 | 0.683 | 0.622–0.751 |
| nvidia/gliner-PII (library) | 0.746 | 0.833 | 0.442 | 0.666 | 0.672 | 0.618–0.748 |
| nullpii, every category masked, all its spans | 0.717 | 0.793 | 0.136 | 0.766 | 0.603 | 0.540–0.759 |
| Presidio | 0.688 | 0.779 | 0.280 | 0.646 | 0.598 | 0.538–0.705 |
| piiranha | 0.770 | 0.760 | 0.239 | 0.605 | 0.593 | 0.534–0.711 |
| gliner-pii-large | 0.792 | 0.801 | 0.191 | 0.577 | 0.590 | 0.520–0.723 |
| gliner_multi_pii (ONNX) | 0.798 | 0.795 | 0.163 | 0.552 | 0.577 | 0.503–0.715 |
| gliner-stream-pii | 0.724 | 0.769 | 0.141 | 0.637 | 0.568 | 0.501–0.710 |
| deberta PII (default) | 0.646 | 0.761 | 0.260 | 0.505 | 0.543 | 0.470–0.638 |
| nvidia/gliner-PII (NVIDIA server) (default) | 0.619 | 0.751 | 0.291 | 0.501 | 0.540 | 0.470–0.624 |
| mask everything | 0.323 | 0.278 | 0.004 | 0.393 | 0.249 | 0.202–0.331 |

On English documents, openai's privacy-filter and rizzo-pii are significantly ahead of nullpii (nullpii minus the tool, 95%: [−0.052, −0.006] and [−0.041, −0.015]); OpenMed privacy-filter-multilingual-v2 [−0.025, +0.016], pii-identifier [−0.022, +0.021], ettin-68m [−0.006, +0.020] and OpenMed PII Large [−0.014, +0.040] are within the interval.

nullpii with every category masked (the default before 0.5) also masks five categories outside the core labels these datasets are scored on (organisations, occupations, demographic and sensitive attributes, titles). Counted on everything it masks, it scores lower here: 0.653 on the gated sets, 0.136 on PIILO. Turning those five off gives the core regime above. The default nullpii now ships for coding agents leaves those five categories and dates readable (`DEFAULT_DISABLED_CATEGORIES`). It is not measured on these sets, and it is not the core regime either, since the core labels count dates; the agent-traffic benchmark above measures it.

**Comparisons (gated sets, F2).** On the macro over the five sets, nullpii is significantly ahead of every tool but one, at that tool's better row (not on each set: on PIILO, eight tools are ahead). The narrowest margins are nvidia/gliner-PII [+0.025, +0.051] and OpenMed privacy-filter-multilingual-v2 [+0.031, +0.049]. rizzo-pii at its default is significantly ahead of nullpii, [−0.020, −0.003], all of it on PIILO; this is the test fixed before the run. With 99.67% intervals (a Bonferroni correction for 15 comparisons, added after the run), the 14 leads hold (13 tools and NVIDIA's server pipeline; the narrowest is nvidia/gliner-PII, [+0.019, +0.058]), and the gap to rizzo-pii, −0.012, is no longer significant, [−0.024, +0.002]. No dataset has a tool with significantly higher recall at matched or better precision. nullpii's macro recall (0.958) is the highest of any tool's better row; rizzo-pii at its tuned setting reaches 0.967, at a macro char-F2 of 0.583. At F0.5, nullpii falls to ninth on these rows (eight tools ahead), and to twelfth with each tool at its best F0.5 row.

**One dataset carries the margin.** Leaving each set out in turn (each tool at its better row; the tool's score minus nullpii's, with the paired 95% CI):

| Left out | nullpii | Tools ahead of nullpii | Closest behind |
|---|---:|---|---|
| REDACT | 0.734 | rizzo-pii (default) +0.023 [+0.012, +0.033] | nvidia/gliner-PII −0.029 [−0.045, −0.013] |
| Tonic | 0.729 | rizzo-pii (default) +0.020 [+0.010, +0.030] | nvidia/gliner-PII −0.037 [−0.055, −0.022] |
| PIILO | 0.845 | none | rizzo-pii (default) −0.039 [−0.050, −0.030] |
| eu-clinical | 0.725 | openai privacy-filter +0.030 [+0.013, +0.045], rizzo-pii (default) +0.027 [+0.016, +0.037] | pii-identifier −0.007 [−0.023, +0.008], privacy-filter-multilingual-v2 (default) −0.009 [−0.021, +0.002], ettin-68m −0.013 [−0.024, −0.003], OpenMed large −0.019 [−0.037, −0.001] |
| traces-v3 | 0.754 | rizzo-pii (default) +0.029 [+0.023, +0.034] | nvidia/gliner-PII −0.022 [−0.030, −0.014] |

Without the clinical notes, the lead over everyone but rizzo-pii is gone: two tools are significantly ahead, and pii-identifier and privacy-filter-multilingual-v2 are within the interval (OpenMed Large is just outside it). The clinical notes are the only medical text, and the only Greek, in the gated sets.

**Sensitivity checks.** They are reported, and none decides. All three include NVIDIA's server row:
- without the documents any OpenMed row returned no output for (77 gated documents, for every tool): conclusions unchanged;
- every set resampled by its recorded clusters: conclusions unchanged (rizzo-pii [−0.021, −0.003]);
- with nullpii with every category masked, on the core labels (0.748), as the baseline: it is ahead of the same 14 rows, also with the Bonferroni correction (the narrowest is nvidia/gliner-PII, [+0.009, +0.049]), and behind rizzo-pii by 0.022, significantly in both tests ([−0.030, −0.012] at 95%, [−0.034, −0.007] corrected).

**OpenMed's texts with no output.** `deidentify` refuses some texts as suspicious content: 7 traces-v3 transcripts, 2 PIILO essays, 2 RedactionBench documents and 1 mama-deid text, for both models at both points. It also fails its own safety-sweep check on others, more often at the tuned points' lower thresholds (Small tuned: 7 REDACT, 41 Tonic, 11 PIILO, 1 eu-clinical, 83 mama-deid; Large tuned: 9 REDACT, 3 Tonic, 1 PIILO, 59 mama-deid). These texts score as no spans. The package logs no text, so each failure is matched to its document by length and empty output (`scripts/ab/openmed_no_output.py`).

**PIIMB** (`sentences` subset, 150,022 texts; nullpii with every category masked, the default before 0.5), scored by us with the leaderboard's method (`scripts/ab/piimb_score.py`), not a submitted entry: average F2 0.851, above all 35 listed tools. Next are OpenMed privacy-filter-multilingual-v2 (0.836) and OpenMed PII SuperClinical Large (0.835). nullpii's F2 per task: ai4privacy-en 0.960, ai4privacy-multilingual 0.939, nemotron-pii 0.950, Gretel 0.962, privy 0.713, mapa-eur-lex 0.580. These are the release build's. Caveats:
- the nemotron-pii task is in nullpii's training family (2.5% of its sampled text overlaps nullpii's training corpus, 5.2% overlaps Nemotron-PII's); without it nullpii averages 0.831, against gliner-stream-pii's 0.827 and privacy-filter-multilingual-v2's 0.822, and the leaderboard gives no intervals;
- the ai4privacy tasks come from the same family as part of the tuning set;
- PIIMB shaped one design decision. An earlier result, on which nullpii missed every category it did not mask then, is why the five extended categories exist. They were masked by default until 0.5; the 0.5 default for coding agents leaves them readable. PIIMB has not been used to tune anything.

**Latency** is in the README. It is measured on idle machines, every tool on the same texts of coding-agent material (code, logs, prose and tool output) at 2,000, 30,000 and 100,000 characters, after a warm-up. On GPU every tool runs the full plan: 60, 12 and 5 texts per size, in three rounds; the table shows the median of the rounds' medians. On CPU the full plan takes hours for a single tool, so every tool runs the short plan: one text of each kind at 2,000 and 30,000 characters (6 each) and three at 100,000, timed once; the table shows their median. The short plan's texts are a subset of the full plan's.

Every tool was timed on the same idle machine; nullpii's rows were repeated with the release build and moved by less than 2%. The 0.5 default (dates readable, so fewer labels asked of the model) takes 32, 458 and 1,642 ms on GPU and 384, 6,104 and 23,075 ms on CPU, at 2,000, 30,000 and 100,000 characters.

## Limits

- F2 rewards over-masking. nullpii ranks on recall: at F0.5 most compared tools rank above it.
- Five gated datasets is a small sample of the world, and only English, the main EU languages and Greek are covered.
- Gold labels differ in scope between datasets. PIILO labels only students' names, contact details, addresses, URLs and ids, so another person's name, a date or a place that a tool masks counts against it. Tonic's gold does not include city, state or postcode, which affects every precision figure on it.
- The tuning set is close to nullpii's training distribution and partly to some competitors' (it is used to choose, never to claim).
- Latency depends on hardware and load; it is measured on idle machines, every tool on the same corpus.

## Reproduce

`scripts/bench_full.py` runs any tool on any dataset and writes per-document predictions; `scripts/ab/char_metrics.py` scores them (`--cluster-rows` and `--exclude` for the sensitivity checks); `scripts/ab/r2_verdict.py` applies the comparison rules; `scripts/ab/tune_operating_point.py` tunes a competitor; `scripts/ab/score_capture.mjs` captures nullpii's spans; `scripts/ab/piimb_score.py` scores PIIMB; `scripts/ab/competitor_latency.py` and `scripts/ab/harness.mjs` time the tools.
