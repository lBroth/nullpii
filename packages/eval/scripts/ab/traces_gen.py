# SPDX-License-Identifier: Apache-2.0
"""Build the Claude-Code-traces report set (PROTOCOL.md report set).

What a coding agent actually reads: source files, READMEs, package
manifests, logs, .env files, CSV exports, SQL, stack traces, git logs.
Carriers are real open-source files from `node_modules` (not this
repository: its files feed the U1 decision metric) plus template-built
logs and configs. PII and secrets are planted, so gold spans are exact.

Value pools are written by hand, not drawn from Faker, because Faker
generated part of the training data. Secrets cover a broad list of
formats, including ones nullpii's recognizer pack has no pattern for,
and generic secrets no regex can identify, so the set does not favour
any one tool's rules.

Carrier cleaning: lines carrying an email address and manifest
author/maintainer/contributor fields are removed before planting, so
real maintainer PII does not sit in the text as unlabelled gold. Names
mentioned in README prose are not removed; that residual noise is the
same for every tool.

Deterministic (fixed seed). Output is not redistributed: it stays under
the gitignored results/ tree.

  python traces_gen.py --node-modules <dir> --out traces.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import string
from pathlib import Path

SEED = 20261016
N_DOCS = 400
N_LONG = 40
CARRIER_MAX_CHARS = 8_000
LONG_DOC_CHARS = 28_000
NEGATIVE_SHARE = 0.15
PLANTS_PER_DOC = (1, 6)

FIRST = {
    "it": ["Giulia", "Marco", "Chiara", "Alessandro", "Francesca", "Lorenzo", "Martina", "Davide", "Sara", "Matteo", "Elisa", "Riccardo"],
    "de": ["Lena", "Jonas", "Hannah", "Lukas", "Sophie", "Felix", "Marie", "Tobias", "Anna", "Maximilian", "Laura", "Niklas"],
    "fr": ["Camille", "Louis", "Manon", "Hugo", "Chloé", "Lucas", "Léa", "Théo", "Inès", "Gabriel", "Zoé", "Arthur"],
    "es": ["Lucía", "Hugo", "Carmen", "Javier", "Elena", "Diego", "Paula", "Álvaro", "Marta", "Pablo", "Nerea", "Sergio"],
    "en": ["Emily", "James", "Olivia", "Ethan", "Grace", "Daniel", "Chloe", "Ryan", "Hannah", "Nathan", "Megan", "Owen"],
    "nl": ["Sanne", "Daan", "Fleur", "Bram", "Lotte", "Sem", "Femke", "Thijs", "Iris", "Ruben", "Noor", "Jesse"],
}
LAST = {
    "it": ["Ferrari", "Esposito", "Bianchi", "Colombo", "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti", "Mancini", "Lombardi"],
    "de": ["Müller", "Schneider", "Fischer", "Weber", "Becker", "Hoffmann", "Schäfer", "Koch", "Richter", "Klein", "Wolf", "Neumann"],
    "fr": ["Martin", "Bernard", "Dubois", "Lefèvre", "Moreau", "Laurent", "Girard", "Roux", "Fournier", "Mercier", "Blanc", "Garnier"],
    "es": ["García", "Fernández", "López", "Martínez", "Sánchez", "Romero", "Navarro", "Torres", "Ruiz", "Moreno", "Jiménez", "Castillo"],
    "en": ["Thompson", "Walker", "Harris", "Clarke", "Turner", "Hughes", "Wright", "Bennett", "Parker", "Mitchell", "Collins", "Foster"],
    "nl": ["de Vries", "Jansen", "Bakker", "Visser", "Smit", "Meijer", "de Boer", "Mulder", "Bos", "Vos", "Peters", "Hendriks"],
}
MAIL_DOMAINS = ["gmail.com", "outlook.com", "libero.it", "gmx.de", "orange.fr", "telefonica.net", "ziggo.nl", "proton.me",
                "studio-ferri.it", "brandt-logistik.de", "atelier-roux.fr", "constructora-navarro.es", "harbourview-legal.co.uk"]
STREETS = {
    "it": ["Via Garibaldi", "Corso Vittorio Emanuele II", "Via dei Mille", "Piazza Cavour", "Viale Monza"],
    "de": ["Hauptstraße", "Bahnhofstraße", "Lindenallee", "Schillerstraße", "Am Marktplatz"],
    "fr": ["rue de la République", "avenue Jean Jaurès", "boulevard Voltaire", "rue Victor Hugo", "place de la Mairie"],
    "es": ["Calle Mayor", "Avenida de la Constitución", "Calle de Alcalá", "Paseo de Gracia", "Calle Real"],
    "en": ["High Street", "Station Road", "Church Lane", "Victoria Road", "Park Avenue"],
    "nl": ["Kerkstraat", "Dorpsstraat", "Stationsweg", "Molenstraat", "Prinsengracht"],
}
CITIES = {
    "it": [("20121", "Milano"), ("00184", "Roma"), ("40126", "Bologna"), ("10123", "Torino")],
    "de": [("10115", "Berlin"), ("80331", "München"), ("50667", "Köln"), ("20095", "Hamburg")],
    "fr": [("75011", "Paris"), ("69002", "Lyon"), ("13001", "Marseille"), ("31000", "Toulouse")],
    "es": [("28013", "Madrid"), ("08007", "Barcelona"), ("41001", "Sevilla"), ("46002", "Valencia")],
    "en": [("SW1A 1AA", "London"), ("M1 1AE", "Manchester"), ("EH1 1YZ", "Edinburgh"), ("BS1 4DJ", "Bristol")],
    "nl": [("1012 JS", "Amsterdam"), ("3011 AD", "Rotterdam"), ("3511 LX", "Utrecht"), ("2511 BT", "Den Haag")],
}
IBAN_SHAPE = {"it": ("IT", "A", 27), "de": ("DE", "", 22), "fr": ("FR", "", 27), "es": ("ES", "", 24), "nl": ("NL", "AAAA", 18), "en": ("GB", "AAAA", 22)}  # total IBAN length
PHONE = {
    "it": lambda r: f"+39 3{r.randint(20, 49)} {r.randint(100, 999)} {r.randint(1000, 9999)}",
    "de": lambda r: f"+49 15{r.randint(1, 9)} {r.randint(1000000, 9999999)}",
    "fr": lambda r: f"+33 6 {r.randint(10, 99)} {r.randint(10, 99)} {r.randint(10, 99)} {r.randint(10, 99)}",
    "es": lambda r: f"+34 6{r.randint(10, 99)} {r.randint(100, 999)} {r.randint(100, 999)}",
    "en": lambda r: f"+44 7{r.randint(100, 999)} {r.randint(100000, 999999)}",
    "nl": lambda r: f"+31 6 {r.randint(10000000, 99999999)}",
}

ALNUM = string.ascii_letters + string.digits
B64 = ALNUM + "+/"
B64URL = ALNUM + "-_"


def rnd(r: random.Random, alphabet: str, n: int) -> str:
    return "".join(r.choice(alphabet) for _ in range(n))


def ascii_fold(s: str) -> str:
    table = str.maketrans("àáâäãåèéêëìíîïòóôöõùúûüçñßÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜÇÑ", "aaaaaaeeeeiiiiooooouuuucnsAAAAEEEEIIIIOOOOUUUUCN")
    return re.sub(r"[^a-z.]", "", s.translate(table).lower().replace(" ", ""))


def iban(r: random.Random, loc: str) -> str:
    country, prefix, length = IBAN_SHAPE[loc]
    bban = "".join(r.choice(string.ascii_uppercase) if c == "A" else r.choice(string.digits) for c in prefix)
    bban += rnd(r, string.digits, length - 4 - len(bban))
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{bban}"


def luhn_card(r: random.Random) -> str:
    body = r.choice(["4", "51", "52", "53", "54", "55"]) + rnd(r, string.digits, 14)
    body = body[:15]
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    full = body + str((10 - total % 10) % 10)
    return " ".join(full[i : i + 4] for i in range(0, 16, 4))


_CF_ODD = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                   [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23], strict=True))
_CF_MONTHS = "ABCDEHLMPRST"


def codice_fiscale(r: random.Random) -> str:
    body = rnd(r, string.ascii_uppercase, 6) + f"{r.randint(50, 99):02d}" + r.choice(_CF_MONTHS)
    body += f"{r.randint(1, 28) + r.choice([0, 40]):02d}" + r.choice(string.ascii_uppercase) + f"{r.randint(100, 999)}"
    total = 0
    for i, ch in enumerate(body):
        if i % 2 == 0:
            total += _CF_ODD[ch]
        else:
            total += int(ch) if ch.isdigit() else ord(ch) - ord("A")
    return body + chr(ord("A") + total % 26)


def public_ip(r: random.Random) -> str:
    while True:
        a = r.choice([31, 46, 62, 77, 81, 93, 109, 151, 178, 185, 188, 212, 213, 217])
        return f"{a}.{r.randint(1, 254)}.{r.randint(1, 254)}.{r.randint(1, 254)}"


SECRETS = {
    "aws_access_key": lambda r: "AKIA" + rnd(r, string.ascii_uppercase + string.digits, 16),
    "aws_secret": lambda r: rnd(r, B64, 40),
    "github_pat": lambda r: "ghp_" + rnd(r, ALNUM, 36),
    "github_fine": lambda r: "github_pat_" + rnd(r, ALNUM, 22) + "_" + rnd(r, ALNUM, 59),
    "gitlab_pat": lambda r: "glpat-" + rnd(r, ALNUM + "-_", 20),
    "slack_bot": lambda r: f"xoxb-{r.randint(10**10, 10**11)}-{r.randint(10**11, 10**12)}-{rnd(r, ALNUM, 24)}",
    "stripe_live": lambda r: "sk_live_" + rnd(r, ALNUM, 32),
    "anthropic": lambda r: "sk-ant-api03-" + rnd(r, B64URL, 93) + "AA",
    "openai_proj": lambda r: "sk-proj-" + rnd(r, B64URL, 64),
    "google_api": lambda r: "AIza" + rnd(r, B64URL, 35),
    "npm_token": lambda r: "npm_" + rnd(r, ALNUM, 36),
    "hf_token": lambda r: "hf_" + rnd(r, ALNUM, 34),
    "sendgrid": lambda r: "SG." + rnd(r, B64URL, 22) + "." + rnd(r, B64URL, 43),
    "jwt": lambda r: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + rnd(r, B64URL, 48) + "." + rnd(r, B64URL, 43),
    "azure_account_key": lambda r: rnd(r, B64, 86) + "==",
    "datadog_api": lambda r: rnd(r, "0123456789abcdef", 32),
    "generic_hex": lambda r: rnd(r, "0123456789abcdef", 40),
    "generic_password": lambda r: rnd(r, ALNUM, 6) + r.choice("!#$%&*") + rnd(r, ALNUM, 5),
    "db_password": lambda r: rnd(r, ALNUM, 14),
}
SECRET_LINES = {
    "aws_access_key": ["AWS_ACCESS_KEY_ID={v}", "aws_access_key_id = {v}"],
    "aws_secret": ["AWS_SECRET_ACCESS_KEY={v}", "aws_secret_access_key = {v}"],
    "github_pat": ["GITHUB_TOKEN={v}", "token: {v}"],
    "github_fine": ["GH_TOKEN={v}"],
    "gitlab_pat": ["GITLAB_TOKEN={v}"],
    "slack_bot": ["SLACK_BOT_TOKEN={v}"],
    "stripe_live": ["STRIPE_SECRET_KEY={v}", 'stripeKey: "{v}"'],
    "anthropic": ["ANTHROPIC_API_KEY={v}"],
    "openai_proj": ["OPENAI_API_KEY={v}"],
    "google_api": ["GOOGLE_MAPS_KEY={v}", 'apiKey: "{v}"'],
    "npm_token": ["//registry.npmjs.org/:_authToken={v}"],
    "hf_token": ["HF_TOKEN={v}"],
    "sendgrid": ["SENDGRID_API_KEY={v}"],
    "jwt": ["Authorization: Bearer {v}", 'session_token: "{v}"'],
    "azure_account_key": ["DefaultEndpointsProtocol=https;AccountName=prodstore;AccountKey={v};EndpointSuffix=core.windows.net"],
    "datadog_api": ["DD_API_KEY={v}"],
    "generic_hex": ["INTERNAL_API_TOKEN={v}", "webhook_secret: {v}"],
    "generic_password": ['password = "{v}"', "ADMIN_PASSWORD={v}"],
    "db_password": ["DATABASE_URL=postgres://app_rw:{v}@db-prod-2.internal:5432/orders"],
}


class Person:
    def __init__(self, r: random.Random) -> None:
        self.loc = r.choice(list(FIRST))
        self.first = r.choice(FIRST[self.loc])
        self.last = r.choice(LAST[self.loc])
        self.name = f"{self.first} {self.last}"
        self.email = f"{ascii_fold(self.first)}.{ascii_fold(self.last)}@{r.choice(MAIL_DOMAINS)}"
        self.phone = PHONE[self.loc](r)
        self.username = ascii_fold(self.first)[0] + ascii_fold(self.last)
        zip_, city = r.choice(CITIES[self.loc])
        self.address = f"{r.choice(STREETS[self.loc])} {r.randint(1, 140)}, {zip_} {city}"
        self.dob = f"{r.randint(1950, 2003)}-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}"
        self.iban = iban(r, self.loc)
        self.card = luhn_card(r)
        self.cf = codice_fiscale(r) if self.loc == "it" else None
        self.ip = public_ip(r)


class Doc:
    """Text under construction with exact gold spans."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[dict] = []
        self.length = 0

    def add(self, text: str) -> None:
        self.parts.append(text)
        self.length += len(text)

    def pii(self, value: str, label: str) -> None:
        self.spans.append({"label": label, "start": self.length, "end": self.length + len(value)})
        self.add(value)

    def line(self, template: str, values: dict[str, tuple[str, str]]) -> None:
        """`template` holds `{key}` slots; `values[key] = (value, label)`."""
        for piece in re.split(r"(\{[a-z_]+\})", template):
            key = piece[1:-1] if piece.startswith("{") and piece.endswith("}") else None
            if key in values:
                self.pii(*values[key])
            else:
                self.add(piece)
        self.add("\n")

    def text(self) -> str:
        return "".join(self.parts)


def plant(doc: Doc, r: random.Random, comment: str) -> None:
    p = Person(r)
    kind = r.choice(["person", "contact", "finance", "secret", "secret", "address", "ip", "id"])
    c = comment
    if kind == "person":
        doc.line(f"{c}TODO({{name}}): confirm the migration window before Friday", {"name": (p.name, "private_person")})
    elif kind == "contact":
        doc.line(f"{c}Owner: {{name}} <{{email}}>, on call {{phone}}",
                 {"name": (p.name, "private_person"), "email": (p.email, "private_email"), "phone": (p.phone, "private_phone")})
    elif kind == "finance":
        if p.cf and r.random() < 0.5:
            doc.line(f"{c}refund to {{name}} (CF {{cf}}), IBAN {{iban}}",
                     {"name": (p.name, "private_person"), "cf": (p.cf, "account_number"), "iban": (p.iban, "account_number")})
        else:
            doc.line(f"{c}test charge declined for card {{card}} ({{name}})",
                     {"card": (p.card, "account_number"), "name": (p.name, "private_person")})
    elif kind == "secret":
        fmt = r.choice(list(SECRETS))
        doc.line(c + r.choice(SECRET_LINES[fmt]), {"v": (SECRETS[fmt](r), "secret")})
    elif kind == "address":
        doc.line(f"{c}ship replacement to {{name}}, {{address}}",
                 {"name": (p.name, "private_person"), "address": (p.address, "private_address")})
    elif kind == "ip":
        doc.line(f"{c}blocked login for {{email}} from {{ip}}", {"email": (p.email, "private_email"), "ip": (p.ip, "private_ip")})
    else:
        doc.line(f"{c}KYC: {{name}}, born {{dob}}", {"name": (p.name, "private_person"), "dob": (p.dob, "private_date")})


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
MANIFEST_PEOPLE_RE = re.compile(r'"(author|maintainers|contributors|email)"', re.I)


def clean_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not EMAIL_RE.search(ln) and not MANIFEST_PEOPLE_RE.search(ln)]


def carrier_files(node_modules: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for pkg in sorted(p for p in node_modules.iterdir() if p.is_dir() and not p.name.startswith((".", "@"))):
        manifest = pkg / "package.json"
        if not manifest.exists():
            continue
        readme = next((pkg / n for n in ("README.md", "readme.md", "Readme.md") if (pkg / n).exists()), None)
        if readme:
            files.append(("markdown", readme))
        files.append(("json", manifest))
        main = json.loads(manifest.read_text(encoding="utf-8", errors="replace")).get("main") or "index.js"
        main_path = pkg / main if (pkg / main).suffix else pkg / f"{main}.js"
        if main_path.exists() and main_path.is_file():
            files.append(("code", main_path))
    return files


COMMENT = {"code": "// ", "markdown": "", "json": "", "log": "", "env": "# ", "csv": "", "sql": "-- ", "trace": ""}


def from_carrier(r: random.Random, kind: str, path: Path, plants: int, max_chars: int) -> Doc:
    lines = clean_lines(path.read_text(encoding="utf-8", errors="replace")[: max_chars * 2])
    doc = Doc()
    slots = set(r.sample(range(len(lines) + 1), min(plants, len(lines) + 1))) if plants else set()
    for i, ln in enumerate(lines):
        if doc.length >= max_chars:
            break
        if i in slots:
            if kind == "json":
                plant_json(doc, r)
            else:
                plant(doc, r, COMMENT[kind])
        doc.add(ln + "\n")
    return doc


def plant_json(doc: Doc, r: random.Random) -> None:
    p = Person(r)
    if r.random() < 0.5:
        doc.line('  "contact": "{name} <{email}>",', {"name": (p.name, "private_person"), "email": (p.email, "private_email")})
    else:
        fmt = r.choice(list(SECRETS))
        doc.line('  "_authToken": "{v}",', {"v": (SECRETS[fmt](r), "secret")})


def synthetic(r: random.Random, kind: str, plants: int) -> Doc:
    doc = Doc()
    n_lines = r.randint(20, 120)
    slots = set(r.sample(range(n_lines), min(plants, n_lines))) if plants else set()
    for i in range(n_lines):
        if i in slots:
            synthetic_pii_line(doc, r, kind)
        else:
            doc.add(synthetic_noise_line(r, kind) + "\n")
    return doc


def synthetic_noise_line(r: random.Random, kind: str) -> str:
    rid = rnd(r, "0123456789abcdef", 16)
    ms = r.randint(2, 900)
    if kind == "log":
        return f"2026-10-{r.randint(1, 28):02d}T{r.randint(0, 23):02d}:{r.randint(0, 59):02d}:{r.randint(0, 59):02d}Z INFO http GET /api/v2/orders/{r.randint(1000, 99999)} 200 {ms}ms req={rid}"
    if kind == "env":
        return r.choice(["NODE_ENV=production", f"PORT={r.randint(3000, 9000)}", "LOG_LEVEL=info", f"CACHE_TTL={r.randint(60, 3600)}", "FEATURE_NEW_CHECKOUT=true"])
    if kind == "csv":
        return f"{r.randint(1, 99999)},{r.choice(['active', 'paused', 'closed'])},{r.randint(1, 500)},{r.choice(['EUR', 'GBP', 'USD'])}"
    if kind == "sql":
        return f"UPDATE orders SET status = '{r.choice(['shipped', 'paid'])}' WHERE id = {r.randint(1, 99999)};"
    return f"    at {r.choice(['processTicksAndRejections', 'Router.handle', 'Layer.handle', 'next'])} (node:internal/process/task_queues:{r.randint(50, 120)}:{r.randint(1, 40)})"


def synthetic_pii_line(doc: Doc, r: random.Random, kind: str) -> None:
    p = Person(r)
    if kind == "log":
        doc.line("2026-10-16T09:41:07Z WARN auth failed login user={email} ip={ip} attempts=3",
                 {"email": (p.email, "private_email"), "ip": (p.ip, "private_ip")})
    elif kind == "env":
        fmt = r.choice(list(SECRETS))
        doc.line(r.choice(SECRET_LINES[fmt]), {"v": (SECRETS[fmt](r), "secret")})
    elif kind == "csv":
        doc.line("{name},{email},{phone},{iban}", {"name": (p.name, "private_person"), "email": (p.email, "private_email"),
                                                    "phone": (p.phone, "private_phone"), "iban": (p.iban, "account_number")})
    elif kind == "sql":
        doc.line("INSERT INTO customers (full_name, email, birth_date) VALUES ('{name}', '{email}', '{dob}');",
                 {"name": (p.name, "private_person"), "email": (p.email, "private_email"), "dob": (p.dob, "private_date")})
    else:
        doc.line("Error: ENOENT: no such file or directory, open '/Users/{user}/projects/billing/.env.local'",
                 {"user": (p.username, "private_person")})


SYNTHETIC_KINDS = ["log", "env", "csv", "sql", "trace"]


def source_of(kind: str, path: Path) -> str:
    return f"{kind}:{path.parent.name}/{path.name}"


def build(
    node_modules: Path, seed: int = SEED, exclude: frozenset[str] = frozenset(), used: set[str] | None = None
) -> list[dict]:
    """`used`, when given, collects every carrier file read, including the
    parts of concatenated long docs, so another set can exclude them."""
    used = set() if used is None else used
    r = random.Random(seed)
    carriers = [c for c in carrier_files(node_modules) if source_of(*c) not in exclude]
    docs = []
    for i in range(N_DOCS):
        plants = 0 if r.random() < NEGATIVE_SHARE else r.randint(*PLANTS_PER_DOC)
        if r.random() < 0.6:
            kind, path = r.choice(carriers)
            doc = from_carrier(r, kind, path, plants, CARRIER_MAX_CHARS)
            source = source_of(kind, path)
            used.add(source)
        else:
            kind = r.choice(SYNTHETIC_KINDS)
            doc = synthetic(r, kind, plants)
            source = f"{kind}:synthetic"
        docs.append({"id": f"trace:{i}", "kind": kind, "source": source, "text": doc.text(), "spans": doc.spans})
    code = [c for c in carriers if c[0] == "code"]
    for i in range(N_LONG):
        doc = Doc()
        while doc.length < LONG_DOC_CHARS:
            _, path = r.choice(code)
            used.add(source_of("code", path))
            part = from_carrier(r, "code", path, r.randint(1, 3), LONG_DOC_CHARS - doc.length)
            offset = doc.length
            doc.add(part.text())
            doc.spans += [{**s, "start": s["start"] + offset, "end": s["end"] + offset} for s in part.spans]
        docs.append({"id": f"trace-long:{i}", "kind": "code-long", "source": "code:concat", "text": doc.text(), "spans": doc.spans})
    return docs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-modules", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--exclude-from", type=Path, help="a <traces>.sources.json whose carrier files must not be reused"
    )
    args = parser.parse_args()
    exclude = frozenset(json.loads(args.exclude_from.read_text())) if args.exclude_from else frozenset()
    used: set[str] = set()
    docs = build(args.node_modules, args.seed, exclude, used)
    Path(f"{args.out}.sources.json").write_text(json.dumps(sorted(used)), encoding="utf-8")
    for d in docs:
        for s in d["spans"]:
            if not d["text"][s["start"] : s["end"]]:
                raise ValueError(f"{d['id']}: empty gold span {s}")
    with args.out.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    n_spans = sum(len(d["spans"]) for d in docs)
    chars = sum(len(d["text"]) for d in docs)
    print(f"docs {len(docs)}  gold spans {n_spans}  chars {chars}")


if __name__ == "__main__":
    main()
