# Report set R3: selection criteria (PROTOCOL rule change 10)

Written and committed before any candidate dataset's text is opened. The shortlist comes from metadata only: dataset cards, licence files, papers and file listings. No row was downloaded, sampled or printed. A change to this file after any R3 text is opened is logged in `LOG.md`, with its reason.

## Criteria

**C1. Licence.** A dataset enters R3 only if its terms permit evaluation and the frozen text can be redistributed with the kit, or at least re-downloaded by anyone without a personal approval step. The terms are quoted below. Excluded (owner decision, 2026-10-19):
- data under a data-use agreement or credentialed access;
- data with no licence;
- data whose terms forbid sharing the dataset or modified versions.

This last rule excludes Samsung CredData (per-file upstream licences) and bigcode-pii-dataset (manual approval, no sharing).

**C2. Gold.**
- **Gated datasets:** human-annotated gold, or text generated with values injected or realigned by code and audited by humans.
- **Not allowed in the gate:**
  - gold checked only by models;
  - silver NER;
  - pseudonymiser output;
  - entity lists without offsets.

**C3. Labels.** Each native label is written down, before the data is opened, as one of:
- a core category;
- an *ignore region*, which is neither true positive nor false positive and is applied to every tool;
- unknown, which raises.

Where the gold deliberately labels only some instances of a core category, the rule for the rest is fixed below.

**C4. Independence.** Each of the following excludes a dataset:
- (a) a compared tool declares training on it;
- (b) it is derived from an excluded source:
  - the ai4privacy family, Isotonic, argilla, DeepMount00/pii-masking-ita;
  - TAB;
  - Nemotron-PII;
  - both Gretel PII sets;
  - every PIIMB task;
  - the rizzo corpus;
  - urchade/synthetic-pii-ner-mistral-v1;
  - presidio-evaluator templates;
  - this project's generators;
- (c) this project has loaded it as gold before (MEDDOCAN, conll2003, wikiann).

Two further rules:
- **Time check.** A dataset first published after a tool's last weight commit cannot be in that tool's training.
- **Overlap.** After freezing, 64-character-window overlap against nullpii's training corpus and every public declared training set is measured. Above 1%, the dataset is flagged ‡ for that tool and leaves that tool's S1/S2 tests. Only aggregate shares are printed.

A tool's authors reporting an evaluation on a dataset is disclosed, but does not exclude it.

**C5. Coverage, over the whole set.**
- Several EU languages including Italian.
- Business, finance, legal and medical prose.
- Email and chat.
- Coding-agent traces.

An **English-only macro** is reported next to the full macro, because 7 of the 14 tools are English-first.

**C6. Size.**
- A gated dataset has at least 200 documents and 1,000 gold core spans.
- Smaller sets enter only inside a bucket declared here.
- A large set is sampled with the size and seed fixed here.

**C7. Reproducibility.**
- Character offsets into the raw text.
- A pinned revision.
- A SHA-256 freeze before any tool runs.

## R3

### Gated (S1/S2 are decided on these)

| Key | Source and revision | Licence | Gold | Rows used | Label rules |
|---|---|---|---|---|---|
| `redact` | `guneeshv/REDACT-PII-Benchmark` @ `1d7fef6` | REDACT Dataset Terms v1.0: "benchmarking and evaluation" permitted; redistribution with the terms file and notices kept | LLM text, offsets realigned by code, 510 entities hand-checked (99.1% agreement) | The locked 1,000-record test split, records in an EU language or English only | Core: names, emails, phones, addresses, city, state, date/time, DOB, static IP, card, national ID, tax reference, password, passport, driving licence, geolocation. Ignore: organisation, age, gender and every other non-core type, plus spans marked `disclosed=false` |
| `tonic-human` | `TonicAI/Privacy-Bench` @ tag v2.5 (tag ref `a9f3e39`, commit `a79d9e8`), the 6 `human_annotations` configs | CC BY 4.0 | Human-corrected | All rows | Core: NAME_GIVEN, NAME_FAMILY, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION_ADDRESS, ACCOUNT_NUMBER, URL. Ignore: USERNAME, EMPLOYEE_ID, ORGANIZATION. City, state and ZIP are not gold (stated with every precision figure) |
| `piilo` | Kaggle `lburleigh/piilo-dataset` v2 | CC BY 4.0 | Human (Kaggle competition) | Every essay (6,807). Corrected 2026-10-19 after the build and before any scoring: the first text's 2,000-essay sample held 434 gold spans, under C6's floor of 1,000 | Core: NAME_STUDENT, EMAIL, USERNAME, ID_NUM, PHONE_NUM, URL_PERSONAL, STREET_ADDRESS. Only students' names are gold; other people's names are scored as written, and the precision caveat is stated |
| `eu-clinical` (bucket) | Greek clinical de-id benchmark, Zenodo 10.5281/zenodo.22824895; GraSCCo_PHI, Zenodo 11502329 | CC BY 4.0 (both) | Human: two blinded reviews plus arbitration; Krippendorff's α ≈ 0.97 | All 500 Greek notes and all German letters, as one dataset | Core categories from each guideline, fixed in the loader before the gold files are opened. Hospital and organisation are ignore regions, and so are age and profession (C3; corrected 2026-10-19 after the build and before any scoring: the first text said "dropped", which C3 does not allow and which contradicted the redact row) |
| `traces-v3` | New coding-agent traces from an independent generator (rule change 10.2): spec in `scripts/r3/TRACES_SPEC.md`, generator written by an agent with no access to this project's generators, corpora or tuning sets | Apache-2.0 (project-authored); carriers permissively licensed and outside the packages nullpii's corpus used | Values injected by code at known offsets | Size and seed fixed in the spec | As the spec states. Distractor regions (timestamps, public URLs, loopback addresses, placeholders) come in a sidecar; precision is reported with and without them |

### Reported, not gated (owner decision, 2026-10-19)

| Key | Source | Why not gated |
|---|---|---|
| `redactionbench` | `A10Networks/RedactionBench` @ `1af44a6` (CC BY 4.0; 101 documents sourced from the public web, used locally and not bundled) | Untyped gold (`mandatory` / `contextual`), so the core regime cannot be applied. Scored label-agnostic with contextual spans as ignore regions. The dev genres (code, logs, terminal, files) are a separate slice. Its authors searched thresholds on it for 7 of our tools; those thresholds are not reused |
| `mama-deid-val` | `mamahealth/mama-deid-dataset` @ `2277eb8`, validation split only (CC BY 4.0) | Gold checked by models only. Its train split contains Nemotron rows, so the overlap check runs against Nemotron-PII as well |

### Excluded from the shortlist, with reasons

- **CredData, bigcode-pii-dataset:** C1 (owner decision).
- **ABCD:** gold would come from an alignment rule not yet written; reconsider only with that rule fixed first.
- **SPY:**
  - only the asker's PII is gold;
  - Faker values are in nullpii's training distribution;
  - its loader executes code.
- **LLM-Redactor leak benchmark:** 800 template prompts with no licence file in the repository.
- **Everything in the research note's reject table:** C1, C2 or C4.

## Access

These require an action on the owner's accounts and are not taken without the owner's go:
- `redact`: HF gated, auto-approval, which means accepting the REDACT terms;
- `piilo`: a Kaggle account.

Everything else is public.

## Statistics

Unchanged from rule change 9:
- char-level F1, F2 and F0.5;
- paired bootstrap, with traces-v3 resampled by template cluster;
- leave-one-dataset-out;
- a mask-all row.

New with rule change 10: S1 is decided against each competitor's better row (default or tuned), and an English-only macro is reported.
