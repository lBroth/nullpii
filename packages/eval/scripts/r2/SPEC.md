Spec written by the nullpii maintainers; generator written independently from this spec only.

SPECIFICATION (the dataset):
Purpose: text that a coding agent (an LLM working in a developer's repository) reads as tool output, with personal data and secrets planted at known character offsets, to measure how much of it a masking tool catches and how much non-sensitive text it masks.

Output format: JSON Lines, one document per line: {"id": "tv2:<n>", "kind": <document kind>, "template": <template cluster id string, the same for documents built from the same template/skeleton>, "lang": <"en"|"de"|"fr"|"it"|"es">, "text": <string>, "spans": [{"start": int, "end": int, "label": <label>}]} — offsets are Python string indices (code points), end exclusive, spans sorted, non-overlapping, and text[start:end] must equal the planted value exactly (assert this for every span in the generator).

Size: 600 documents. About 10% are long (20,000–60,000 characters, built by concatenating several sections), the rest 300–6,000 characters. Languages: about 50% en, and roughly equal shares of de, fr, it, es for prose, comments and values (code keywords stay in their language).

Document kinds (spread roughly evenly, design your OWN templates; at least 40 distinct template skeletons in total, each used several times with different values):
- source code files in several languages (Python, TypeScript/JavaScript, Go, Java, Ruby, PHP, shell) with comments, fixtures, test data, config constants;
- configuration files (.env, YAML, TOML, INI, JSON, Dockerfile, docker-compose, Kubernetes manifests, CI pipeline files);
- application and server logs (web server access logs, application logs with levels, audit logs, cron/job logs);
- stack traces and error reports from several runtimes;
- shell sessions (commands and their output: curl, psql/mysql, kubectl, git log, ssh, ls);
- data exports (CSV, SQL dumps / INSERT statements, JSON API responses, XML);
- markdown documents (README sections, incident reports, meeting notes, support tickets, changelogs);
- emails or chat transcripts pasted into a terminal.

Labels (only these 14; label every occurrence of these kinds of values that you plant; do not plant labelled values inside other labelled values):
- private_person: a natural person's name (given name, family name, or full name; also a personal username/handle that identifies a person).
- private_email: an email address of a person or a mailbox.
- private_phone: a telephone number.
- private_address: a postal address. Label each address as ONE span from its first to its last character (street, number, postcode, city, region and country together when they appear together as one address).
- private_date: a date tied to a person (birth date, appointment, hire or leave date, a person's event). Machine timestamps (log line timestamps, build times, file modification times, commit dates) are NOT labelled.
- private_url: a URL that identifies a person or exposes non-public resources (internal hosts, URLs with user identifiers, tokens or private repository paths). URLs of public documentation, public package registries and public project homepages are NOT labelled.
- private_ip: an IPv4 or IPv6 address of a host (loopback 127.0.0.1/::1 and 0.0.0.0 are not labelled).
- private_mac: a MAC address.
- account_number: bank account numbers, IBANs, payment card numbers, national identification and social security numbers, tax numbers, health insurance numbers, cryptocurrency wallet addresses.
- secret: credentials — passwords, API keys, access tokens, private keys, signing secrets, connection-string passwords, session cookies.
- private_passport: a passport number.
- private_driver_license: a driving licence number.
- private_vehicle_id: a vehicle registration plate or VIN.
- private_geolocation: geographic coordinates of a person's location (latitude/longitude pairs).

Unlabelled distractors (plant plenty, never label them): UUIDs, commit hashes and content digests, version strings, build numbers, port numbers, HTTP status codes, file paths, function and variable names, public URLs, product and company names, timestamps of machine events, random request/trace identifiers, numeric metrics, locale codes, time zone names, cloud region names, example placeholders like <YOUR_API_KEY> or ${DB_PASSWORD} (placeholders are not secrets).

Value design: invent your own formats and pools. Secrets should cover many credential styles you design yourself (vendor-style prefixed tokens of your own invention, JWT-shaped tokens, PEM private key blocks, hex and base64 strings, passwords of varying complexity, database URLs with passwords where only the password is labelled). Names should cover the five languages and include multi-part names. Mix formats for phones, dates (several notations), addresses (per-country formats), and identifiers (per-country formats with valid check digits where the format has one).

Density: on average one labelled span per 300–600 characters; some documents with no labelled span at all (about 10%).

Self-checks the generator must run before writing (fail loudly if any fails): every span's text equals the planted value; spans do not overlap; every label is one of the 14; template ids cover at least 40 skeletons; document count and length distribution as specified.
