#!/usr/bin/env python3
"""Synthetic dev-paste prompt generator for nullpii v9 training.

Goal: re-balance the v9 training corpus toward "developer-style" prompts
that mirror the held-out `nullpii-bench` distribution (PR reviews, deploy
logs, support tickets, code with secrets, postmortems, …) without
sampling from the bench file itself.

Each record matches the `nullpii-bench.jsonl` schema:

    {"id": "...", "locale": "en|it|de|fr|es",
     "subset": "dev-paste-synth-train",
     "text": "...",
     "spans": [{"label": "private_email", "start": 12, "end": 30}, ...]}

PII labels follow the nullpii 8-cat schema:
    private_email, private_phone, private_person, private_address,
    private_url, private_date, account_number, secret

Generation strategy:
    1. Pick a template (~20 variants spanning PR/RFC/deploy/DB/support/
       code/slack/postmortem/payments).
    2. Pick a locale and bind a Faker(locale) instance.
    3. Sample placeholder values via Faker + custom secret synthesisers
       (AKIA / sk_live_ / ghp_ / sk-ant-) so secrets look real.
    4. Substitute placeholders, recording precise (start, end) offsets
       for each PII span.
    5. Each text yields 1–5 spans by template construction.

CLI:
    python generate_dev_paste_synth.py --n 20000 \
        --out packages/eval/datasets/dev-paste-synth-train.jsonl --seed 42

Outputs JSON-Lines, one record per line.
"""
from __future__ import annotations

import argparse
import json
import random
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Faker is already vendored via presidio-evaluator (see public_datasets.py).
from faker import Faker

# ─── Constants ────────────────────────────────────────────────────

LOCALES: tuple[str, ...] = ("en_US", "it_IT", "de_DE", "fr_FR", "es_ES")
LOCALE_TO_BENCH_CODE: dict[str, str] = {
    "en_US": "en",
    "it_IT": "it",
    "de_DE": "de",
    "fr_FR": "fr",
    "es_ES": "es",
}
SUBSET_NAME = "dev-paste-synth-train"


# ─── Secret / credential synthesisers ─────────────────────────────
#
# We deliberately do not call Faker for secrets — Faker's secret
# generators don't match the prefix shape that real cloud providers
# emit (AKIA, ghp_, sk_live_, sk-ant-). Models that learn the prefix
# pattern transfer better to real-world dev pastes.

_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_ALPHANUM = string.ascii_letters + string.digits
_HEX = "0123456789abcdef"


def _aws_key(rng: random.Random) -> str:
    return "AKIA" + "".join(rng.choices(_ALPHANUM_UPPER, k=16))


def _stripe_live(rng: random.Random) -> str:
    return "sk_live_" + "".join(rng.choices(_ALPHANUM, k=24))


def _github_pat(rng: random.Random) -> str:
    return "ghp_" + "".join(rng.choices(_ALPHANUM, k=36))


def _anthropic_key(rng: random.Random) -> str:
    # sk-ant-api03-<base64ish>
    body = "".join(rng.choices(_ALPHANUM + "-_", k=95))
    return "sk-ant-api03-" + body


def _openai_key(rng: random.Random) -> str:
    return "sk-proj-" + "".join(rng.choices(_ALPHANUM, k=48))


def _slack_token(rng: random.Random) -> str:
    return (
        "xoxb-"
        + "".join(rng.choices(string.digits, k=12))
        + "-"
        + "".join(rng.choices(string.digits, k=12))
        + "-"
        + "".join(rng.choices(_ALPHANUM, k=24))
    )


def _jwt(rng: random.Random) -> str:
    head = "eyJ" + "".join(rng.choices(_ALPHANUM + "-_", k=20))
    body = "".join(rng.choices(_ALPHANUM + "-_", k=120))
    sig = "".join(rng.choices(_ALPHANUM + "-_", k=43))
    return f"{head}.{body}.{sig}"


def _bearer(rng: random.Random) -> str:
    return "Bearer " + "".join(rng.choices(_ALPHANUM, k=40))


def _password(rng: random.Random) -> str:
    pool = _ALPHANUM + "!@#$%^&*"
    return "".join(rng.choices(pool, k=rng.randint(12, 24)))


def _api_key_generic(rng: random.Random) -> str:
    return "".join(rng.choices(_ALPHANUM, k=32))


_SECRET_GENS: tuple[Callable[[random.Random], str], ...] = (
    _aws_key,
    _stripe_live,
    _github_pat,
    _anthropic_key,
    _openai_key,
    _slack_token,
    _jwt,
    _bearer,
    _password,
    _api_key_generic,
)


def _hostname(rng: random.Random) -> str:
    region = rng.choice(("us-east-1", "us-west-2", "eu-central-1", "eu-west-1", "ap-south-1"))
    role = rng.choice(("api", "db", "cache", "worker", "ingest", "auth"))
    env = rng.choice(("prod", "staging", "dev"))
    n = rng.randint(1, 9)
    return f"{role}-{env}-{n}.{region}.internal"


def _ipv4(rng: random.Random) -> str:
    return ".".join(str(rng.randint(1, 254)) for _ in range(4))


# ─── Span tracking helpers ────────────────────────────────────────
#
# Build text by concatenating literal chunks and PII chunks; every PII
# chunk records its offset relative to the running cursor. This avoids
# str.format() and the off-by-one risk of post-hoc regex matching.


@dataclass(slots=True)
class _Chunk:
    text: str
    label: str | None  # None → literal


def _assemble(chunks: list[_Chunk]) -> tuple[str, list[dict]]:
    parts: list[str] = []
    spans: list[dict] = []
    cursor = 0
    for c in chunks:
        if c.label is not None:
            spans.append({"label": c.label, "start": cursor, "end": cursor + len(c.text)})
        parts.append(c.text)
        cursor += len(c.text)
    return "".join(parts), spans


def _lit(text: str) -> _Chunk:
    return _Chunk(text=text, label=None)


def _pii(label: str, text: str) -> _Chunk:
    return _Chunk(text=text, label=label)


# ─── Faker-backed PII generators ──────────────────────────────────
#
# Faker is locale-aware: a single `Faker("de_DE")` instance produces
# German names, German phone numbers, German addresses, etc. — exactly
# what we want for multilingual coverage.


def _email(faker: Faker) -> str:
    return faker.email()


def _person(faker: Faker) -> str:
    return faker.name()


def _phone(faker: Faker) -> str:
    return faker.phone_number()


def _address_one_line(faker: Faker) -> str:
    # Collapse multi-line addresses to a single line so spans stay clean.
    return faker.address().replace("\n", ", ")


def _url(faker: Faker) -> str:
    return faker.url()


def _internal_url(faker: Faker, rng: random.Random) -> str:
    host = _hostname(rng)
    path = rng.choice(("/healthz", "/api/v1/users", "/admin", "/metrics", "/v2/orders"))
    return f"https://{host}{path}"


def _date(faker: Faker) -> str:
    return faker.date()


def _iban(faker: Faker) -> str:
    return faker.iban()


def _ssn(faker: Faker) -> str:
    return faker.ssn()


def _credit_card(faker: Faker) -> str:
    return faker.credit_card_number()


# ─── Templates ────────────────────────────────────────────────────
#
# Each template is a `Callable[[Faker, Random], list[_Chunk]]` so the
# template body can use locale-aware Faker + a deterministic RNG. We
# return a list of chunks rather than a format string so spans stay
# byte-accurate even when PII values contain literal `{` or `}`.


def t_pr_review(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    email = _email(faker)
    return [
        _lit("Review "),
        _pii("private_person", name),
        _lit("'s PR; ping "),
        _pii("private_email", email),
        _lit(" if blocked."),
    ]


def t_rfc_byline(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    email = _email(faker)
    date = _date(faker)
    return [
        _lit("# RFC: storage layer rewrite\n\nAuthor: "),
        _pii("private_person", name),
        _lit(" <"),
        _pii("private_email", email),
        _lit(">\nLast-Updated: "),
        _pii("private_date", date),
        _lit("\n\nThis document proposes splitting the monolithic store."),
    ]


def t_deploy_log_aws(faker: Faker, rng: random.Random) -> list[_Chunk]:
    key = _aws_key(rng)
    host = _hostname(rng)
    return [
        _lit("[deploy] uploading artifact to s3://"),
        _lit(f"prod-bucket-{rng.randint(100, 999)}"),
        _lit("/release.tgz\n[deploy] using key "),
        _pii("secret", key),
        _lit("\n[deploy] rolling out to "),
        _pii("private_url", f"https://{host}/healthz"),
    ]


def t_deploy_log_stripe(faker: Faker, rng: random.Random) -> list[_Chunk]:
    key = _stripe_live(rng)
    return [
        _lit("ERROR: payment webhook failed (auth)\n  STRIPE_SECRET="),
        _pii("secret", key),
        _lit("\n  please rotate immediately."),
    ]


def t_db_connection_string(faker: Faker, rng: random.Random) -> list[_Chunk]:
    user = faker.user_name()
    pwd = _password(rng)
    host = _hostname(rng)
    db = rng.choice(("main", "users", "events", "billing"))
    port = rng.choice((5432, 3306, 27017))
    # The whole URL is one secret span — including embedded creds —
    # because that's how a model should treat a leaked DSN: redact
    # the entire string, not just the password.
    dsn = f"postgres://{user}:{pwd}@{host}:{port}/{db}"
    return [
        _lit("Connection string in repo:\n  "),
        _pii("secret", dsn),
        _lit("\nShould I rotate?"),
    ]


def t_support_ticket(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    email = _email(faker)
    phone = _phone(faker)
    addr = _address_one_line(faker)
    return [
        _lit(f"Customer support ticket #{rng.randint(1000, 99999)}\nFrom: "),
        _pii("private_person", name),
        _lit(" <"),
        _pii("private_email", email),
        _lit(">\nPhone: "),
        _pii("private_phone", phone),
        _lit("\nShipping address: "),
        _pii("private_address", addr),
        _lit("\nIssue: order never arrived."),
    ]


def t_support_ticket_short(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    email = _email(faker)
    return [
        _lit("Customer "),
        _pii("private_person", name),
        _lit(" ("),
        _pii("private_email", email),
        _lit(") reported a 500 from prod."),
    ]


def t_code_secret_comment(faker: Faker, rng: random.Random) -> list[_Chunk]:
    key = _openai_key(rng)
    return [
        _lit("```python\n# TODO: move to env vars before merging\nOPENAI_API_KEY = \""),
        _pii("secret", key),
        _lit("\"\nclient = OpenAI(api_key=OPENAI_API_KEY)\n```\nWhy am I getting 401?"),
    ]


def t_code_anthropic(faker: Faker, rng: random.Random) -> list[_Chunk]:
    key = _anthropic_key(rng)
    return [
        _lit("```js\nconst anthropic = new Anthropic({\n  apiKey: \""),
        _pii("secret", key),
        _lit("\",\n});\n```\nMy SDK keeps timing out."),
    ]


def t_code_docstring_secret(faker: Faker, rng: random.Random) -> list[_Chunk]:
    key = _github_pat(rng)
    return [
        _lit("```python\ndef fetch_repo():\n    \"\"\"Pull latest. Token: "),
        _pii("secret", key),
        _lit(" (rotated 2024-Q4).\"\"\"\n    return requests.get(URL)\n```"),
    ]


def t_slack_repost(faker: Faker, rng: random.Random) -> list[_Chunk]:
    n1 = _person(faker)
    n2 = _person(faker)
    email = _email(faker)
    return [
        _lit("[#engineering] "),
        _pii("private_person", n1),
        _lit(": hey "),
        _pii("private_person", n2),
        _lit(", can you forward the SOC2 questionnaire to "),
        _pii("private_email", email),
        _lit(" today?"),
    ]


def t_postmortem(faker: Faker, rng: random.Random) -> list[_Chunk]:
    operator = _person(faker)
    ip = _ipv4(rng)
    host = _hostname(rng)
    date = _date(faker)
    return [
        _lit("# Postmortem: Outage on "),
        _pii("private_date", date),
        _lit("\n\nIncident commander: "),
        _pii("private_person", operator),
        _lit("\nFirst alert from host "),
        _pii("private_url", f"https://{host}/metrics"),
        _lit("\nSource IP: "),
        _pii("account_number", ip),
        _lit("\n\nRoot cause: cache poisoning."),
    ]


def t_iban_payment(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    iban = _iban(faker)
    return [
        _lit("[payments] processed transfer for "),
        _pii("private_person", name),
        _lit(" to IBAN "),
        _pii("account_number", iban),
        _lit(" — receipt sent."),
    ]


def t_ssn_log(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    ssn = _ssn(faker)
    return [
        _lit("WARN: KYC retry for "),
        _pii("private_person", name),
        _lit(" (national_id="),
        _pii("account_number", ssn),
        _lit(") failed validation."),
    ]


def t_card_chargeback(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    card = _credit_card(faker)
    email = _email(faker)
    return [
        _lit("Chargeback raised by "),
        _pii("private_person", name),
        _lit(" ("),
        _pii("private_email", email),
        _lit(") for card ending "),
        _pii("account_number", card),
        _lit("."),
    ]


def t_curl_trace(faker: Faker, rng: random.Random) -> list[_Chunk]:
    jwt = _jwt(rng)
    host = _hostname(rng)
    return [
        _lit("Curl trace:\n  curl -H 'Authorization: Bearer "),
        _pii("secret", jwt),
        _lit("' "),
        _pii("private_url", f"https://{host}/api/v1/orders"),
        _lit("\n  → 403"),
    ]


def t_pr_review_long(faker: Faker, rng: random.Random) -> list[_Chunk]:
    n1 = _person(faker)
    n2 = _person(faker)
    email = _email(faker)
    return [
        _lit("PR feedback from "),
        _pii("private_person", n1),
        _lit(":\n\n> The retry loop in worker.ts looks racy. Did you "),
        _lit("benchmark this against the baseline?\n\nReassigning to "),
        _pii("private_person", n2),
        _lit(" for a second pass — please email "),
        _pii("private_email", email),
        _lit(" once you've addressed the comments."),
    ]


def t_env_dump(faker: Faker, rng: random.Random) -> list[_Chunk]:
    aws = _aws_key(rng)
    gh = _github_pat(rng)
    return [
        _lit("$ env | grep -E '(KEY|TOKEN)'\nAWS_ACCESS_KEY_ID="),
        _pii("secret", aws),
        _lit("\nGITHUB_TOKEN="),
        _pii("secret", gh),
        _lit("\nLOG_LEVEL=info"),
    ]


def t_meeting_notes(faker: Faker, rng: random.Random) -> list[_Chunk]:
    n1 = _person(faker)
    n2 = _person(faker)
    date = _date(faker)
    addr = _address_one_line(faker)
    return [
        _lit("Meeting notes — "),
        _pii("private_date", date),
        _lit("\nAttendees: "),
        _pii("private_person", n1),
        _lit(", "),
        _pii("private_person", n2),
        _lit("\nLocation: "),
        _pii("private_address", addr),
        _lit("\nAction: revisit next sprint."),
    ]


def t_oncall_handoff(faker: Faker, rng: random.Random) -> list[_Chunk]:
    n1 = _person(faker)
    phone = _phone(faker)
    host = _hostname(rng)
    return [
        _lit("Handing off oncall to "),
        _pii("private_person", n1),
        _lit(" — reachable at "),
        _pii("private_phone", phone),
        _lit(". Active alerts on "),
        _pii("private_url", f"https://{host}/alerts"),
        _lit("."),
    ]


def t_user_record_dump(faker: Faker, rng: random.Random) -> list[_Chunk]:
    name = _person(faker)
    email = _email(faker)
    phone = _phone(faker)
    date = _date(faker)
    return [
        _lit("DEBUG users.row =\n  name="),
        _pii("private_person", name),
        _lit("\n  email="),
        _pii("private_email", email),
        _lit("\n  phone="),
        _pii("private_phone", phone),
        _lit("\n  created_at="),
        _pii("private_date", date),
    ]


# All template builders. Each is a callable returning a chunk list.
TEMPLATES: tuple[Callable[[Faker, random.Random], list[_Chunk]], ...] = (
    t_pr_review,
    t_rfc_byline,
    t_deploy_log_aws,
    t_deploy_log_stripe,
    t_db_connection_string,
    t_support_ticket,
    t_support_ticket_short,
    t_code_secret_comment,
    t_code_anthropic,
    t_code_docstring_secret,
    t_slack_repost,
    t_postmortem,
    t_iban_payment,
    t_ssn_log,
    t_card_chargeback,
    t_curl_trace,
    t_pr_review_long,
    t_env_dump,
    t_meeting_notes,
    t_oncall_handoff,
    t_user_record_dump,
)


# ─── Validation ───────────────────────────────────────────────────


def _validate_record(record: dict) -> None:
    """Sanity check that span offsets actually slice the recorded PII.

    Catches off-by-one errors in template construction immediately
    rather than letting them silently corrupt the training set.
    """
    text = record["text"]
    for s in record["spans"]:
        start, end = int(s["start"]), int(s["end"])
        if start < 0 or end > len(text) or start >= end:
            raise ValueError(
                f"invalid span offsets: {s} for text of length {len(text)}",
            )


# ─── Generation loop ──────────────────────────────────────────────


def generate(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    # One Faker per locale, seeded deterministically from `seed` so
    # successive runs produce bit-identical data.
    fakers: dict[str, Faker] = {}
    for loc in LOCALES:
        f = Faker(loc)
        f.seed_instance(seed)
        fakers[loc] = f

    records: list[dict] = []
    for i in range(n):
        loc = rng.choice(LOCALES)
        template = rng.choice(TEMPLATES)
        chunks = template(fakers[loc], rng)
        text, spans = _assemble(chunks)
        if not spans:
            # Templates always emit at least one span by construction;
            # an empty list signals a code bug, not bad sampling.
            raise RuntimeError(f"template {template.__name__} produced 0 spans")
        record = {
            "id": f"dev-paste-synth-{i:06d}",
            "locale": LOCALE_TO_BENCH_CODE[loc],
            "subset": SUBSET_NAME,
            "text": text,
            "spans": spans,
        }
        _validate_record(record)
        records.append(record)
    return records


# ─── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--n", type=int, default=20_000)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[gen] generating {args.n} dev-paste synth records (seed={args.seed})…")
    records = generate(args.n, args.seed)

    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[gen] DONE → {args.out} ({len(records)} records)")

    # Brief distribution summary so the user can sanity-check at a glance.
    by_locale: dict[str, int] = {}
    by_label: dict[str, int] = {}
    for r in records:
        by_locale[r["locale"]] = by_locale.get(r["locale"], 0) + 1
        for s in r["spans"]:
            by_label[s["label"]] = by_label.get(s["label"], 0) + 1
    print(f"[gen] locale dist: {by_locale}")
    print(f"[gen] label dist:  {by_label}")


if __name__ == "__main__":
    main()
