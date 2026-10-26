# SPDX-License-Identifier: Apache-2.0
"""MUST_KEEP / AMBIGUOUS value generators: hashes, versions, dates, placeholders, public URLs, ..."""
from __future__ import annotations

import base64
import random
import string
import uuid as _uuid

import values as VV

HEX = "0123456789abcdef"

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}
MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW3 = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def sha40(rng: random.Random) -> str:
    return "".join(rng.choice(HEX) for _ in range(40))


def short_sha(rng: random.Random, n: int | None = None) -> str:
    return "".join(rng.choice(HEX) for _ in range(n or rng.choice([7, 7, 8, 10, 12])))


def sha256hex(rng: random.Random) -> str:
    return "".join(rng.choice(HEX) for _ in range(64))


def uuid4(rng: random.Random) -> str:
    return str(_uuid.UUID(int=rng.getrandbits(128), version=4))


def integrity(rng: random.Random) -> str:
    return "sha512-" + base64.b64encode(bytes(rng.getrandbits(8) for _ in range(64))).decode()


def docker_digest(rng: random.Random) -> str:
    return "sha256:" + sha256hex(rng)


def version(rng: random.Random, v_prefix: bool | None = None) -> str:
    major = rng.choices([0, 1, 2, 3, 4, 5, 8, 12, 18, 20], [3, 5, 4, 3, 2, 2, 1, 1, 1, 1])[0]
    s = f"{major}.{rng.randint(0, 30)}.{rng.randint(0, 20)}"
    if rng.random() < 0.1:
        s += rng.choice(["-rc.1", "-beta.2", "-alpha", ".post1", "-SNAPSHOT"])
    if v_prefix or (v_prefix is None and rng.random() < 0.2):
        s = "v" + s
    return s


def date_parts(rng: random.Random, lo: int = 2022, hi: int = 2026) -> tuple[int, int, int, int, int, int]:
    return rng.randint(lo, hi), rng.randint(1, 12), rng.randint(1, 28), rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)


def iso_date(rng: random.Random) -> str:
    y, m, d, *_ = date_parts(rng)
    return f"{y}-{m:02d}-{d:02d}"


def iso_ts(rng: random.Random, z: bool | None = None, ms: bool | None = None) -> str:
    y, mo, d, h, mi, s = date_parts(rng)
    frac = f".{rng.randint(0, 999):03d}" if (ms if ms is not None else rng.random() < 0.5) else ""
    tz = "Z" if (z if z is not None else rng.random() < 0.6) else rng.choice(["+00:00", "+01:00", "+02:00", "-05:00"])
    return f"{y}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{frac}{tz}"


def log_ts(rng: random.Random) -> str:
    y, mo, d, h, mi, s = date_parts(rng)
    return rng.choice([f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d},{rng.randint(0, 999):03d}",
                       f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}.{rng.randint(0, 999):03d}",
                       f"{y}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}Z",
                       f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"])


def git_date(rng: random.Random) -> str:
    y, mo, d, h, mi, s = date_parts(rng)
    return f"{rng.choice(DOW3)} {MON3[mo - 1]} {d} {h:02d}:{mi:02d}:{s:02d} {y} {rng.choice(['+0100', '+0200', '+0000', '-0500', '-0700'])}"


def http_date(rng: random.Random) -> str:
    y, mo, d, h, mi, s = date_parts(rng)
    return f"{rng.choice(DOW3)}, {d:02d} {MON3[mo - 1]} {y} {h:02d}:{mi:02d}:{s:02d} GMT"


def clf_date(rng: random.Random) -> str:
    y, mo, d, h, mi, s = date_parts(rng)
    return f"{d:02d}/{MON3[mo - 1]}/{y}:{h:02d}:{mi:02d}:{s:02d} +0000"


def syslog_date(rng: random.Random) -> str:
    _, mo, d, h, mi, s = date_parts(rng)
    return f"{MON3[mo - 1]} {d:>2} {h:02d}:{mi:02d}:{s:02d}"


def human_date(rng: random.Random, lang: str) -> str:
    y, m, d, *_ = date_parts(rng)
    mn = MONTHS[lang][m - 1]
    if lang == "en":
        return rng.choice([f"{mn} {d}, {y}", f"{d} {mn} {y}", f"{y}-{m:02d}-{d:02d}"])
    if lang == "it":
        return rng.choice([f"{d} {mn} {y}", f"{d:02d}/{m:02d}/{y}"])
    if lang == "de":
        return rng.choice([f"{d}. {mn} {y}", f"{d:02d}.{m:02d}.{y}"])
    if lang == "fr":
        return rng.choice([f"{d} {mn} {y}", f"{d:02d}/{m:02d}/{y}"])
    return rng.choice([f"{d} de {mn} de {y}", f"{d:02d}/{m:02d}/{y}"])


def birth_date_str(lang: str, y: int, m: int, d: int, rng: random.Random) -> str:
    if lang == "en":
        return rng.choice([f"{y}-{m:02d}-{d:02d}", f"{m:02d}/{d:02d}/{y}", f"{d:02d}/{m:02d}/{y}"])
    if lang == "de":
        return f"{d:02d}.{m:02d}.{y}"
    return f"{d:02d}/{m:02d}/{y}"


# ------------------------------------------------------------------ placeholders, env refs, reserved

ENV_VARS = ["DATABASE_URL", "API_KEY", "STRIPE_SECRET_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SMTP_PASSWORD",
            "REDIS_URL", "SENTRY_DSN", "JWT_SECRET", "OPENAI_API_KEY", "DB_PASSWORD", "SLACK_WEBHOOK_URL", "NPM_TOKEN",
            "TWILIO_AUTH_TOKEN", "SECRET_KEY", "MAILGUN_API_KEY", "HOME", "PATH", "CI_JOB_TOKEN", "PGPASSWORD"]


def env_ref(rng: random.Random, var: str | None = None) -> str:
    var = var or rng.choice(ENV_VARS)
    return rng.choice([f"${{{var}}}", f"${var}", f"${{{{ secrets.{var} }}}}", f"${{{var}:-}}", f"%{var}%"])


def placeholder(rng: random.Random, what: str = "API_KEY") -> str:
    w = what.upper()
    return rng.choice([f"YOUR_{w}", f"<your-{what.lower().replace('_', '-')}>", f"<{what.lower()}>", "xxxxxxxxxxxxxxxx",
                       "XXXXXXXXXXXXXXXXXXXX", f"REPLACE_WITH_{w}", "********", "<redacted>", "[REDACTED]", f"{{{{ {what.lower()} }}}}",
                       f"your_{what.lower()}_here", "changeme-in-prod"])


def reserved_host(rng: random.Random) -> str:
    return rng.choice(["localhost", "127.0.0.1", "0.0.0.0", "::1", "example.com", "api.example.com", "example.org",
                       "db.example.net", "test.example.com"])


def example_email(rng: random.Random) -> str:
    local = rng.choice(["user", "jane.doe", "john.doe", "test", "alice", "bob", "someone", "you", "admin", "customer"])
    return f"{local}@{rng.choice(['example.com', 'example.org', 'example.net'])}"


def role_email(rng: random.Random) -> str:
    return f"{rng.choice(VV.handmade_lines('role_localparts.txt'))}@{rng.choice(VV.handmade_lines('role_domains.txt'))}"


def dummy_cred(rng: random.Random) -> str:
    return rng.choice(VV.handmade_lines("dummy_credentials.txt"))


# ------------------------------------------------------------------ public URLs, paths, tickets

PUBLIC_URLS = [
    "https://docs.python.org/3/library/{mod}.html", "https://pypi.org/project/{pkg}/", "https://pypi.org/simple/",
    "https://github.com/{org}/{repo}/issues/{n}", "https://github.com/{org}/{repo}/pull/{n}",
    "https://github.com/{org}/{repo}/blob/main/README.md", "https://api.github.com/repos/{org}/{repo}/releases",
    "https://api.stripe.com/v1/charges", "https://api.stripe.com/v1/customers", "https://registry.npmjs.org/",
    "https://www.npmjs.com/package/{npkg}", "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/{code}",
    "https://docs.djangoproject.com/en/4.2/ref/settings/", "https://kubernetes.io/docs/concepts/configuration/secret/",
    "https://hub.docker.com/_/postgres", "https://docs.docker.com/compose/environment-variables/",
    "https://api.openai.com/v1/chat/completions", "https://api.anthropic.com/v1/messages", "https://api.twilio.com/2010-04-01/Accounts",
    "https://hooks.slack.com/", "https://www.rfc-editor.org/rfc/rfc{rfc}", "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html",
    "https://cloud.google.com/docs/authentication", "https://fastapi.tiangolo.com/tutorial/security/",
    "https://nodejs.org/api/fs.html", "https://docs.gitlab.com/ee/ci/variables/", "https://stackoverflow.com/questions/{so}",
    "https://sentry.io/organizations/", "https://api.sendgrid.com/v3/mail/send", "https://www.postgresql.org/docs/16/libpq-envars.html",
    "https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions", "https://redis.io/docs/latest/",
    "https://crates.io/crates/{crate}", "https://go.dev/doc/", "https://maven.apache.org/settings.html",
]
MODS = ["json", "os", "pathlib", "subprocess", "logging", "datetime", "re", "urllib.parse", "asyncio", "typing"]
PKGS = ["requests", "django", "fastapi", "pydantic", "boto3", "sqlalchemy", "celery", "httpx", "pytest", "numpy"]
NPKGS = ["express", "axios", "dotenv", "jsonwebtoken", "next", "react", "zod", "prisma", "lodash", "pg"]
ORGS = [("psf", "requests"), ("django", "django"), ("tiangolo", "fastapi"), ("pallets", "flask"), ("encode", "httpx"),
        ("pydantic", "pydantic"), ("boto", "boto3"), ("expressjs", "express"), ("axios", "axios"), ("vercel", "next.js"),
        ("prisma", "prisma"), ("sqlalchemy", "sqlalchemy"), ("celery", "celery"), ("pytest-dev", "pytest"), ("nodejs", "node")]


def public_url(rng: random.Random) -> str:
    t = rng.choice(PUBLIC_URLS)
    org, repo = rng.choice(ORGS)
    return t.format(mod=rng.choice(MODS), pkg=rng.choice(PKGS), org=org, repo=repo, n=rng.randint(10, 9999),
                    npkg=rng.choice(NPKGS), code=rng.choice([400, 401, 403, 404, 409, 422, 429, 500, 502, 503]),
                    rfc=rng.choice([5737, 3849, 6749, 7519, 2606, 1918]), so=rng.randint(1_000_000, 79_000_000),
                    crate=rng.choice(["serde", "tokio", "reqwest", "clap"]))


def ticket_ref(rng: random.Random) -> str:
    return rng.choice([f"#{rng.randint(12, 9999)}", f"{rng.choice(['PROJ', 'OPS', 'BE', 'WEB', 'PAY', 'SUP', 'DEV', 'INFRA'])}-{rng.randint(10, 4999)}",
                       f"GH-{rng.randint(10, 999)}", f"INC{rng.randint(100000, 999999):07d}"])


INTERNAL_HOSTS = ["db.internal", "postgres.svc.cluster.local", "redis-master.default.svc.cluster.local", "jenkins.corp.local",
                  "vault.service.consul", "kafka-0.kafka-headless", "git.intranet.lan", "mysql-primary.prod.internal",
                  "rabbitmq.infra.local", "build-agent-07.ci.internal", "nexus.corp.lan", "es-data-2.logging.svc"]


def internal_host(rng: random.Random) -> str:
    return rng.choice(INTERNAL_HOSTS)


def rds_host(rng: random.Random) -> str:
    sub = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    return f"{rng.choice(['prod-db', 'app-main', 'orders', 'billing'])}.{sub}.{rng.choice(['eu-west-1', 'us-east-1', 'eu-central-1'])}.rds.amazonaws.com"


# ------------------------------------------------------------------ code identifiers (name-like)

CODE_WORDS = ["config", "client", "report", "export", "invoice", "adapter", "service", "handler", "fixture", "mapper", "parser", "utils",
              "settings", "loader", "sync", "backup", "importer", "validator"]


def namelike_identifier(rng: random.Random, lang: str) -> str:
    """Code identifiers containing a person-like token, e.g. getMarioConfig, class Rossi (MUST_KEEP)."""
    tok = rng.choice(VV.names(lang, rng.choice(["given_male", "given_female", "surnames"])))
    t = VV.fold(tok, lang).replace(" ", "").replace("-", "")
    w = rng.choice(CODE_WORDS)
    style = rng.random()
    if style < 0.25:
        return f"get{t.capitalize()}{w.capitalize()}"
    if style < 0.45:
        return f"{t.capitalize()}{w.capitalize()}"
    if style < 0.65:
        return f"{t.lower()}_{w}"
    if style < 0.8:
        return f"{rng.choice(['load', 'parse', 'build', 'send', 'test'])}_{t.lower()}_{w}"
    if style < 0.9:
        return t.capitalize()
    return f"{t.upper()}_{w.upper()}"


def job_title(rng: random.Random, lang: str) -> str:
    return rng.choice(VV.lang_table("job_titles.tsv")[lang])


def honorific(rng: random.Random, lang: str, gender: str) -> str:
    opts = {
        "en": {"m": ["Mr.", "Dr.", "Mr", "Prof."], "f": ["Ms.", "Mrs.", "Dr.", "Ms", "Prof."]},
        "it": {"m": ["Sig.", "Dott.", "Ing.", "Avv."], "f": ["Sig.ra", "Dott.ssa", "Ing.", "Avv."]},
        "de": {"m": ["Herr", "Dr.", "Herr Dr."], "f": ["Frau", "Dr.", "Frau Dr."]},
        "fr": {"m": ["M.", "Monsieur", "Dr"], "f": ["Mme", "Madame", "Dr"]},
        "es": {"m": ["Sr.", "D.", "Don", "Dr."], "f": ["Sra.", "Dña.", "Doña", "Dra."]},
    }
    return rng.choice(opts[lang][gender])


def org(rng: random.Random) -> str:
    return rng.choice(VV.handmade_lines("orgs.txt"))


def public_figure(rng: random.Random) -> str:
    return rng.choice(VV.handmade_lines("public_figures.txt"))


def order_number(rng: random.Random) -> str:
    return rng.choice([f"ORD-{rng.randint(100000, 999999)}", f"#{rng.randint(1000000, 9999999)}", f"{rng.randint(2023, 2026)}-{rng.randint(10000, 99999)}",
                       f"INV-{rng.randint(2023, 2026)}-{rng.randint(1000, 9999)}", f"FA{rng.randint(100000, 999999)}"])
