# traces-v3 generator

Synthetic coding-agent transcripts with character-exact annotations of personal data and secrets (gold), plus a sidecar of look-alike values that are not personal data (distractors). Built from `SPEC.md` only.

## Running it

Requirements: CPython 3.11 or newer (developed and run with 3.12.13). Standard library only — no third-party package, no virtual environment needed.

```bash
python3.12 -m unittest discover -s tests -v      # check digits, segment model, invariants, end-to-end
python3.12 generate.py                            # seed 2026, 600 documents
python3.12 generate.py --update-readme            # same, and refresh the statistics block below
```

`generate.py` writes, next to itself:

- `traces-v3.jsonl` — one document per line: `{"id", "template_id", "text", "spans": [{"start", "end", "label"}]}`
- `traces-v3-distractors.jsonl` — one line per document, same order: `{"id", "regions": [{"start", "end", "class"}]}`
- `traces-v3-meta.jsonl` — one line per document, same order: `{"id", "template_id", "conversation_language"}`, the ISO 639-1 code (en/it/de/fr/es) of the transcript's conversation language; added after the set was frozen, as a separate file that does not change the other two
- `traces-v3-stats.json` — the summary statistics reproduced below (no document text)

and prints the command and the SHA-256 of the JSONL files. Offsets are Python string indices (code points). Files are UTF-8, `\n`-terminated, one `json.dumps(..., ensure_ascii=False)` object per line.

Other options: `--seed`, `--n`, `--out`. Two developer tools use separate development seeds and were never run with the release seed: `devrun.py` renders a few documents of chosen templates (or smoke-tests every template in every mode and language with `--all`) with tagged values marked inline, and `qa_untagged.py` scans text outside every span and region for e-mail, IP, MAC, IBAN, card, phone, JWT, vendor-key, PEM and name patterns that a template might have left untagged.

Files:

| path | content |
|---|---|
| `generate.py` | command-line entry point, file writing, re-verification, SHA-256 |
| `tracegen/core.py` | segment model, fragment helpers (`T`, `lines`, `table`, `grid`, `prefix_lines`, JSON escaping), assembly, per-document invariant check |
| `tracegen/doc.py` | document builder, gold provider `d.g`, distractor provider `d.x`, generation modes |
| `tracegen/values.py`, `tracegen/checkdigits.py` | value generators and check-digit algorithms |
| `tracegen/distract.py` | clock, timestamp formats, identifiers, reserved IPs, placeholders |
| `tracegen/lists.py` | name, street, city, company, public-entity and public-URL lists |
| `tracegen/styles.py` | the 13 transcript renderings |
| `tracegen/phrases.py` | shared localized phrases (en/it/de/fr/es) |
| `tracegen/templates/t_*.py` | the 81 templates |
| `tracegen/build.py` | template allocation, mode assignment, corpus-level invariants |
| `tracegen/stats.py` | summary statistics |
| `tests/` | check digits, segment model and invariants, end-to-end tests |

## How it works

- **Segments, not search.** A document is built as a list of segments (`tracegen/core.py`). A gold value or a distractor is a tagged segment created at the moment the template inserts it; offsets are fixed when the segments are concatenated, so no offset is ever recovered by searching the text. Rendering transforms (line prefixes of a transcript style, JSON escaping inside JSON-lines transcripts) are applied segment by segment and keep the tags; when such a transform has to touch the inside of a multi-line value (a PEM block under an indented tool result), the inserted value is the transformed text and the span covers it.
- **Invariants, checked before writing** (`core.check_document`, `build.check_corpus`): `text[start:end]` equals the inserted value for every span and region; gold spans overlap neither each other nor any distractor region; every label/class is valid; every document is 300–20,000 characters; no template exceeds 4% of the documents; at least 60 templates are used; at least 40% of documents have no gold secret and at least 15% have no gold at all; ids are unique; documents generated without gold contain none and documents generated without secrets contain no gold secret. After writing, `generate.py` re-reads both files and re-checks offsets, labels and overlaps on the serialized data. Any violation raises and nothing is reported as success.
- **Templates** (`tracegen/templates/t_*.py`) are functions that emit one session through a style object: `d.user(...)`, `d.agent(...)`, `d.tool(tool, argument, output)`. Every personal value goes through the gold provider `d.g` and every look-alike through the distractor provider `d.x`.
- **Values** (`tracegen/values.py`, `tracegen/checkdigits.py`) are generated from format rules written for this generator; check digits are computed (Luhn; IBAN ISO 7064 MOD 97-10 plus the Italian CIN, French RIB key, Spanish DC, Dutch 11-proof, Belgian and Portuguese national checks; Italian codice fiscale; German Steuer-IdNr ISO 7064 MOD 11,10 with the digit-distribution rule; French NIR key; Spanish DNI/NIE letter; Dutch BSN 11-proof; Polish PESEL; Portuguese NIF; Swiss AHV EAN-13; VIN position-9 check digit; ICAO 9303 for MRZ data). Every secret is random in a published vendor format; none is a real credential.
- **Determinism.** One `random.Random` per document, seeded from the string `"{seed}:{doc_id}:{template_id}:{attempt}"`; no set iteration, clock or environment read influences the output (verified by running with different `PYTHONHASHSEED` values).

## Choices left open by the specification

**Transcript rendering.** 13 plain-text styles (`tracegen/styles.py`), each template bound to exactly one, so a template is internally consistent and styles vary across templates: `cc` (bulleted terminal transcript with `⎿`-indented tool output and a session box), `xml` (`<user>`, `<assistant>`, `<tool_call>`, `<tool_result>`), `md` (Markdown headings with fenced output), `colon` (`USER:` / `AGENT:` / `CALL` / `OUTPUT:` with indented output), `jsonl` (one JSON event per line, every string JSON-escaped), `tslog` (time-stamped `you>` / `agent>` lines), `box` (box-drawing frames), `hai` (`Human:` / `Assistant:` with `[output]` blocks), `irc` (`<nick>` lines; the nick is the developer's username), `react` (`Task/Thought/Action/Observation`), `steps` (numbered `--- step N ---` blocks), `aider` (`####` prompts and `> /run` commands), `plain` (role lines and `$` commands with a rule after output). Tool names differ per style (e.g. `Bash`/`run_shell`/`exec_command`/`Shell`).

**Templates.** 81 templates; one template is one session shape with its own tool sequence, carriers and wording (for example: a failing deploy workflow, a rebase conflict, a pytest failure with locals, a postfix bounce analysis, a GraphQL customer query, a DSAR erasure ticket, an airline booking import). Inside a template, alternative root causes, optional steps and random row/line counts make documents differ. Every template is tagged with the document types of the specification it covers (`file`, `shell`, `git`, `trace`, `log`, `http`, `ticket`); the per-type counts are below. Documents are spread evenly: 600 = templates × ⌊600/templates⌋ plus one extra document for a random subset of templates, then shuffled (7 or 8 documents per template, 1.33% maximum share).

**Gold density.** Each document gets a generation mode, assigned by exact counts: 20% *clean* (no gold value at all — every personal slot is filled with its non-personal stand-in: placeholders, reserved IPs, bot identities, generic paths), 31% *no-secret* (personal data but every secret slot gets a placeholder such as `changeme`, `${DB_PASSWORD}`, `****`), 49% *full*. Clean documents are drawn by weighted sampling without replacement: the 24 templates whose substance is a set of records about people (`build.RECORD_TEMPLATES`: customer dumps, HR and payroll files, KYC and booking payloads, fleet and device inventories, support tickets) get weight 0.3, all others 1.0, because an all-placeholder customer table is less realistic than an all-placeholder config or log. No-secret documents are drawn uniformly from the rest. Full documents can still lack a secret when their branch has no secret slot, so the realized shares are reported below. Within a document the number of values follows the carrier (a one-host SSH question has a handful, a customer dump or telematics log hundreds).

**Distractor density.** Distractors are what each carrier naturally contains: every machine timestamp, SHA, UUID, version, port, request id, documentation/registry URL, reserved IP and placeholder that a template inserts is tagged; incidental numbers in the carrier text are not. Machine timestamps come from a per-document clock that starts between January 2025 and October 2026 and moves forward through the session (log excerpts read during the session may lie before it).

**Length.** No target distribution; lengths follow from each template's structure and random counts. A document outside 300–20,000 characters is regenerated with the next attempt number (counts reported below).

**Languages.** Conversation language per document, drawn with weights en 44%, it 17%, de 15%, fr 15%, es 9%: user turns are written in that language for every template, agent turns in that language through a shared phrase bank and per-template text (Spanish falls back to English for some agent sentences). Text authored by people inside the transcript (tickets, e-mails, review comments, chat) is written in the author persona's language. Persona locales: en_US, en_GB, it_IT, de_DE, fr_FR, es_ES, nl_NL, pt_PT, pl_PL; a document's default locale follows its language 75% of the time, and each additional person keeps that locale with probability 0.6.

**Annotation conventions (span boundaries).**
- `private_person`: full names, given or family names alone, usernames and handles that name a person (a handle span includes the `@`), usernames inside home paths (`/Users/<name>/…`), shell prompts, IAM user names, git author names, airline-format names (`FAMILY/GIVEN`). Generic service accounts (`deploy`, `ubuntu`, `postgres`, `app`) and team handles (`@org/platform-team`) are not tagged. In clean documents git identities become bot accounts (`dependabot[bot]` …, tagged `public_entity`).
- `private_address`: a one-line address is one span; in structured records (JSON fields, CSV columns, XML elements) street, postcode and city are separate spans.
- `private_date`: dates tied to a person (birth, hire and start dates, appointment, accident, document expiry, permit validity, travel dates inside a booking record). Machine times (log lines, file times, commit dates, HTTP `Date`, record creation stamps) are `machine_timestamp` distractors.
- `private_url`: full URLs on internal hosts, private repositories, personal pages, share/reset/invite links, pre-signed URLs and links to records about a person. When a URL embeds credentials (`https://user:token@host/path`), the user name and the token get their own spans (`private_person`, `secret`) and the `host/path` remainder is a `private_url` span; the scheme and separators are untagged. Bare host names are not tagged.
- `secret`: the whole token (JWT including header and signature; PEM block from `-----BEGIN` to `-----END …-----`; Slack webhook and Sentry DSN as whole URLs; Kubernetes `data:` values in their base64 form; session cookie values; OAuth authorization codes). In connection strings only the password is tagged. Public SSH key bodies, key fingerprints and hashed `known_hosts` entries are `identifier` distractors.
- `private_geolocation`: a latitude/longitude pair written together is one span (also in degrees-minutes-seconds form); separate fields (`lat=…`, `"lon": …`, CSV columns) are two spans.
- `account_number`: IBANs (electronic or grouped; also an employer's own debtor IBAN in a payroll file), card numbers (Luhn-valid), national ID and tax numbers, customer, employee and frequent-flyer numbers in records about a person. One customer/employee numbering scheme per document. BICs are `identifier` distractors.
- `private_ip`: IPv4/IPv6 of hosts or clients in private or public ranges, including network addresses of routes and VPN allowed-IP lists (the `/prefix` suffix is outside the span). Loopback, unspecified and documentation ranges are always distractors; link-local, CGNAT, multicast, benchmark ranges and well-known public resolvers are never generated.
- Values are tagged as they appear in the carrier: a name escaped as `\'` inside a SQL dump, an e-mail written `NAME//DOMAIN` in an airline record or a phone number reduced to digits are the gold text there.
- Rendering artefacts (role labels, line-number gutters of file reads, step counters) are not tagged; line numbers that are part of tool output (stack traces, `grep -n`, compiler errors) are `identifier` distractors.
- Fictional employer names and their domains are not tagged (they are neither personal data nor public entities); e-mail addresses of people on those domains are gold. Role and list mailboxes (`support@`, `noreply@`, `alerts@`, `dmarc@`, project mailing lists) are neither gold nor distractors and stay untagged.

**Distractor classes** follow the specification table. `placeholder` includes conventional example identities (`John Doe`, `Max Mustermann`, `Mario Rossi`, `Jean Dupont`), `example.com` addresses, fictional phone ranges (`555-01xx`, Ofcom drama numbers), masked values, template variables (`${…}`, `{{ … }}`), and vendor documentation examples (`AKIAIOSFODNN7EXAMPLE`, test card `4242 4242 4242 4242`). `public_entity` covers products, libraries, companies and public figures named as such in prose or credits; library names inside code are not tagged.

## Sources and licences

- **Name lists, street lists, cities, words**: written by the author of this generator from general knowledge (common given and family names per locale, generic street names, real city names). No list was downloaded, no PII-detection dataset or fake-data library (Faker, Mimesis or similar) was used.
- **Public facts used in formats**: city coordinates (rounded), postcode ranges, telephone dialling and mobile prefixes, Italian cadastral (Belfiore) codes, vehicle manufacturer identifiers (WMI), airline and airport codes, national ID and IBAN structures, vendor secret prefixes and lengths (as published by the vendors and by public secret-scanner rule definitions — formats only, no test fixture copied) — written from the public format definitions, not copied from any file.
- **Real public names used as such**: public mailbox providers and their MX host names (personal addresses are built on them), documentation/registry/CDN/badge URLs of well-known projects, vendor documentation example values used as placeholders (`AKIAIOSFODNN7EXAMPLE`, `4242 4242 4242 4242`, the `RSSMRA80A01H501U` codice fiscale example).
- **Companies** (`lists.COMPANIES`) are invented; any resemblance to a real organisation is accidental. **Public entities and figures** are real products, organisations and well-known people, used only as such.
- **Carrier text** (source code, configs, logs, HTTP exchanges, tickets, e-mails, prose in five languages) is written by the author for this generator. No file was taken from npm, PyPI or any other package or repository, so there is no third-party carrier to license.

## Summary statistics

<!-- STATS:BEGIN -->

Command: `python3.12 generate.py --seed 2026 --n 600`

| file | SHA-256 |
|---|---|
| `traces-v3.jsonl` | `c01579395fd26816cd1873f1503f71afabc6f78b8431a71a3bce15e3945daabc` |
| `traces-v3-distractors.jsonl` | `f733897e29b3054bdbe37409e73ef8fe0cf40f6a49eeff7c6f625d6631c118ae` |
| `traces-v3-meta.jsonl` | `626c73de4b5d57ea58a7c8a69d9b2e8ba540b9292e7baff7663c9ea1ff9a994e` |

Documents: **600**, templates: **81**, largest template share: **1.33%** (cap 4%).

Documents without a gold secret: **457** (76.2%); without any gold value: **120** (20.0%). Generation modes: clean 120, full 294, no_secret 186.

### Spans per gold category

| category | spans | documents |
|---|---:|---:|
| `private_person` | 4647 | 449 |
| `private_email` | 2653 | 393 |
| `private_phone` | 809 | 206 |
| `private_address` | 1520 | 140 |
| `private_date` | 818 | 120 |
| `private_url` | 413 | 128 |
| `private_ip` | 2655 | 237 |
| `private_mac` | 251 | 39 |
| `account_number` | 1388 | 177 |
| `secret` | 584 | 143 |
| `private_passport` | 91 | 24 |
| `private_driver_license` | 149 | 22 |
| `private_vehicle_id` | 585 | 36 |
| `private_geolocation` | 644 | 41 |
| **total** | **17207** | |

Gold spans per document: median 19, mean 28.68, max 471.

### Distractors per class

| class | regions | documents |
|---|---:|---:|
| `machine_timestamp` | 7172 | 503 |
| `public_url` | 386 | 177 |
| `reserved_ip` | 767 | 120 |
| `placeholder` | 3176 | 305 |
| `identifier` | 9641 | 580 |
| `public_entity` | 259 | 104 |
| **total** | **21401** | |

Distractor regions per document: median 24, mean 35.67, max 366.

### Length distribution (characters)

| min | p10 | p25 | median | p75 | p90 | max | mean |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 354 | 2522 | 3175 | 4208 | 5454 | 7681 | 17194 | 4709 |

| bucket | documents |
|---|---:|
| 300-999 | 6 |
| 1000-1999 | 16 |
| 2000-3999 | 239 |
| 4000-7999 | 287 |
| 8000-11999 | 39 |
| 12000-15999 | 12 |
| 16000-20000 | 1 |

### Languages

Conversation language (user and agent turns): de 97, en 259, es 51, fr 101, it 92.

Documents containing free text in each language (user/agent turns, tickets, e-mails, reviews): de 98, en 287, es 58, fr 103, it 97, nl 4.

Documents containing personal data from each persona locale: de_DE 127, en_GB 140, en_US 145, es_ES 106, fr_FR 129, it_IT 132, nl_NL 85, pl_PL 82, pt_PT 69.

### Document types

| type | templates | documents |
|---|---:|---:|
| file | 38 | 285 |
| git | 11 | 82 |
| http | 12 | 89 |
| log | 22 | 157 |
| shell | 28 | 206 |
| ticket | 10 | 76 |
| trace | 19 | 141 |

### Documents per template

| template | style | types | documents |
|---|---|---|---:|
| `alpr_parking_events` | plain | log, file | 8 |
| `android_crash_location` | xml | trace, log | 7 |
| `ansible_inventory_vault` | irc | file | 7 |
| `audit_log_admin_actions` | react | log | 7 |
| `aws_cli_keys` | colon | shell | 7 |
| `clinic_appointment_bug` | colon | ticket, file, trace | 7 |
| `cron_systemd_backup` | box | shell, log | 7 |
| `csv_customer_import` | irc | file, trace | 7 |
| `curl_verbose_profile` | cc | http, shell | 7 |
| `dhcp_leases_mac` | hai | log, file | 7 |
| `django_settings_admins` | md | file, trace | 8 |
| `docker_logs_container` | plain | shell, log | 7 |
| `dockerfile_build_args` | jsonl | file, shell | 8 |
| `dotnet_appsettings_test` | aider | trace, file | 8 |
| `env_db_connect` | cc | file, shell | 8 |
| `fleet_telematics` | irc | log, file | 8 |
| `gdpr_dsar_deletion` | md | ticket, shell | 8 |
| `gha_deploy_failure` | colon | file, log | 7 |
| `git_bisect_session` | plain | git, trace | 7 |
| `git_blame_regression` | steps | git, file | 7 |
| `git_diff_staged_secret` | aider | git | 8 |
| `git_filter_repo_purge` | tslog | git, shell | 7 |
| `git_format_patch_email` | box | git | 8 |
| `git_log_changelog` | react | git | 7 |
| `git_rebase_conflict` | xml | git, file | 8 |
| `git_remote_push_auth` | md | git, shell | 8 |
| `git_shortlog_mailmap` | cc | git, file | 7 |
| `git_show_commit_metadata` | colon | git | 7 |
| `github_issue_bug_report` | steps | ticket, trace | 8 |
| `go_panic_request` | react | trace | 7 |
| `graphql_customer_query` | colon | http | 8 |
| `har_cookie_analysis` | md | http, file | 8 |
| `home_disk_cleanup` | aider | shell | 8 |
| `hr_onboarding_accounts` | xml | ticket, shell | 7 |
| `httpie_booking_api` | steps | http | 7 |
| `insurance_claim_parser` | hai | file, ticket | 7 |
| `iot_device_registry` | aider | file, log | 8 |
| `ip_addr_network_debug` | steps | shell | 7 |
| `java_spring_exception_mdc` | irc | trace, log | 7 |
| `jest_snapshot_user` | hai | trace | 7 |
| `jira_refund_ticket` | aider | ticket, file | 8 |
| `json_logs_jq` | box | log, shell | 7 |
| `k8s_events_ingress` | cc | log | 7 |
| `k8s_manifests` | xml | file, shell | 8 |
| `kubectl_pod_debug` | cc | shell, log | 7 |
| `kyc_api_integration` | tslog | http, file | 7 |
| `mail_server_bounce` | steps | log | 7 |
| `mdm_device_inventory` | aider | shell, file | 8 |
| `mysql_dump_restore` | hai | shell, file | 7 |
| `nginx_access_top_ips` | colon | log, shell | 7 |
| `npm_publish_auth` | jsonl | shell, file | 7 |
| `oauth_callback_debug` | jsonl | http, log | 7 |
| `pandas_notebook_cleaning` | box | file, trace | 8 |
| `payroll_sepa_xml` | tslog | file, ticket | 8 |
| `php_laravel_log` | plain | trace, log, file | 7 |
| `postgres_slow_query_log` | jsonl | log | 7 |
| `postman_collection_env` | irc | http, file | 8 |
| `pr_review_thread` | jsonl | ticket, git | 8 |
| `psql_user_lookup` | xml | shell | 7 |
| `pytest_showlocals` | box | trace | 8 |
| `python_celery_retry` | colon | trace, log | 7 |
| `readme_maintainers` | box | file | 8 |
| `redis_sessions` | md | shell | 8 |
| `rest_client_pagination` | box | http, shell | 8 |
| `rspec_factory_failure` | steps | trace | 8 |
| `rust_cargo_build` | cc | trace, file | 8 |
| `secret_scanner_triage` | jsonl | shell, file | 7 |
| `sentry_issue_event` | md | trace, http | 7 |
| `shell_history_audit` | tslog | shell | 8 |
| `slack_incident_thread` | cc | ticket, log | 7 |
| `soap_xml_insurance` | react | http, file | 8 |
| `spring_application_yml` | react | file, trace | 8 |
| `ssh_config_hosts` | hai | file, shell | 7 |
| `ssh_keygen_deploy_key` | irc | shell, file | 7 |
| `sshd_auth_journal` | tslog | log, shell | 7 |
| `stripe_webhook_debug` | xml | http, file | 7 |
| `support_email_thread` | plain | ticket | 8 |
| `terraform_tfvars` | tslog | file, shell | 7 |
| `travel_booking_pnr` | react | file, trace | 7 |
| `vpn_access_log` | plain | log | 7 |
| `webhook_signature_slack` | hai | http, file | 7 |

Length retries (attempts needed to land in 300–20,000 chars): 1: 600.

<!-- STATS:END -->
