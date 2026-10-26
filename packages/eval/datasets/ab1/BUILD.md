# AB-1 component A — agent traffic

Canary: `AB1-CANARY-6f3a1c9e-nullpii-agentbench-2026-10-23`

This directory holds component **A (Agent traffic)** of AB-1 as pre-registered in `SPEC.md`
(1,200 documents an agent sees, with injected fictional values and annotated keep items).
Components B1 and B2 are not built here. The builder had only `SPEC.md` and the build brief; no nullpii
repository, corpus, model or tool was read or run, and no PII-masking tool or model was used.

## Layout

| path | content |
|---|---|
| `data/ab1.jsonl` | the gold: one JSON object per document (schema below) |
| `data/stats.json` | counts per split × kind × lang × origin, per split × class × category, clean documents, encoded copies, gitleaks rules used, template families |
| `data/CANARY` | the canary string (first line) |
| `gen/` | generator code (Python), `gen/requirements.txt`, the reviewed carrier decisions `gen/carrier_review.tsv`, the value blocklist `gen/blocklist.txt`; `gen/real/` holds the phase-A scripts that selected and fetched the non-English carrier material |
| `lists/` | value lists and `lists/SOURCES.md` (URL, licence, revision/date of each) |
| `checks/validate.py` | the validator; its output is at the end of this file |
| `cache/` | downloads and intermediate files (not part of the frozen set): the two carrier pools `cache/pool.jsonl` and `cache/pool_real.jsonl`, and the phase-A real material in `cache/real/` |

Schema of a row: `{"id", "split": "dev"|"test", "kind": "prompt"|"file"|"shell"|"log"|"tool_json"|"ticket",
"lang": "en"|"it"|"de"|"fr"|"es", "origin": "carrier"|"template", "carrier": {"dataset", "revision", "row", "start", "end"} | null,
"text", "items": [{"start", "end", "class": "MUST_MASK"|"MUST_KEEP"|"AMBIGUOUS", "category", "kind", "encoded_of"}]}`.
Offsets are Python code-point offsets into `text`, end exclusive. Items never overlap. For MUST_MASK items
`category` is one of secret, person, email, phone, address, account, ip, mac, url, passport, driver_license,
national_id, iban, card and `kind` is a finer type (e.g. `gitleaks:<rule id>`, `password`, `full_name`,
`os_username`, `it_codice_fiscale`); an encoded copy has kind `base64:<original kind>` or `urlencoded:<original kind>`
and `encoded_of` = index of the original item in the same document. For MUST_KEEP and AMBIGUOUS items
`category` = `kind`. Carrier `row` is `<trajectory_id>/trajectory[i].content` (or `.tool_calls[j].function.arguments`)
for SWE-rebench rows, `<parquet row>/trajectory[i].content` (or `.extras`) for openhands-feedback rows,
`<conversation_hash>/turn<i>` for WildChat-1M rows and `<owner>/<repo>#<number>` for GitHub issues;
`start`/`end` are offsets of the excerpt inside that field. A GitHub issue carrier carries two extra keys,
`url` (the issue's `html_url`) and `license` (the repository's SPDX licence at fetch time), so the text can be
re-fetched and its licence re-checked.

## How to rebuild

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r gen/requirements.txt
.venv/bin/python gen/build.py          # downloads the carriers at the pinned revisions if missing, builds data/
.venv/bin/python checks/validate.py    # all checks (the carrier scan is the slow part and caches its result)
```

`gen/build.py` downloads the carriers (`gen/download.py`), builds the two carrier pools once
(`gen/carriers.py` → `cache/pool.jsonl` from the two parquet datasets, `cache/pool_real.jsonl` from the
phase-A material in `cache/real/`), then generates every document. It reads only `lists/` for values;
`gen/fetch_lists.py` is how `lists/` was produced (re-running it queries live services and is not needed).
`gen/real/wildchat_select.py` and `gen/real/gh_fetch.py` are how `cache/real/` was produced (they are not run
by the build; they need the WildChat download and the network respectively). `gen/review_dump.py` writes all
carrier regex hits to `cache/review/carrier_hits.tsv` for review.
The build is deterministic: two runs with different `PYTHONHASHSEED` produce byte-identical `data/`,
and `checks/validate.py` re-runs the build in memory and compares.

## Publishing

`gen/real/publish.py` writes `data/ab1-public.jsonl` (plus `data/ab1-public.meta.json`): the same 1,200 rows in the same order as `data/ab1.jsonl`, with one change — every document whose carrier is a GitHub issue carries no `text`. It keeps instead `segments`, the document text as an ordered list of pieces, each either `{"carrier": [start, end]}` (a range of the normalised carrier text `title + "\n\n" + body`, built exactly as the builder normalised it) or `{"text": "..."}` (characters the builder wrote: an injected snippet, an added line break, the encoded copy); and `text_sha256`, the sha256 of the document text, so a rebuild can check itself. The `carrier` record (dataset, revision, row, start, end, url, license) is unchanged. The meta file records the sha256 of both files, the number of GitHub documents (72) and the total literal and carrier characters. **GitHub issue text is not redistributed**: only the URL, the offsets and the pieces of the document that the builder itself wrote travel in the public file; every other document (SWE-rebench, openhands-feedback, WildChat, templates) is published as is.

Rebuilding the gold from the public file fetches the issues back from GitHub:

```bash
GITHUB_TOKEN=... .venv/bin/python gen/real/rebuild_public.py --out ab1.jsonl --in data/ab1-public.jsonl
```

`gen/real/rebuild_public.py` asks the GitHub REST API for `GET https://api.github.com/repos/<owner>/<repo>/issues/<number>` for each issue the segments need (one request per issue, a pause between them, retries with backoff on 403/429, an optional token from `GITHUB_TOKEN`), builds `title + "\n\n" + body` with the builder's own normalisation (`gen/carriers.py`, imported, not copied), fills the segments and checks every document against `text_sha256`. It writes the gold's rows (`text` restored, `segments` and `text_sha256` dropped) to `--out`, and prints how many documents were rebuilt, which ones changed or disappeared (by id, never their text) and whether the whole file's sha256 equals `source_sha256`. An issue edited or deleted after the fetch date (**2026-10-24**, the day `gen/real/gh_fetch.py` ran, recorded as the carrier revision) rebuilds differently: the document is written with whatever text the issue gives now (literals only, if the issue has disappeared) and reported — that is a change in the source, not an error in the rebuild.

The fetch is a single replaceable function, so the whole script runs offline: `checks/test_publish.py` drives it against the local pool (all 72 rebuild, the file's sha256 equals `source_sha256`), against one issue with an edited body and against one issue returning 404 (each reported, exactly once, and the run finishes). Run it with `.venv/bin/python -I checks/test_publish.py`.

## Seeds

- Master seed `MASTER_SEED = 20261023` (`gen/common.py`). Every random choice uses
  `random.Random(derive_seed(*labels))`, where `derive_seed` is the first 64 bits of
  SHA-256 of `json.dumps([MASTER_SEED, *labels])`.
- Labels used: `("doc", id, attempt)` per document; `("enc", id, attempt)` for the encoded copy of a document
  (a separate stream, so the base document is identical with or without it); `("ids", kind)` for id assignment;
  `("clean", split, kind)`; `("carrier-assign", kind, language)`; `("excerpt", candidate id)`; `("pool", candidate id)`
  for the carrier pool priority; `("encode-select",)`; `("street-sample", country)` and
  `("postal-sample", country)` for the list samples; probe RNGs `"probe:<rule id>"` for checking each gitleaks rule.

## Carriers and licences

| dataset | revision | licence | files used |
|---|---|---|---|
| [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) | `35455389ab51bf5e2306bfd436ef72d0f98bf882` | CC BY 4.0 | `trajectories.parquet` |
| [OpenHands/openhands-feedback](https://huggingface.co/datasets/OpenHands/openhands-feedback) | `facf45600d625510b98222ec584a8c9ac59272a2` | MIT | `data/train-00000-of-00001.parquet` |
| [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M) | `7d6490e462285cf85d91eabea0f9a954fbddcd1f` | ODC-BY 1.0 | `data/train-*.parquet` (the first user turn of it/de/fr/es conversations) |
| GitHub issues (`github-issues`) | fetched `2026-10-24` | per document: the repository's SPDX licence, recorded in the carrier | issues of repositories named by [github/multilingual-repositories](https://huggingface.co/datasets/github/multilingual-repositories) |

Notes on the two added sources.

- **WildChat-1M** (Allen Institute for AI, ODC-BY 1.0; please cite *WildChat: 1M ChatGPT Interaction Logs in the
  Wild*, Zhao et al., ICLR 2024). The prompts used here are what people typed **into a chat assistant**, not what
  they typed to a coding agent: they are real non-English programming questions, not agent traffic. The dataset
  replaced some personal data with Presidio-style tags (`<PRESIDIO_ANONYMIZED_EMAIL_ADDRESS>`, `…_PHONE_NUMBER`,
  `…_URL`); those tags are kept verbatim and annotated MUST_KEEP `placeholder`, and everything the carrier regex
  pass finds besides them is annotated as in the English carriers.
- **github/multilingual-repositories** (CC0-1.0, commit `3d63dbdb61f69663486309a1f8805a1c8eb4a353`) is used **only
  to find repositories**: it holds no issue text. It names repositories whose *issues* its classifiers mark as
  Italian, German, French or Spanish with confidence ≥ 0.9 (`gen/real/gh_candidates.py` filters them to those with
  an SPDX licence, ≥ 5 issues and ≥ 3 stars, and ranks the survivors with the builder's seeded priority).
  `gen/real/gh_fetch.py` then fetched the issue text through `gh api` on 2026-10-24, one issue per repository,
  recording that repository's licence as the API reported it at that moment.
- **A GitHub issue keeps its repository's licence.** The repository named by the dataset is only a pointer; the
  licence that applies to the text is the one the repository had when the issue was fetched, and it is recorded
  per document (`license`) next to `url`, `row`, `start` and `end`. With those five values alone the excerpt can be
  fetched again and the document rebuilt exactly, so the carrier record never depends on redistributing the text:
  the project's own Apache-2.0 covers the generator, the lists and the annotations, and every carrier excerpt
  inside `data/ab1.jsonl` stays under its dataset's or repository's own licence (a redistribution that cannot
  carry a given repository's issue text drops it and restores it from the recorded URL and offsets).

Other inputs: gitleaks `config/gitleaks.toml` at tag `v8.30.1`, commit `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` (MIT);
Wikidata (CC0) and GeoNames (CC BY 4.0) lists, details in `lists/SOURCES.md`. The generator, the handmade lists
and the gold are Apache-2.0. Carrier excerpts inside `data/ab1.jsonl` keep their dataset licence
(CC BY 4.0 / MIT / ODC-BY 1.0 / the repository's own).
Python packages: huggingface-hub (Apache-2.0), pyarrow (Apache-2.0), pyahocorasick (BSD-3-Clause).

## Choices made where SPEC.md left room

**Plan and splits**
1. Counts per kind: prompt 240, file 240, shell 240, log 180, tool_json 120, ticket 180. Inside each
   (kind, language, origin) cell, `round(n/6)` documents are dev and the rest test, so every kind is exactly 1/6 dev.
2. Prompts and tickets are 1/5 per language (48 prompts, 36 tickets each), and **every (kind, language) cell of
   these two kinds is exactly half carrier, half template**: 24 carrier + 24 template prompts and 18 carrier +
   18 template tickets per language. English takes its carriers from the English datasets as before
   (openhands-feedback user messages, SWE-rebench issue descriptions) and its templates from English families
   written for this step, structurally identical to the it/de/fr/es ones; it/de/fr/es take half their prompts from
   WildChat-1M first user turns and half their tickets from GitHub issues, the other half from the template
   families. So all five languages now carry both origins, and file, shell, log and tool_json stay English and
   exactly half carrier, half template.
3. Clean documents (no MUST_MASK item) are exactly 20% of every (split, kind), assigned round-robin over the
   (language, origin) cells after a seeded shuffle. A clean carrier document is the verbatim excerpt; a clean
   template document uses only keep / ambiguous stand-ins (placeholders, env references, example.com addresses,
   RFC 5737 / 3849 addresses, role addresses, dummy credentials, public figures).
4. Ids are `ab1-<kind>-<nnnn>`, numbered after a seeded shuffle within the kind (the id says nothing about split,
   origin or cleanliness).

**Carriers**
5. Mapping of carrier material to kinds. English: prompts = real user messages of openhands-feedback;
   tickets = the `<issue_description>` of the first user turn of SWE-rebench trajectories; file reads =
   `str_replace_editor view` outputs and `cat/head/tail/sed -n` outputs of a single file; shell = other
   `execute_bash` / `run` outputs (git diff/log/show/status, test runs, installs, listings, grep, curl, scripts,
   docker/kubectl); logs = outputs containing a traceback or ≥ 3 log-level lines; tool_json = the arguments
   string of a `str_replace_editor` / `execute_bash` call, or the `extras` JSON of an openhands-feedback
   `run` / `run_ipython` action. it/de/fr/es: prompts = the first user turn of a WildChat-1M conversation of that
   language, tickets = a GitHub issue of that language (text `title + "\n\n" + body`, as fetched). Sub-type
   quotas are in `CARRIER_MIX` and the per-language buckets in `LANG_CARRIER_BUCKET` (`gen/build.py`).
6. Pools: the two parquet datasets are pooled in `cache/pool.jsonl`, the phase-A material in
   `cache/pool_real.jsonl` (one bucket per (kind, language), each rebuilt deterministically by
   `gen/carriers.py: build_real_pool`). Every candidate gets the priority `derive_seed("pool", id)` — for the
   phase-A material the id is `<dataset>|<row>`, i.e. `allenai/WildChat-1M|<hash>/turn<i>` and
   `github-issues|<owner>/<repo>#<number>` — and the pool is walked in priority order.
   Selection takes at most one excerpt per repository (SWE-rebench, GitHub issues) or conversation (feedback,
   WildChat) per (kind, language), skips excerpts whose first 150 normalised characters repeat an already chosen
   one (canned messages reused across sessions), and for the English prompt and ticket buckets requires English
   prose (stop-word ratio over non-code lines, no non-Latin script); the phase-A material was already filtered by
   language when it was selected (`gen/real/`), so the buckets for it need no English test.
7. Excerpts are cut at line boundaries, 300–6,000 characters, target length drawn uniformly in 700–3,600;
   a prompt or issue that fits is taken whole (for WildChat and GitHub candidates the pool already holds only
   texts of 300–6,000 characters, so they are always taken whole); a tool-call argument string is always taken
   whole (so it stays valid JSON). The final newline is not part of the excerpt. Carrier text is kept verbatim
   (CRLF line ends and ANSI colour codes included).

**Injection (where values go)**
8. Non-clean carrier documents get one snippet (excerpt < 1,500 characters) or one to three snippets, inserted
   only at line boundaries: at paragraph boundaries outside code fences for prompts, tickets and Markdown/RST
   files; in code at statement boundaries outside multi-line strings, with the indentation of the next line, in
   the file's own syntax (`.py`, `.js`, YAML, TOML/INI, JSON, shell); in logs before a traceback, after an
   exception line or between log lines; in shell output at the top (a `user@host:~/dir$ <command>` prompt line,
   a new commit for a `git log`) or at the end; never after the OpenHands status footer
   (`[The command completed …]`, `[Current working directory: …]`).
9. `cat -n` gutters are renumbered after an inserted line; lines added to a diff are `+` lines and the hunk
   header's new-side count is updated so the patch still applies to its pre-image.
10. Sandbox project roots (`/workspace/<repo>`, `/testbed`) are replaced everywhere in the excerpt, when they occur
    at most 6 times (shell, log and file carriers: with probability 0.5; tool_json carriers: always), by
    `/home/<user>/<dir>/<repo>` or `/Users/<user>/<dir>/<repo>` of one fictional user.
11. In tool_json carriers the injected lines go inside a JSON string after an escaped newline, JSON-escaped
    (`old_str` is never modified, so the edit still matches its file); a command without newlines gets an
    `export VAR=<secret> && ` prefix.
12. Templates: 22 file families (.env, compose, k8s, GitHub/GitLab CI, Spring YAML, Django settings, package.json,
    package-lock, pyproject, requirements with hashes, Dockerfile, Python/JS source, SQL seed, JSON fixtures, CSV
    export, dotfiles, tfvars, nginx, appsettings.json, README), 19 shell, 12 log, 11 tool_json families, and 12
    prompt and 9 ticket families **in all five languages** (written by the builder): the English families were
    added for this step and have the same variants, the same slots and the same labels as the it/de/fr/es ones
    (`gen/tpl_lang.py`), so an English template document injects exactly what the other languages inject. File
    reads are rendered raw (40%), with a `cat -n` gutter (35%) or with the OpenHands view header (25%); a file
    with a multi-line item is always raw.
    Tool-call JSON follows Claude Code (`command`/`description`, `file_path`/`content`, `old_string`/`new_string`,
    `edits`, `url`/`prompt`, `todos`, `subagent_type`) and OpenHands (`command`/`path`/`file_text`, `code`) shapes.
13. Non-English documents use addresses and phones of their language's country; English documents use the US or
    the UK; customer records inside English technical templates are drawn from all five languages. Because the
    it/de/fr/es prompt and ticket cells halved when they became half carrier, the address-bearing bands of the
    prompt and ticket snippets were widened (`gen/inject.py`) so the test split still holds at least 150 addresses.

**Values**
14. Secrets: each provider-format secret draws a gitleaks rule uniformly from the 221 usable rules of v8.30.1
    (`pkcs12-file` has no content regex and is excluded). The value is generated by walking the rule's regex
    (its secret group, or the whole match when it has none), after translating the RE2 constructs Python lacks
    (mid-pattern `(?i)`, `\z`, POSIX classes). It is accepted only if the full rule regex matches it in a canonical
    line (`VAR=value`, or the rule's own context for curl/nuget/terraform/k8s rules), the matched secret equals the
    value, it meets the rule's entropy and passes the rule and global allowlists. Structure-aware generators are
    used where a provider publishes a layout: GitHub `ghp_/gho_/ghu_/ghs_/ghr_` and npm `npm_` tokens with the
    CRC32/base62 6-character checksum, fine-grained PATs, AWS `AKIA/ASIA`, Google `AIzaSy`, Slack bot/user tokens
    and webhook URLs, Stripe, JWTs (real header/payload, random signature), PEM private keys (random DER body),
    Bedrock short-lived keys (base64 of a presigned URL), Sourcegraph tokens. Rule draws per rule are in `stats.json`.
15. Other secrets (not gitleaks formats): human passwords (word+year+symbol, name-based, random 12–32 chars),
    passwords inside connection strings, session cookies, Django `SECRET_KEY`, AWS secret access keys, and the
    base64 `data:` values of `kubectl get secret -o yaml` (category secret, kind `base64:gitleaks:<rule>`).
16. Names: given names by gender and family names per language from Wikidata (by sitelink rank); a person is a
    random given + family name of one language. Usernames, handles and e-mail local parts are folded to ASCII
    (German umlauts → ae/oe/ue). Personal e-mails use the country's free-mail domains; work e-mails (35%) use a
    fictional company domain built from a surname and an industry word (such a domain may exist; the address is
    still generated, not taken from anyone).
17. Addresses: a real street name of the country (Wikidata) + random house number + a random postcode/place of the
    same country (GeoNames), in the national format; the combination is fictional.
18. Phones: random numbers in valid national formats (mobile and landline prefixes, several spellings); reserved
    fiction ranges were not used, to keep the formats realistic.
19. Ids: cards are Luhn-valid Visa/Mastercard/Amex/Discover numbers (well-known test numbers excluded; they appear only
    as AMBIGUOUS dummies). IBANs are mod-97 valid for IT, DE, FR, ES, GB, with the national check computed for IT
    (CIN), FR (RIB key) and ES (DC); DE and GB account check digits are bank-specific and not computed. National ids:
    IT codice fiscale consistent with the person's name, gender and birth date (check character computed), ES DNI/NIE
    (mod-23 letter), FR NIR (key 97 − n mod 97), DE Steuer-IdNr (ISO 7064 MOD 11,10), US SSN and GB NINO (structure
    rules; these formats have no check character). Passport and driver-licence numbers follow national layouts
    (GB driver number built from surname and birth date). Account numbers: customer ids, user account ids, bank
    account numbers, Stripe customer ids, contract numbers → category `account`.
20. Network: public IPv4/IPv6 addresses outside private, reserved and documentation ranges (`is_global`), up to 15% IPv6 depending on the context;
    MAC addresses unicast, in colon, dash and Cisco notations. Server IPs in `curl -v` output and traceroute hops
    are public IPs and therefore MUST_MASK `ip`, as SPEC.md lists them.
21. Personal URLs: GitHub/GitLab/LinkedIn/X/Twitter/Medium/Mastodon/Instagram profiles and personal domains of
    fictional people → `url`. Profile URLs of real maintainers found in carriers → AMBIGUOUS `maintainer_handle`.

**Item boundaries**
22. Private key: the base64 body between the BEGIN and END lines is one item (header and footer lines are not part
    of it); in JSON or `.env` strings the body includes the escaped `\n` separators.
23. Connection strings: only the password is MUST_MASK; the host is annotated on its own (AMBIGUOUS internal host /
    RFC 1918 IP, MUST_MASK public IP or MUST_KEEP localhost) and the port is MUST_KEEP; the database user is a service
    account and is not annotated. A token in a URL: the token is MUST_MASK and the URL up to the query string is MUST_KEEP.
24. Home paths: `/home/` or `/Users/` is not annotated, the username is MUST_MASK `person/os_username`, the rest
    of the path is MUST_KEEP `path`. Generic accounts (`root`, `runner`, `ubuntu`, `deploy`, `ci`, …) are not persons.
25. E-mail headers and `git log` lines: display name (`person`) and address (`email`) are separate items; an
    honorific before a name is its own MUST_KEEP item. Values inside JSON strings are annotated in their escaped form.
26. Dates and timestamps are MUST_KEEP except birth dates, which are AMBIGUOUS and only appear next to a birth-date
    label in templates. Order and invoice numbers are AMBIGUOUS; ticket, issue and PR references are MUST_KEEP.

**Encoded copies**
27. Exactly `round(5% × injected values)` copies: the build runs twice; pass 1 counts injected MUST_MASK values,
    then documents with a usable hook are picked by a seeded shuffle and get one encoded copy each in pass 2 (drawn
    from the separate `("enc", id)` stream). Secrets are base64-encoded; other values are URL-encoded when that
    changes them (e-mails, names, phones, addresses, spaced IBANs/cards), otherwise not eligible. Context-specific
    places are used first (URL-encoded password in a DSN next to the plain one, `data:` of a k8s Secret, a query
    string of a search/reset link, an API request line in a log); otherwise the copy is appended as a new last line
    in the document's own idiom (`curl …?query=`, `echo -n "$VAR" | base64`, a debug header line, a code comment,
    a `Link:` / `(in base64: …)` line in prompts and tickets).

**Annotation passes**
28. Carrier regex pass (`gen/annotate.py: carrier_pass`) on the raw excerpt, before injection: e-mails, phone
    numbers, IPv4/IPv6, MAC addresses, the 221 gitleaks rules, `password=/token=/api_key=` assignments, high-entropy
    strings, names in authorship contexts (git `Author:`, `Signed-off-by:`, copyright lines, package metadata,
    `Name <e-mail>`, `Name (@handle)`), `@handles` in prose and home-directory usernames. Classification:
    example.com/.test addresses, 127.0.0.1/0.0.0.0/::1 and documentation IPs → MUST_KEEP `reserved_address`;
    role mailboxes → AMBIGUOUS `role_address`; RFC 1918 / link-local / CGNAT → AMBIGUOUS `rfc1918_ip`;
    placeholder-like key values → AMBIGUOUS `dummy_credential`; copyright and package-author names → AMBIGUOUS
    `licence_name`; everything else real-looking → AMBIGUOUS `carrier_pii` (handles → `maintainer_handle`).
    All hits of the selected excerpts were reviewed (`gen/review_dump.py` → `cache/review/carrier_hits.tsv`), 62
    rows in the current build, and `gen/carrier_review.tsv` records the per-value decisions: seven values the rules
    got wrong, left unannotated — a Jetpack Compose annotation taken for a handle, a forum URL path slug, an
    `Example…` documentation file name, two PV-simulation file names, two four-part version numbers taken for IP
    addresses — one real personal name in a WildChat customer record the rules miss (annotated AMBIGUOUS
    `carrier_pii`, next to the mobile number they do find) and one maintainer URL forced to AMBIGUOUS
    `maintainer_handle`. Everything else the rules found stands. Earlier rule changes fixed the false hits seen on
    the English carriers (Makefile `@echo`, file names and dotted identifiers taken for keys, `\n@decorator` taken
    for an e-mail, `"name":` JSON fields taken for people, service users such as `opendevin`).
29. Keep regex pass (`gen/annotate.py: keep_pass`) on every document after injection, never overlapping an
    existing item: public URLs (internal hosts → AMBIGUOUS `internal_host`, example.com/localhost →
    `reserved_address`, single-segment profile URLs → AMBIGUOUS `maintainer_handle`), git remotes, UUIDs, hashes
    (`sha256:`/`sha512-` digests, 64- and 32-hex), 40-hex and short SHAs in git contexts, env references
    (`${VAR}`, `$VAR`, `${{ secrets.X }}`, `%VAR%`, `process.env.X`, `os.environ[...]`), placeholders
    (`YOUR_…`, `<your-token>`, `xxxxxx`, `****`, `[REDACTED]`, `{{ var }}`, and the Presidio-style anonymisation
    tags WildChat-1M left upstream such as `<PRESIDIO_ANONYMIZED_EMAIL_ADDRESS>`), file paths (absolute, `~/`, relative with
    an extension, Windows), dates and times (ISO, CLF, RFC 2822, git, syslog, numeric, written months in the five
    languages), remaining RFC 1918 IPs, versions, ticket/issue/PR numbers, line numbers, HTTP status codes, PIDs,
    ports, code identifiers (`def/class/function/func/fn` names, traceback frames, Java frames), organisation names
    from `lists/handmade/orgs.txt` (common words such as *Apple*, *Express*, *Linear* excluded) and multi-word job titles.
    Template insertions annotate their own keep items (name-like identifiers such as `getRossiConfig` or `class Mueller`,
    companies, job titles, honorifics, paths, versions, …); the two audit rules below reclassify such items too, since
    a template-placed UUID or encoded value is already an item when this pass runs.
30. MUST_KEEP kinds used: code_identifier, public_url, sha, hash, uuid, version, date, org, job_title, honorific,
    placeholder, env_ref, reserved_address, ticket_number, line_number, port, pid, http_status, path.
    AMBIGUOUS kinds: carrier_pii, licence_name, public_figure, maintainer_handle, role_address, internal_host,
    rfc1918_ip, order_number, birth_date, dummy_credential, session_id.
31. From the audit: a UUID that directly follows a session-like key (`session`, `session_id`, `sessionId`, `sid`,
    `token`, `cookie`, with `=` or `:`, optional quotes, case-insensitive) is AMBIGUOUS `session_id` — it sits
    between two SPEC.md entries (UUIDs are MUST_KEEP, session cookies are secrets) — every other UUID stays
    MUST_KEEP `uuid`. 23 items (dev 3, test 20).
32. From the audit: a base64- or URL-encoded value that decodes to a dummy credential of the SPEC AMBIGUOUS list
    (`gen/keepvals.py: dummy_cred` → `lists/handmade/dummy_credentials.txt`) is AMBIGUOUS `dummy_credential`, not a
    MUST_KEEP `placeholder`; encoded values that decode to a real placeholder (`REPLACE_WITH_…`, `YOUR_…`) stay
    MUST_KEEP `placeholder`. 1 item.

**Fictional values**
33. Every MUST_MASK value is generated; `checks/validate.py` scans all text of all four carrier datasets (every row:
    trajectory messages, tool-call arguments, patches, feedback steps, and for the phase-A material the whole
    WildChat and GitHub pools in `cache/real/`, not only the excerpts that were selected) for each value as a whole
    token. Single-token values that are entries of the name lists (a bare first name, or a username equal to one)
    are exempt, since common names occur in any large text. Values found are added to `gen/blocklist.txt` and
    re-drawn (three so far, all usernames: one found in the English carriers and two found in the phase-A material
    once it was scanned whole — the second scan is what caught them).

**Canary**
34. The canary is in this README and on the first line of `data/CANARY`; rows of `ab1.jsonl` carry no canary field.

## Statistics

Documents (dev / test) per kind, language and origin:

| kind | lang | origin | dev | test |
|---|---|---|---|---|
| prompt | en | carrier | 4 | 20 |
| prompt | en | template | 4 | 20 |
| prompt | it | carrier | 4 | 20 |
| prompt | it | template | 4 | 20 |
| prompt | de | carrier | 4 | 20 |
| prompt | de | template | 4 | 20 |
| prompt | fr | carrier | 4 | 20 |
| prompt | fr | template | 4 | 20 |
| prompt | es | carrier | 4 | 20 |
| prompt | es | template | 4 | 20 |
| file | en | carrier | 20 | 100 |
| file | en | template | 20 | 100 |
| shell | en | carrier | 20 | 100 |
| shell | en | template | 20 | 100 |
| log | en | carrier | 15 | 75 |
| log | en | template | 15 | 75 |
| tool_json | en | carrier | 10 | 50 |
| tool_json | en | template | 10 | 50 |
| ticket | en | carrier | 3 | 15 |
| ticket | en | template | 3 | 15 |
| ticket | it | carrier | 3 | 15 |
| ticket | it | template | 3 | 15 |
| ticket | de | carrier | 3 | 15 |
| ticket | de | template | 3 | 15 |
| ticket | fr | carrier | 3 | 15 |
| ticket | fr | template | 3 | 15 |
| ticket | es | carrier | 3 | 15 |
| ticket | es | template | 3 | 15 |

Carriers by dataset: SWE-rebench 343 (file, shell, log, tool_json, English tickets), openhands-feedback 89
(English prompts), WildChat-1M 96 (it/de/fr/es prompts), GitHub issues 72 (it/de/fr/es tickets); 528 carriers
record `dataset`/`revision`/`row`/`start`/`end` and the 72 GitHub ones add `url` and `license`.

Clean documents (no MUST_MASK item): dev 40, test 200 (20.0% of each).  
Injected MUST_MASK values (originals): 4002; encoded copies: 200 (dev 43, test 157) = 5.00%.  
gitleaks v8.30.1 (83d9cd684c87): 221 of 222 rules usable; 450 provider-format secrets placed as originals, covering 195 rules (per-rule counts in `data/stats.json`).

Items per class × category (dev / test):

| class | category | dev | test |
|---|---|---|---|
| MUST_MASK | account | 31 | 198 |
| MUST_MASK | address | 35 | 160 |
| MUST_MASK | card | 19 | 56 |
| MUST_MASK | driver_license | 1 | 9 |
| MUST_MASK | email | 132 | 557 |
| MUST_MASK | iban | 27 | 91 |
| MUST_MASK | ip | 53 | 436 |
| MUST_MASK | mac | 24 | 104 |
| MUST_MASK | national_id | 5 | 31 |
| MUST_MASK | passport | 1 | 12 |
| MUST_MASK | person | 225 | 1009 |
| MUST_MASK | phone | 40 | 170 |
| MUST_MASK | secret | 116 | 589 |
| MUST_MASK | url | 11 | 60 |
| MUST_KEEP | code_identifier | 71 | 408 |
| MUST_KEEP | date | 149 | 742 |
| MUST_KEEP | env_ref | 17 | 132 |
| MUST_KEEP | hash | 27 | 125 |
| MUST_KEEP | honorific | 23 | 103 |
| MUST_KEEP | http_status | 22 | 138 |
| MUST_KEEP | job_title | 25 | 110 |
| MUST_KEEP | line_number | 76 | 387 |
| MUST_KEEP | org | 50 | 191 |
| MUST_KEEP | path | 250 | 1461 |
| MUST_KEEP | pid | 28 | 161 |
| MUST_KEEP | placeholder | 30 | 194 |
| MUST_KEEP | port | 59 | 260 |
| MUST_KEEP | public_url | 72 | 452 |
| MUST_KEEP | reserved_address | 39 | 170 |
| MUST_KEEP | sha | 55 | 153 |
| MUST_KEEP | ticket_number | 40 | 118 |
| MUST_KEEP | uuid | 21 | 145 |
| MUST_KEEP | version | 75 | 531 |
| AMBIGUOUS | birth_date | 1 | 17 |
| AMBIGUOUS | carrier_pii | 3 | 24 |
| AMBIGUOUS | dummy_credential | 11 | 32 |
| AMBIGUOUS | internal_host | 20 | 83 |
| AMBIGUOUS | licence_name | 0 | 1 |
| AMBIGUOUS | maintainer_handle | 0 | 17 |
| AMBIGUOUS | order_number | 6 | 20 |
| AMBIGUOUS | public_figure | 5 | 27 |
| AMBIGUOUS | rfc1918_ip | 21 | 138 |
| AMBIGUOUS | role_address | 17 | 65 |
| AMBIGUOUS | session_id | 3 | 20 |

Totals: dev MUST_MASK 720; dev MUST_KEEP 1129; dev AMBIGUOUS 87; test MUST_MASK 3482; test MUST_KEEP 5981; test AMBIGUOUS 444.
Test-split ids and accounts together: 397.

SHA-256: `data/ab1.jsonl` `54ee48c3248b13c1845e510d531402f0c06873e0509503fb9bceaafb156d7a44` (2,801,698 bytes),
`data/stats.json` `993f51c42a38773a53013f5c2adfd2e9fb8e16be9ef6637e39dc1a0708d09de7` (16,443 bytes),
`data/ab1-public.jsonl` `69f8ee893ac125338bec89c1a99d0281c02f640227da03d3c3c7a6d131aef9b7` (2,723,183 bytes).

## Validation output

`python checks/validate.py` (full run, including the carrier scan and the rebuild comparison):

```
PASS  schema: fields, enums, unique ids                                                                                                                                                                                                   1200 rows; problems: []
PASS  offsets: inside text, non-empty                                                                                                                                                                                                     0 bad
PASS  offsets: no item has leading/trailing whitespace                                                                                                                                                                                    0 items, e.g. []
PASS  items: no overlaps                                                                                                                                                                                                                  0 overlapping pairs
PASS  encoded copies: link to a MUST_MASK original and decode to it                                                                                                                                                                       200 copies; bad []
PASS  encoded copies: ~5% of injected values (5% ± 1pp)                                                                                                                                                                                   200 of 4002 injected values = 5.00%
PASS  size: 1,200 documents, dev 200 / test 1,000                                                                                                                                                                                         1200 documents, dev 200
PASS  kind share prompt: 20% ± 2pp                                                                                                                                                                                                        20.00%
PASS  split prompt: dev 1/6 ± 2pp                                                                                                                                                                                                         dev 16.67%
PASS  language share prompt/en: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share prompt/en: exactly 50%                                                                                                                                                                                                24/48 = 50.00%
PASS  language share prompt/it: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share prompt/it: exactly 50%                                                                                                                                                                                                24/48 = 50.00%
PASS  language share prompt/de: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share prompt/de: exactly 50%                                                                                                                                                                                                24/48 = 50.00%
PASS  language share prompt/fr: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share prompt/fr: exactly 50%                                                                                                                                                                                                24/48 = 50.00%
PASS  language share prompt/es: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share prompt/es: exactly 50%                                                                                                                                                                                                24/48 = 50.00%
PASS  kind share file: 20% ± 2pp                                                                                                                                                                                                          20.00%
PASS  split file: dev 1/6 ± 2pp                                                                                                                                                                                                           dev 16.67%
PASS  language file: en only                                                                                                                                                                                                              
PASS  carrier share file: 50% ± 2pp                                                                                                                                                                                                       50.00%
PASS  kind share shell: 20% ± 2pp                                                                                                                                                                                                         20.00%
PASS  split shell: dev 1/6 ± 2pp                                                                                                                                                                                                          dev 16.67%
PASS  language shell: en only                                                                                                                                                                                                             
PASS  carrier share shell: 50% ± 2pp                                                                                                                                                                                                      50.00%
PASS  kind share log: 15% ± 2pp                                                                                                                                                                                                           15.00%
PASS  split log: dev 1/6 ± 2pp                                                                                                                                                                                                            dev 16.67%
PASS  language log: en only                                                                                                                                                                                                               
PASS  carrier share log: 50% ± 2pp                                                                                                                                                                                                        50.00%
PASS  kind share tool_json: 10% ± 2pp                                                                                                                                                                                                     10.00%
PASS  split tool_json: dev 1/6 ± 2pp                                                                                                                                                                                                      dev 16.67%
PASS  language tool_json: en only                                                                                                                                                                                                         
PASS  carrier share tool_json: 50% ± 2pp                                                                                                                                                                                                  50.00%
PASS  kind share ticket: 15% ± 2pp                                                                                                                                                                                                        15.00%
PASS  split ticket: dev 1/6 ± 2pp                                                                                                                                                                                                         dev 16.67%
PASS  language share ticket/en: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share ticket/en: exactly 50%                                                                                                                                                                                                18/36 = 50.00%
PASS  language share ticket/it: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share ticket/it: exactly 50%                                                                                                                                                                                                18/36 = 50.00%
PASS  language share ticket/de: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share ticket/de: exactly 50%                                                                                                                                                                                                18/36 = 50.00%
PASS  language share ticket/fr: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share ticket/fr: exactly 50%                                                                                                                                                                                                18/36 = 50.00%
PASS  language share ticket/es: 20% ± 2pp                                                                                                                                                                                                 20.00%
PASS  carrier share ticket/es: exactly 50%                                                                                                                                                                                                18/36 = 50.00%
PASS  clean documents (dev): 20% ± 2pp                                                                                                                                                                                                    40/200 = 20.00%
PASS  clean documents (test): 20% ± 2pp                                                                                                                                                                                                   200/1000 = 20.00%
PASS  clean documents (all): 20% ± 2pp                                                                                                                                                                                                    240/1200 = 20.00%
PASS  cards: Luhn-valid                                                                                                                                                                                                                   71 checked; bad []
PASS  IBANs: mod-97 (and IT CIN, FR RIB key, ES DC) valid                                                                                                                                                                                 116 checked; bad []
PASS  national ids: valid check characters / structure                                                                                                                                                                                    34 checked; bad []
PASS  secrets: every gitleaks-drawn value matches its rule (regex, entropy, allowlists)                                                                                                                                                   639 secrets checked; bad []
PASS  email: format                                                                                                                                                                                                                       633 checked; bad []
PASS  ip: format                                                                                                                                                                                                                          485 checked; bad []
PASS  mac: format                                                                                                                                                                                                                         121 checked; bad []
PASS  phone: format                                                                                                                                                                                                                       207 checked; bad []
PASS  test split MUST_MASK secret >= 150                                                                                                                                                                                                  589
PASS  test split MUST_MASK person >= 150                                                                                                                                                                                                  1009
PASS  test split MUST_MASK email >= 150                                                                                                                                                                                                   557
PASS  test split MUST_MASK phone >= 150                                                                                                                                                                                                   170
PASS  test split MUST_MASK address >= 150                                                                                                                                                                                                 160
PASS  test split MUST_MASK ids >= 150                                                                                                                                                                                                     397
PASS  test split MUST_MASK ip >= 150                                                                                                                                                                                                      436
PASS  test split MUST_MASK mac >= 40                                                                                                                                                                                                      104
PASS  test split MUST_MASK url >= 40                                                                                                                                                                                                      60
PASS  test split: every MUST_KEEP kind >= 100                                                                                                                                                                                             19 kinds; low: {}
PASS  tool_json documents are valid JSON                                                                                                                                                                                                  bad: []
PASS  carrier excerpts: 300-6,000 characters; clean carrier docs are the verbatim excerpt                                                                                                                                                 bad []
PASS  carrier records: pinned dataset and revision; WildChat row <hash>/turn<i>; GitHub row <repo>#<number> with its url and repository SPDX licence                                                                                      bad []
PASS  carrier records: all four dataset/revision pairs are used                                                                                                                                                                           4 datasets: {'allenai/WildChat-1M': 96, 'OpenHands/openhands-feedback': 89, 'nebius/SWE-rebench-openhands-trajectories': 343, 'github-issues': 72}
PASS  canary: data/CANARY first line and README                                                                                                                                                                                           
PASS  audit rule 1: a UUID directly after a session-like key (`session`, `session_id`, `sessionId`, `sid`, `token`, `cookie`, `=` or `:`, optional quotes, case-insensitive) is AMBIGUOUS session_id, every other UUID is MUST_KEEP uuid  {'test': 20, 'dev': 3} session_id items; 0 wrong: []
PASS  audit rule 2: a base64 / URL-encoded value that decodes to a dummy credential of the SPEC AMBIGUOUS list is AMBIGUOUS dummy_credential, not a MUST_KEEP placeholder                                                                 1 encoded dummy credential item(s), 3 encoded placeholders that decode to a real placeholder stay MUST_KEEP; 0 wrong: []
PASS  determinism: a fresh build reproduces data/ab1.jsonl and stats.json byte for byte (each item was checked against the value the generator placed)                                                                                    54ee48c3248b13c1
PASS  fictional: no MUST_MASK value occurs in the carrier datasets' text (whole-token match, all four datasets, every row)                                                                                                                3924 values scanned, 95 single-token list names exempt; found: []

77/77 checks passed
```
