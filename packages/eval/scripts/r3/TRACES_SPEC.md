# traces-v3: specification for an independent coding-agent trace generator

This is the only input the generator's author receives (PROTOCOL rule change 10.2). That author is an agent with no access to this repository, to any earlier trace generator or trace set, to any training corpus or to any tuning set, and must not look for them. Everything below defines what to build. What is left open is the author's choice, and the author records each such choice in the generator's README.

## What a document is

One document is one transcript of a coding agent working in a developer's environment, as the agent sees it: the user's messages, the agent's messages, and the tool calls and tool results in between. Tool results cover:
- file reads (source code in several languages, configs, `.env` files, YAML/TOML/JSON, Dockerfiles, CI files, READMEs);
- shell sessions (commands and their output);
- `git log`, `git diff` and `git blame` output;
- stack traces and test output;
- application logs (web server, database, systemd/journal, application JSON logs);
- HTTP requests and responses;
- issue and ticket text, and code-review comments.

The plain-text rendering of a transcript is up to the author. It must be consistent within a template, and it must vary across templates. Each document is 300–20,000 characters long; the length distribution is the author's choice and is reported.

## Values: what is personal data or a secret (gold)

Each injected value has a category from this list. Its exact character offsets are recorded at the moment the value is inserted, never recovered later by search.

| Category | Examples of what to inject |
|---|---|
| `private_person` | People's names: full, given or family name; usernames and handles that name a person (`jsmith`, `@maria.rossi`); git author names |
| `private_email` | Personal and work email addresses of people |
| `private_phone` | Phone numbers in national and international formats from several countries |
| `private_address` | Postal addresses, or their parts (street with number, city, postcode), from several countries |
| `private_date` | Dates tied to a person: birth dates, hire dates, appointment dates written in a record about a person |
| `private_url` | URLs that identify a person or a private resource: personal pages, private repositories, internal hosts, URLs carrying a token or an identifier |
| `private_ip` | IPv4 and IPv6 addresses of hosts or clients, public or private ranges, except the excluded ranges in the next section |
| `private_mac` | MAC addresses |
| `account_number` | IBANs, card numbers (Luhn-valid), national ID and tax numbers of several countries (with check digits where the format has them), customer and employee numbers in a record about a person |
| `secret` | API keys and tokens in real vendor formats (cloud providers, payment, source hosting, chat, AI APIs), passwords in configs and connection strings, JWTs, private keys (PEM blocks), session cookies |
| `private_passport` | Passport numbers |
| `private_driver_license` | Driving licence numbers |
| `private_vehicle_id` | Number plates and VINs (VINs with a valid check digit) |
| `private_geolocation` | Latitude/longitude pairs tied to a person or a device |

Value sources:
- The author writes the value generators: format rules, check-digit algorithms, and name, street and city lists.
- **Faker, Mimesis and similar fake-data libraries must not be used**, and neither must any dataset or list produced for PII detection.
- Name and place lists may come from public-domain or CC0 sources (for example, national statistics offices' name frequency tables) or be written by the author. The source of each list and its licence are recorded.
- Secret formats may follow published format specifications or public secret-scanner rule definitions (by regex, not by copying their test fixtures). Every secret value is random and is not a real credential.
- At least 4 languages appear in personal-data context (names, addresses, free text in tickets and messages): English, Italian, German and French; others are allowed.

## Distractors: things that look like personal data and are not gold

The generator also inserts values that a detector may mask but that are not personal data. Their offsets go to a **sidecar** with a distractor class, and they never appear in the gold.

| Distractor class | Examples |
|---|---|
| `machine_timestamp` | Log-line and build timestamps, file modification times, ISO 8601 times in machine output |
| `public_url` | Documentation links, package registry URLs, public repositories of well-known projects, CDN and badge URLs |
| `reserved_ip` | Loopback (127.0.0.0/8, ::1), unspecified (0.0.0.0, ::), documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) |
| `placeholder` | `YOUR_API_KEY`, `<token>`, `xxx-xxx`, `user@example.com`, `changeme`, redacted or masked values (`****1234`) |
| `identifier` | Commit SHAs, checksums, UUIDs of non-personal objects, build numbers, version strings, port numbers, line numbers |
| `public_entity` | Names of companies, products, libraries and public figures mentioned as such (for example, a library's maintainer in its licence header) |

Both gold values and distractors appear in every document type, at realistic densities: at least 40% of documents contain no gold secret, and at least 15% contain no gold value at all.

## Templates and clusters

- At least 60 distinct document templates (session shapes), each with its own structure and wording. A template id is recorded per document; bootstrap resampling is done by template.
- No template accounts for more than 4% of the documents.
- The text around values (code, logs, prose) is written by the author for this generator, or taken from files under a permissive licence (MIT, Apache-2.0, BSD, CC0). Each carrier file's source and licence are recorded. Carriers must not come from npm or PyPI packages, because those were used elsewhere.

## Output

- `traces-v3.jsonl`, one document per line: `{"id", "template_id", "text", "spans": [{"start", "end", "label"}]}`, where `label` is one of the gold categories above. Offsets are Python string indices (code points).
- `traces-v3-distractors.jsonl`, one line per document: `{"id", "regions": [{"start", "end", "class"}]}`.
- 600 documents, generated by one command with a fixed seed (2026). The command and the SHA-256 of both files are printed and recorded in the README.

Invariants, checked by the generator before it writes, with a failure on any violation:
- `text[start:end]` is the injected value;
- gold spans never overlap each other or a distractor region;
- every label is valid;
- the template cap holds.

## Deliverables

- The generator code (Python 3.11+, standard library only plus any permissively licensed package, with versions pinned).
- A README: how to run it, every choice left open above, the sources and licences of lists and carriers, and summary statistics (documents per template, spans per category, distractors per class, length distribution).
- Tests for the check-digit algorithms and the invariants.

The generated text is not opened by anyone on this project before the set is frozen by SHA-256. Only the generator's own summary statistics are read.
