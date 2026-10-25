# How nullpii is measured

This page says how the numbers in the README are produced and what they do and do not show. The scripts are in `scripts/`; the dataset selection rules for the report set are in [`scripts/r3/CRITERIA.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/scripts/r3/CRITERIA.md), committed before any of its texts was opened (it cites the maintainers' working protocol and log, which are not published; this page is their public summary).

## What is tested

nullpii masks personal data and secrets before text reaches an LLM, so the main question is how much personal data it lets through, and at what cost in over-masking. It is compared with every machine-learning PII detector we could run locally, each the way its authors ship it. The job nullpii's default is built for — a coding agent's traffic, where some values must be hidden and others must stay readable — is measured separately by AB-1 ([Agent-traffic benchmark (AB-1)](#agent-traffic-benchmark-ab-1)).

## Agent-traffic benchmark (AB-1)

AB-1 is pre-registered: its specification was written on 2026-10-23, after the 0.5 model was chosen and before any set was built or any tool ran on it, so it cannot steer a training or selection decision; it is reported, never used to choose. Where the implementation departs from the specification, the change was logged before any tool ran; each one is listed under [Departures from the specification](#departures-from-the-specification).

### What it measures, and why

nullpii's default is built for a coding agent's traffic (Claude Code): prompts, file reads, shell output, logs, tool-call arguments, tickets. A masker in front of that traffic has to hide what is dangerous to hand over — secrets and credentials, contact details and addresses, identifiers and account numbers, person names — and leave readable what the agent needs to work: dates, versions, paths, hostnames of public services, placeholders, code identifiers. The R3 report set measures document anonymisation (PIILO is student essays, rizzo-pii is a document anonymiser), which is a different job. AB-1 measures the agent job, per category and with no single combined score: **leak rate** on the items that must be masked, **keep rate** on the items that must stay readable. Scoring is label-agnostic: an item counts as masked when a tool masks its characters, whatever label the tool gave them, so a key masked as `PASSWORD` or as `ID` has still been protected. Latency is not measured on AB-1.

### Data

- **A. Agent traffic.** 1,200 documents an agent sees (dev 200, test 1,000), with injected fictional values and annotated keep items, built from the AB-1 specification alone by an agent working outside every nullpii repository; the generator, the value lists and the gold are Apache-2.0. Kinds, each split 1/6 dev and 5/6 test: user prompts to a coding agent (20%, en/it/de/fr/es in equal shares), file reads of source, `.env`, YAML/JSON/TOML config, Dockerfile and CI files (20%, en), shell output — `git log`, `git diff`, `curl -v`, `env`, `docker`/`kubectl` output, test runs (20%, en), logs and stack traces with home paths (15%, en), tool-call arguments as JSON (10%, en), and issue or ticket text pasted into the agent (15%, en/it/de/fr/es). Half of every kind, and of every language of prompts and tickets, starts from real material (a carrier) and half from templates the builder wrote.
- **A, carriers.** [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) (CC BY 4.0, revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`): tool calls, bash output and diffs from OpenHands runs on public repositories; [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) (MIT, revision `facf45600d625510b98222ec584a8c9ac59272a2`): real user sessions; [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) (ODC-BY 1.0, revision `7d6490e462285cf85d91eabea0f9a954fbddcd1f`): the first user turn of it/de/fr/es conversations; and GitHub issues fetched on 2026-10-24, each keeping the SPDX licence its repository had at that moment. Excerpts are cut at line boundaries, 300–6,000 characters, and the carrier id and offsets are recorded; the GitHub carriers also record the issue URL and the licence, so the text can be re-fetched and the document rebuilt. 600 of the 1,200 documents are carrier documents (SWE-rebench 343, openhands-feedback 89, WildChat-1M 96, GitHub issues 72).
- **A, values and items.** Values go where they really occur: `.env` lines, `Authorization: Bearer` headers, DB connection strings, `git log` author lines, `/Users/<name>/` and `/home/<name>/` paths in tracebacks, `From:`/`To:` lines, log fields (`user=`, `email=`, `customer_id=`), config blocks. 20% of documents get no injected value (clean documents); 5% of injected values appear a second time base64- or URL-encoded (a `kubectl get secret -o yaml` payload, a query string), as its own item linked to the original. Every value is fictional, generated by the builder's code with recorded seeds, and format-valid: Luhn-valid card numbers, mod-97 IBANs, national ids with valid check characters, provider keys with the provider's published prefix, length and charset. Key formats are drawn uniformly from the 221 usable rules of [gitleaks](https://github.com/gitleaks/gitleaks) v8.30.1 (MIT), so the formats are not chosen by anyone who knows nullpii. Names and addresses come from public-domain or permissively licensed lists (Wikidata, GeoNames), not from Faker. Items are annotated in two passes — a carrier pass before injection and a keep pass after it — and never overlap. Classes are MUST_MASK, MUST_KEEP and AMBIGUOUS (real PII-like strings already in the carriers, names in licence headers, public figures, maintainers' handles, role addresses, internal hosts and RFC 1918 addresses, order numbers, birth dates, dummy credentials); AMBIGUOUS is annotated but never scored either way. A generated value found in the carrier material is blocklisted and re-drawn (three, all usernames).
- **A, counts `(pre-freeze)`.** Test split: 3,482 MUST_MASK, 6,002 MUST_KEEP and 423 AMBIGUOUS items, 200 clean documents. Both splits: 4,002 injected values and 200 encoded copies. These are the built counts, before the audit; the audit can change them.
- **B1. CredData** ([Samsung/CredData](https://github.com/Samsung/CredData), Apache-2.0, commit `c49ed106…`, values obfuscated upstream). Seed 0: 2,000 true secrets (102 categories) and 2,000 labelled non-secrets (49 categories), stratified by CredData's `Category` (largest remainder). One document is the line(s) of the candidate with 5 lines of context each side; one item per document — a true secret is MUST_MASK `secret`, a labelled non-secret is MUST_KEEP with its CredData category as its kind. The span convention is CredData's own, taken from its scripts. Rows with label `X` (4,082), offsets outside the line (1) or an empty value (4) are dropped and counted. An independent script re-derived all 4,000 documents and found them identical.
- **B2. Issue secrets** ([Zenodo record 17430335](https://zenodo.org/records/17430335), CC BY 4.0; paper [arXiv 2410.23657](https://arxiv.org/abs/2410.23657)). Every true secret plus an equal seeded sample of labelled non-secrets: 5,803 + 5,803 = 11,606 documents (the record's `main_data.csv` holds 5,873 true secrets, not the 5,881 the specification quoted; 70 are dropped by the rules below). A document is the issue body around the candidate, 1,000 characters each side, cut at whitespace. The scored item is the candidate's core value — its longest run of `[A-Za-z0-9+/_\-.~%=]`, at least 8 characters, without a leading `name=` — because the labelled candidate sometimes carries the key name, quotes or the next line, which no masker is expected to hide. Candidates not found in the body, shorter runs and exact duplicate documents are dropped and counted. Where the value after `name=` is shorter than 8 characters the item is AMBIGUOUS, scored neither way (27 secrets, 152 non-secrets), so 5,776 secrets and 5,651 non-secrets are scored. These secrets are real: only aggregates are published, never a document or a value.
- **B3, not run.** A third slice, bigcode/bigcode-pii-dataset (real code with crowd-annotated personal data), was planned before any run; its access request was not granted, so AB-1 has no B3.

### How it was built and frozen

- **Order of work.** Built by an agent from the specification alone, outside every nullpii repository → 10% audit by a second fresh agent without the gold (Cohen's kappa per class; more than 5% of items wrong → fix the cause and re-audit) → freeze by SHA-256 (the files of A, the B1/B2 id lists, the scorer) → leak check → tools run once → scored once.
- **Freeze.** The SHA-256 of every file of A (code, lists, gold, README), of B1/B2's sampled id lists and of the scorer go to the log before any tool runs, together with the canary string `AB1-CANARY-6f3a1c9e-nullpii-agentbench-2026-10-23`, which is placed in A's README and gold.
- **Audit.** TBD (Cohen's kappa per class, share of gold items found wrong or missing).
- **Leak check** (after the freeze, before any tool runs). Every document of A, both splits, carrier and template, is compared with the shipped model's training corpus (100,982 rows) by 13-token shingles as exact sets: a document is flagged when Jaccard ≥ 0.8, or ≥ 80% of a training row's shingles occur in it, or ≥ 80% of its own occur in one training row. Every injected MUST_MASK value is a hit when its token sequence occurs in any training row; single-token values that are bare given names or surnames from the generator's name lists are exempt and counted. This is stricter than the pre-registered test (MinHash Jaccard on carrier excerpts), which would miss a training row contained in a longer document, with one exception: a bare given name or surname from the generator's lists is not a hit, since common names occur in any large corpus; the exempted values are counted and published. Flagged test documents are dropped and counted, and nothing is added back. TBD (number of documents compared, flagged and dropped; number of value hits).
- **Runs.** The test split is run once for this release, for every tool, and every number is published, including the ones nullpii loses. TBD (date and hashes of the frozen sets).

### Metrics

- A MUST_MASK item is masked when every character carrying its value is masked, whatever the label; whitespace and `\n`/`\r`/`\t` layout escapes inside the item do not count, so a tool that masks a private key line by line has masked it. Partial masking is a leak. The same rule applies to every tool.
- A MUST_KEEP item is kept when no character of it is masked. AMBIGUOUS items are scored neither way.
- These rates are over items, not over characters, which is the difference from the R3 metric above. A tool's leak rate and keep rate are reported per category and overall, with no combined score.
- Also reported: documents with at least one leak; the share of clean documents (no MUST_MASK item) with anything masked; characters masked outside every item, per 1,000 characters; the encoded leak rate, on the base64/URL-encoded copies alone; whether JSON documents still parse after masking; whether diff hunks still have a consistent line count after masking (carrier pre-images are not shipped, so `git apply --check` is not possible); and the secrets' leak rate split by whether nullpii's recognizer pack covers their key format, a split computed after the freeze from the pack itself (`recognizer_spans.mjs`, `secret_coverage.py`) and only reported.
- Uncertainty: paired bootstrap over documents, 1,000 resamples, seed 0, 95% intervals of each tool's overall leak and keep rates and of nullpii minus each tool (not per category). A difference is called a win or a loss only when its interval excludes 0.
- Baseline: nullpii 0.5 in its agent default, the categories the agent policy leaves readable turned off (dates, organisations, occupations, titles, demographic and sensitive attributes).

### Competitors

- The tools of the README's document table, through the same adapters and full upstream pipelines, each at its default operating point and at the one tuned on the tuning set, never on AB-1.
- Each row also has a `+agent` variant: the tool's spans minus those whose mapped label is in the readable set above. For a tool whose categories map onto nullpii's this is the same as turning those categories off, which is why it is the agent-policy row.
- Labels a tool emits that have no nullpii mapping are kept (`--keep-unmapped-labels`), because scoring is label-agnostic: a tool that masks a secret under a label outside nullpii's schema has masked it. Such spans stay in the `+agent` row. The document benchmark's numbers were produced without this option and are unchanged by it.
- Thresholds are not tuned on AB-1, and adapters are not changed after the first run: a needed fix applies to every tool, is logged, and the whole run is redone.
- If CredSweeper is run on B1, its row is marked in-distribution, because its model is trained on CredData.

### Departures from the specification

Each was decided and logged before any tool ran on any AB-1 set.

- **Carriers.** The specification names two carrier datasets, both English. So that prompts and tickets in it/de/fr/es also start from real material half the time, WildChat-1M prompts and GitHub issues were added; a first build without them had 20% carriers for those two kinds and was rebuilt. The added material was selected and the generator extended by a second agent (DeepSeek V4.1 Flash) under the maintainers' written instructions, also without access to any nullpii repository.
- **Masked item.** The specification counts any unmasked character as a leak; whitespace and `\n`/`\r`/`\t` layout escapes inside an item are not counted, so masking a key line by line is not a leak.
- **Diff structure.** Hunk line counts are checked after masking instead of `git apply --check`, because the carriers' pre-images are not shipped.
- **Rows.** The specification has two rows per tool: default, and the agent policy where the tool can turn categories off. Each tool is instead shown at its default and at its tuned operating point (tuned on the tuning set, as in the document benchmark), each raw and with the agent-policy post-filter, which applies to every tool.
- **Unmapped labels** are kept, as label-agnostic scoring requires (see Competitors).
- **B2 item.** The scored item is the candidate's core value, not the labelled candidate string; 70 true secrets are dropped (see Data). The first build kept a leading `name=` inside the value (347 secrets, 416 non-secrets in the set, mostly the record's generic `key=value` pattern), so a tool that masked only the value was counted as leaking it. The final review found this after the tools had run and before any score was read; the gold was rebuilt with the name cut off, the documents and their order unchanged, so no tool was rerun, only scored again.
- **Leak check.** Stricter than specified, with the name exemption described above.
- **Canary.** The canary string is in A's README and in `data/CANARY` next to the gold, not inside the gold's rows.
- **Audit corrections.** The audit's wrong-or-missing share was below the 5% threshold, so no re-audit was required; two annotation rules it exposed were corrected in the generator before the freeze (a UUID right after a session-like key and an encoded dummy credential are AMBIGUOUS, 24 items in all), and nothing else changed.

### Results

No tool has run on any AB-1 set yet, so the tables below hold placeholders only; they are filled once, from the single run, and every figure is published.

**A. Agent traffic** — one row per tool per operating point, plus its `+agent` variant.

<!-- ab1-a:begin -->
| Tool | Leak rate | Keep rate | Docs with a leak | CI of nullpii − tool (leak) |
|---|---:|---:|---:|---|
| nullpii (agent default) | TBD | TBD | TBD | TBD |
| … | TBD | TBD | TBD | TBD |
<!-- ab1-a:end -->

**B1. CredData** — aggregates only. **B2. Issue secrets** — aggregates only, and no document or value is ever printed.

<!-- ab1-b1:begin -->
| Tool | Leak rate | Keep rate | Docs with a leak | CI of nullpii − tool (leak) |
|---|---:|---:|---:|---|
| nullpii (agent default) | TBD | TBD | TBD | TBD |
| … | TBD | TBD | TBD | TBD |
<!-- ab1-b1:end -->

<!-- ab1-b2:begin -->
| Tool | Leak rate | Keep rate | Docs with a leak | CI of nullpii − tool (leak) |
|---|---:|---:|---:|---|
| nullpii (agent default) | TBD | TBD | TBD | TBD |
| … | TBD | TBD | TBD | TBD |
<!-- ab1-b2:end -->

**Secrets by recognizer coverage.** The secrets' leak rate on the items nullpii's recognizer pack covers (run alone on the raw text, without the model or the base64 pass, it masks every character of the value) and on the rest, in each set; computed after the freeze from the pack itself and only reported. Items: A 87 covered of 585, B1 120 of 2,000, B2 2,093 of 5,776.

<!-- ab1-coverage:begin -->
<!-- ab1-coverage:end -->

### Limits

- The injected values of A are fictional and generated. They are format-valid and drawn from real providers' layouts, but a generated key is not a leaked key: AB-1 measures whether a masker finds the shapes, not whether a real credential of that shape is still usable.
- A's file, shell and log carriers are English; only the prompt and ticket kinds cover it/de/fr/es, and their non-English material comes from chat-assistant prompts (WildChat-1M) and GitHub issues.
- The WildChat-1M prompts are written to a chat assistant, not to a coding agent: they are real non-English programming questions, one model of what a user types, not agent traffic.
- A is one specification's view of agent traffic, built by one agent and audited on 10% of its documents. Claude Code-style tools are the model: another agent's traffic (different tool schemas, different file kinds) is not represented.
- B1 and B2 hold secrets and secret-looking non-secrets only: they say nothing about names, contact details or the other categories.
- Real names already in carrier text (for example a signature at the end of a GitHub issue) are not annotated: the builder's carrier pass finds emails, phones, IPs and key-like strings, not names. Masking one counts only in the masked-outside-items figure, never in leak or keep rate. The audit found one in its 120 documents.
- The components are scored separately and are not averaged into one AB-1 score; a tool can lead on one and trail on another.

### Licences and attribution

- Component A's carriers: [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) CC BY 4.0; [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) MIT; [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) ODC-BY 1.0, cited as Zhao, Ren, Hessel, Cardie, Choi, Deng, "WildChat: 1M ChatGPT Interaction Logs in the Wild", ICLR 2024; each GitHub issue keeps the SPDX licence of its repository, recorded per document. Repositories were found through GitHub's Multilingual Repositories Dataset (CC0-1.0, commit `3d63dbdb61f69663486309a1f8805a1c8eb4a353`), which was used only to find repositories.
- The published gold of A does not redistribute GitHub issue text: it holds the issue URL and the offsets, with a script to rebuild the text.
- Value lists: Wikidata (CC0) and GeoNames (CC BY 4.0); key formats: gitleaks v8.30.1, commit `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` (MIT).
- B1: Samsung/CredData (Apache-2.0), source files under their repositories' own licences, published as aggregates only. B2: Zenodo record 17430335 (CC BY 4.0), aggregates only.
- Component A's generator, its handmade lists and its gold are Apache-2.0; carrier excerpts keep their dataset's or repository's licence.

### Reproduce

The AB-1 scripts are published under `packages/eval/scripts/ab1/`: `agent_metrics.py` (the scorer), `b1_build.py`, `b2_build.py` and `leak_check.py`. Component A's generator and gold go to TBD (location), with the builder's README. The scorer is written and hashed before the first run.

## Data

- **Tuning set.** Held-out slices of Isotonic (en, de, fr, it), ai4privacy-300k, and a set of synthetic coding-agent traces. Every choice is made on this set: nullpii's changes and thresholds, and every competitor's operating point. It is close to nullpii's home distribution, which is why nothing is claimed from it.
- **Report set (R3), gated.** Five datasets (four public sets and a synthetic coding-agent trace set) chosen by written criteria (licence, independence from every compared tool's declared training data, domain and language coverage) and frozen by SHA-256 before any tool ran on them:
  - REDACT (EU-language and English records of its locked test split);
  - TonicAI's human-annotated Privacy-Bench;
  - PIILO (student essays);
  - eu-clinical (Greek clinical notes and German letters);
  - traces-v3: coding-agent transcripts from a generator written by an agent that saw only a written spec, never this project's generators, corpora or tuning sets. The spec itself was written by the maintainers: it uses nullpii's label names and treats public URLs, placeholders and similar text as distractors, as nullpii's product scope does.
- **Reported, not gated:** RedactionBench (untyped gold), mama-deid's validation split (gold checked only by models), and traces-v3 with its distractor regions ignored.
- **Overlap check.** Before any tool was scored, each set was compared with nullpii's training corpus and tuning texts, the earlier trace sets, Nemotron-PII, the ai4privacy 200k, 400k and open-500k sets, Isotonic, urchade's synthetic PII set and both Gretel PII sets, using one in eight 10-word shingles. The criteria written before the sets were built named 64-character windows; 10-word shingles of lowercased words (about 60 characters) were used instead, decided before any tool was scored, because nullpii's training corpus is stored tokenized and character windows would never align with it. The 1% threshold is unchanged. No set reaches 1% overlap with any of them. The check covers declared, public training data only: some tools declare none or not all (openai's privacy-filter; rizzo-pii names two of its four sources), and openpii-1m, the Privy-style data on OpenMed privacy-filter-multilingual-v2's card and the Italian sets behind rizzo-pii were not compared.
- **PIIMB.** The public PIIMB leaderboard's `sentences` subset, scored with the leaderboard's own protocol, is reported separately.

Two of the things compared here are built for documents. PIILO is a set of student essays, human-annotated for a Kaggle competition, where among names only the students' own are gold (`scripts/r3/CRITERIA.md`). rizzo-pii is a document anonymiser: the pipeline run here is the one its desktop app serves (`analyze()`, with PDF text extraction in the app), and its model and training corpus are Italian-first. Both measure document anonymisation, which is a different job from masking a coding agent's traffic — prompts, file reads, shell output, logs, tool-call arguments — the job nullpii's default is built for.

## Metric

- **Character level, label-agnostic.** A personal-data character counts as protected if any predicted span covers it, whatever label the tool gave. This is what a user cares about (what reaches the model unmasked), and it removes label-mapping differences between tools.
  - recall = covered gold characters / gold characters (1 − leak rate);
  - precision = covered gold characters / masked characters (1 − over-masking).
- **F2 decides; F1 and F0.5 are reported next to it.** F2 counts recall as twice as important as precision (β = 2), the product's priority, and it rewards over-masking. A mask-everything row shows the floor.
- **Core label space.** Scores use the categories every dataset labels (persons, contact details, addresses, dates, identifiers, URLs, IPs, secrets). nullpii's extended categories (organisations, occupations, demographic and sensitive attributes, titles) are on by default; its default configuration is reported both raw and filtered to the core labels.
- **Macro over datasets**, with a leave-one-dataset-out range so one dataset cannot carry the result.
- **Paired bootstrap, 95% CIs** of nullpii minus each tool, 1,000 resamples: by document, except traces-v3, resampled by generator template. As a sensitivity check every set is also resampled by its recorded source document or conversation. The test fixed before the run is this uncorrected 95% interval over the 14 tools; NVIDIA's reference server, added after the first look, is reported as a 15th comparison under the same test. Intervals corrected for those 15 comparisons (Bonferroni, 99.67%) were added after the run, as a check, and are reported next to them.

## Competitors, run as shipped

- Each tool runs through its authors' inference path: their library or app pipeline, chunker, decoder and rule layers, the label strings of their card, and their recommended device and precision. Where the authors ship a product-level call it is used (rizzo-pii's app `analyze()`, OpenMed's `deidentify`, Presidio's multilingual engine with each text's language). Third-party code is vendored verbatim where needed, with its licence.
- Departures from that path, each so that every tool reads the whole text:
  - the token classifiers (piiranha, deberta, ettin, pii-identifier, and rizzo-pii's model inside its app) run over token windows of their trained length, stitched by overlap, where their pipelines would truncate;
  - the GLiNER tools run over word windows of the model's `max_len`, where the library drops the words past it; on dense code a window can reach several thousand subword tokens, beyond the trained length (in AB-1 a window also holds at most 4,096 tokens, see its departures);
  - gliner_multi_pii runs as onnx-community's ONNX export of `urchade/gliner_multi_pii-v1`, on the CPU as the library does for ONNX; on 300 AB-1 documents its entities are identical to the original PyTorch weights' (1,777 of 1,777, largest score difference 0.0014);
  - gliner-stream-pii runs in 2,048-word windows, one at a time, because its card's whole-text mode ran out of GPU memory;
  - OpenMed runs with `lang='en'` on every text, because another language silently swaps its Small model;
  - `nvidia/gliner-PII` is shown as run through the GLiNER library with its card's labels and threshold. NVIDIA's reference server (the one NeMo Guardrails calls: 384-character chunks, one entity kept per value) was added after the first R3 look and scores lower (0.591).
- Model revisions are pinned. The pins were set after the runs; a rerun of 20 documents reproduced the spans of every tool but NVIDIA's server pipeline (added later), except two tools whose spans differ only through how texts are batched.
- Every tool is run at its default operating point and at one tuned on the tuning set for macro char-F2: the threshold, a bias against the model's "no entity" class for token classifiers, and per-label score cuts, applied by the kit where the tool has no option for it, and through the pipeline's own setting where it has one (OpenMed's `confidence_threshold`, the Viterbi background bias of openai's privacy-filter, the threshold of NVIDIA's server). nullpii's changes were also held to a per-label recall guard and an over-masking cap, which the competitors' tuning was not. The tuned values are in `published-bench/r3/operating-points.json`.
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
2. No training on any benchmark row; training data comes only from permissively licensed sources ([`docs/WEIGHTS_PROVENANCE.md`](https://github.com/lBroth/nullpii/blob/main/docs/WEIGHTS_PROVENANCE.md)).
3. A change to nullpii is kept only if, on the tuning set, it raises macro char-F2 with a CI above zero, lowers no label's recall by more than 0.005 or significantly, and keeps over-masking within a fixed cap; a correctness fix is kept when the property it targets holds and the output changes only where it was wrong.
4. Competitor settings change only symmetrically, and every change is disclosed.
5. Same inputs for every tool, and for latency the same machine; raw per-document outputs are kept.

## Results

nullpii 0.5 (the release build and the published weights, in fp32) in its core regime, measured on CUDA; its CUDA and CPU outputs agree on all but a few documents in a thousand (37 of the 14,701 tuning-set documents differ, release build, fp32 on both). The fp16 model nullpii loads on CUDA by default scores the same macro F2 on these sets, with macro recall 0.9595 against 0.9596 in fp32, and takes 14–15% less time at 30k and 100k characters (463 ms against 537 ms, 1,650 ms against 1,945 ms, median per call on the RTX 4070 Ti). Competitors at their default and tuned operating points; each row shows a tool's better one. The R3 sets were first scored on 20 October with the candidate build; these numbers are the re-measurement after the pre-release fixes, which moved nullpii's macro by −0.001.

**Gated sets** (char-F2; each tool at its better row, `(default)` where that is its default)

| Tool | REDACT | Tonic | PIILO | eu-clinical | traces-v3 | Macro | LODO |
|---|---:|---:|---:|---:|---:|---:|---:|
| rizzo-pii (default) | 0.818 | 0.849 | 0.623 | 0.840 | 0.718 | 0.770 | 0.750–0.806 |
| **nullpii** | 0.847 | 0.871 | 0.407 | 0.887 | 0.769 | 0.756 | 0.723–0.844 |
| nullpii, every category masked, core labels only | 0.827 | 0.872 | 0.402 | 0.880 | 0.757 | 0.747 | 0.714–0.834 |
| nvidia/gliner-PII (library) | 0.779 | 0.833 | 0.442 | 0.875 | 0.672 | 0.720 | 0.681–0.790 |
| OpenMed privacy-filter-multilingual-v2 | 0.784 | 0.874 | 0.480 | 0.725 | 0.725 | 0.717 | 0.678–0.777 |
| pii-identifier | 0.796 | 0.879 | 0.492 | 0.632 | 0.706 | 0.701 | 0.657–0.753 |
| ettin-68m | 0.805 | 0.844 | 0.483 | 0.647 | 0.713 | 0.699 | 0.662–0.752 |
| openai privacy-filter | 0.814 | 0.872 | 0.611 | 0.442 | 0.723 | 0.693 | 0.648–0.755 |
| OpenMed PII Large | 0.784 | 0.869 | 0.528 | 0.589 | 0.642 | 0.682 | 0.635–0.721 |
| OpenMed PII Small | 0.777 | 0.866 | 0.478 | 0.609 | 0.635 | 0.673 | 0.625–0.722 |
| gliner-pii-large | 0.844 | 0.801 | 0.191 | 0.863 | 0.582 | 0.656 | 0.604–0.772 |
| nullpii, every category masked, all its spans | 0.786 | 0.793 | 0.136 | 0.796 | 0.753 | 0.653 | 0.617–0.782 |
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
| **nullpii** | 0.735 | 0.715 | 0.880 | 0.777 | 0.725–0.807 |
| nullpii, every category masked, core labels only | 0.717 | 0.666 | 0.870 | 0.751 | 0.692–0.793 |
| openai privacy-filter | 0.727 | 0.701 | 0.804 | 0.744 | 0.714–0.765 |
| nullpii, every category masked, all its spans | 0.693 | 0.655 | 0.865 | 0.738 | 0.674–0.779 |
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
| **nullpii** | 0.790 | 0.871 | 0.407 | 0.784 | 0.713 | 0.661–0.815 |
| ettin-68m | 0.783 | 0.844 | 0.483 | 0.712 | 0.706 | 0.659–0.780 |
| nullpii, every category masked, core labels only | 0.768 | 0.872 | 0.402 | 0.773 | 0.704 | 0.648–0.804 |
| OpenMed PII Large | 0.772 | 0.869 | 0.528 | 0.630 | 0.700 | 0.643–0.757 |
| OpenMed PII Small | 0.766 | 0.866 | 0.478 | 0.623 | 0.683 | 0.622–0.751 |
| nvidia/gliner-PII (library) | 0.746 | 0.833 | 0.442 | 0.666 | 0.672 | 0.618–0.748 |
| nullpii, every category masked, all its spans | 0.717 | 0.793 | 0.136 | 0.769 | 0.604 | 0.541–0.760 |
| Presidio | 0.688 | 0.779 | 0.280 | 0.646 | 0.598 | 0.538–0.705 |
| piiranha | 0.770 | 0.760 | 0.239 | 0.605 | 0.593 | 0.534–0.711 |
| gliner-pii-large | 0.792 | 0.801 | 0.191 | 0.577 | 0.590 | 0.520–0.723 |
| gliner_multi_pii (ONNX) | 0.798 | 0.795 | 0.163 | 0.552 | 0.577 | 0.503–0.715 |
| gliner-stream-pii | 0.724 | 0.769 | 0.141 | 0.637 | 0.568 | 0.501–0.710 |
| deberta PII (default) | 0.646 | 0.761 | 0.260 | 0.505 | 0.543 | 0.470–0.638 |
| nvidia/gliner-PII (NVIDIA server) (default) | 0.619 | 0.751 | 0.291 | 0.501 | 0.540 | 0.470–0.624 |
| mask everything | 0.323 | 0.278 | 0.004 | 0.393 | 0.249 | 0.202–0.331 |

nullpii with every category masked (the default before 0.5) also masks five categories outside the core labels these datasets are scored on (organisations, occupations, demographic and sensitive attributes, titles), so counted on everything it masks it scores lower here: 0.653 on the gated sets, 0.136 on PIILO. Turning those five off gives the core regime above. The default nullpii now ships for coding agents leaves those five categories and dates readable (`DEFAULT_DISABLED_CATEGORIES`); it is not measured here yet, and it is not the core regime either, since the core labels count dates.

**Comparisons (gated sets, F2).** On the macro over the five sets (not on each set: on PIILO, eight tools are ahead), nullpii is significantly ahead of every tool but one, at that tool's better row: the narrowest margins are nvidia/gliner-PII [+0.024, +0.050] and OpenMed privacy-filter-multilingual-v2 [+0.030, +0.048]. rizzo-pii at its default is significantly ahead of nullpii, [−0.021, −0.005], all of it on PIILO; this is the test fixed before the run. With 99.67% intervals (a Bonferroni correction for 15 comparisons, added after the run), the 14 leads hold (13 tools and NVIDIA's server pipeline; narrowest nvidia/gliner-PII [+0.018, +0.056]) and the gap to rizzo-pii, −0.013, is no longer significant, [−0.025, +0.001]. No dataset has a tool with significantly higher recall at matched or better precision. At F0.5 nullpii falls to ninth on these rows (eight tools ahead), and to twelfth with each tool at its best F0.5 row.

**One dataset carries the margin.** Leaving each set out in turn (each tool at its better row; the tool's score minus nullpii's, with the paired 95% CI):

| Left out | nullpii | Tools ahead of nullpii | Closest behind |
|---|---:|---|---|
| REDACT | 0.734 | rizzo-pii (default) +0.024 [+0.014, +0.033] | nvidia/gliner-PII −0.028 [−0.044, −0.012] |
| Tonic | 0.728 | rizzo-pii (default) +0.022 [+0.012, +0.031] | nvidia/gliner-PII −0.036 [−0.053, −0.020] |
| PIILO | 0.844 | none | rizzo-pii (default) −0.037 [−0.048, −0.029] |
| eu-clinical | 0.723 | openai privacy-filter +0.032 [+0.015, +0.047], rizzo-pii (default) +0.028 [+0.018, +0.038] | pii-identifier −0.005 [−0.021, +0.010], privacy-filter-multilingual-v2 (default) −0.008 [−0.020, +0.004], ettin-68m −0.012 [−0.022, −0.002], OpenMed large −0.018 [−0.035, +0.001] |
| traces-v3 | 0.753 | rizzo-pii (default) +0.029 [+0.024, +0.035] | nvidia/gliner-PII −0.021 [−0.029, −0.013] |

Without the clinical notes, the lead over everyone but rizzo-pii is gone: two tools are significantly ahead, and pii-identifier, privacy-filter-multilingual-v2 and OpenMed large are within the interval. They are the only medical text, and the only Greek, in the gated sets.

**Sensitivity checks** (reported, none decides; the first two were run before NVIDIA's server row was added; the third, at 95% and corrected, includes it):
- without the documents any OpenMed row returned no output for (77 gated documents, for every tool): conclusions unchanged;
- every set resampled by its recorded clusters: conclusions unchanged (rizzo-pii [−0.022, −0.004]);
- nullpii with every category masked, on the core labels (0.747), as the baseline: ahead of the same 14 rows, also with the Bonferroni correction (narrowest nvidia/gliner-PII [+0.009, +0.047]), and behind rizzo-pii, −0.022, significantly in both tests ([−0.031, −0.013] at 95%, [−0.034, −0.008] corrected).

**OpenMed's texts with no output.** `deidentify` refuses some texts as suspicious content (7 traces-v3 transcripts, 2 PIILO essays, 2 RedactionBench documents and 1 mama-deid text, for both models at both points) and fails its own safety-sweep check on others, more at the tuned points' lower thresholds (Small tuned: 7 REDACT, 41 Tonic, 11 PIILO, 1 eu-clinical, 83 mama-deid; Large tuned: 9 REDACT, 3 Tonic, 1 PIILO, 59 mama-deid). They score as no spans. The package logs no text, so each failure is matched to its document by length and empty output (`scripts/ab/openmed_no_output.py`).

**PIIMB** (`sentences` subset, 150,022 texts, nullpii with every category masked (the default before 0.5)), scored by us with the leaderboard's method (`scripts/ab/piimb_score.py`), not a submitted entry: average F2 0.851, above all 35 listed tools; OpenMed privacy-filter-multilingual-v2 0.836, OpenMed PII SuperClinical Large 0.835. Per task, nullpii's F2: ai4privacy-en 0.960, ai4privacy-multilingual 0.940, nemotron-pii 0.953, Gretel 0.962, privy 0.713, mapa-eur-lex 0.580. Caveats:
- the nemotron-pii task is in nullpii's training family; without it nullpii averages 0.831, against gliner-stream-pii's 0.826 and privacy-filter-multilingual-v2's 0.822, and the leaderboard gives no intervals;
- the ai4privacy tasks come from the same family as part of the tuning set;
- PIIMB shaped a design decision: an earlier result, on which nullpii missed every category it did not mask then, is why the five extended categories exist. They were masked by default until 0.5; the 0.5 default for coding agents leaves them readable. PIIMB has not been used to tune anything.

**Latency** is in the README; it is measured on idle machines, every tool on the same texts of coding-agent material (code, logs, prose and tool output) at 2,000, 30,000 and 100,000 characters, after a warm-up. On GPU every tool runs the full plan: 60, 12 and 5 texts per size, in three rounds, and the table shows the median of the rounds' medians. On CPU, where the full plan takes hours for a single tool, every tool runs the short plan: one text of each kind at 2,000 and 30,000 characters (6 each) and three at 100,000, timed once, and the table shows their median. The short plan's texts are a subset of the full plan's.

## Limits

- F2 rewards over-masking. nullpii ranks on recall: at F0.5 most compared tools rank above it.
- Five gated datasets is a small sample of the world, and only English, the main EU languages and Greek are covered.
- Gold labels differ in scope between datasets. PIILO labels only students' names, contact details, addresses, URLs and ids, so another person's name, a date or a place that a tool masks counts against it. Tonic's gold does not include city, state or postcode, which affects every precision figure on it.
- The tuning set is close to nullpii's training distribution and partly to some competitors' (it is used to choose, never to claim).
- Latency depends on hardware and load; it is measured on idle machines, every tool on the same corpus.

## Reproduce

`scripts/bench_full.py` runs any tool on any dataset and writes per-document predictions; `scripts/ab/char_metrics.py` scores them (`--cluster-rows` and `--exclude` for the sensitivity checks); `scripts/ab/r2_verdict.py` applies the comparison rules; `scripts/ab/tune_operating_point.py` tunes a competitor; `scripts/ab/score_capture.mjs` captures nullpii's spans; `scripts/ab/piimb_score.py` scores PIIMB; `scripts/ab/competitor_latency.py` and `scripts/ab/harness.mjs` time the tools.
