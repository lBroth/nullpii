# SPDX-License-Identifier: Apache-2.0
"""Template file reads (en): .env, YAML/JSON/TOML config, Dockerfile, CI files, source, fixtures, dotfiles."""
from __future__ import annotations

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc
from slots import Ctx
from tplutil import add_hook, file_read, frag, home_path, jdump, render_b64_line, urlenc

APPS = ["billing-api", "orders-service", "crm-sync", "shopfront", "invoice-worker", "auth-gateway", "data-pipeline",
        "notifier", "customer-portal", "inventory", "payments", "helpdesk-bot", "reporting", "booking-app"]
DB_USERS = ["app", "postgres", "orders_app", "billing", "svc_api", "root", "admin", "django", "rails"]


def _app(ctx: Ctx) -> str:
    return ctx.rng.choice(APPS)


def _db_host(ctx: Ctx) -> V:
    r = ctx.rng.random()
    if r < 0.45:
        return ctx.amb("internal_host")
    if r < 0.65:
        return AM(K.rds_host(ctx.rng), "internal_host")
    if r < 0.8:
        return ctx.private_ip()
    if r < 0.9:
        return KP("localhost", "reserved_address")
    return ctx.ip(v6_share=0)


def _secrets(ctx: Ctx, lo: int, hi: int) -> list:
    return [ctx.secret() for _ in range(ctx.rng.randint(lo, hi))]


def _conn_url(ctx: Ctx, scheme: str, user: str, pw: V, host: V, port: str, db: str) -> Doc:
    d = Doc()
    d.add(f"{scheme}://{user}:", pw, "@", host, ":", KP(port, "port"), f"/{db}")
    return d


# ------------------------------------------------------------------ families

def dotenv(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    app = _app(ctx)
    d = Doc()
    owner = ctx.person()
    d.add(f"# {app} — environment ({r.choice(['local development', 'staging', 'production', 'shared dev box'])}), see ", ctx.kp("ticket_number"), "\n")
    if not ctx.clean and r.random() < 0.5:
        d.add("# Owner: ", ctx.name(owner), " <", ctx.email(owner), ">\n")
    d.add(f"NODE_ENV={r.choice(['development', 'production', 'staging'])}\n" if r.random() < 0.5 else f"APP_ENV={r.choice(['local', 'production', 'staging'])}\n")
    d.add("PORT=", KP(r.choice(["3000", "8000", "8080", "5000"]), "port"), "\n")
    pw = ctx.password(owner)
    d.add("DB_PASSWORD=", pw, "\n")
    add_hook(d, pw, lambda rng, o: frag(f"DB_DSN=postgres://{rng.choice(DB_USERS)}:", V(urlenc(o.text), "MUST_MASK", "secret", "urlencoded:" + o.kind, enc_of=o),
                                         "@", AM(K.internal_host(rng), "internal_host"), ":", KP("5432", "port"), "/app\n"), "db_url_urlencoded")
    d.add("DATABASE_URL=").extend(_conn_url(ctx, r.choice(["postgres", "postgresql", "mysql"]), r.choice(DB_USERS), ctx.password(owner), _db_host(ctx),
                                             r.choice(["5432", "3306", "6432"]), r.choice(["app", "orders", "prod", app.replace("-", "_")])))
    d.add("\n")
    if r.random() < 0.6:
        d.add("REDIS_URL=redis://:", ctx.password(), "@", _db_host(ctx), ":", KP("6379", "port"), "/0\n")
    for s in _secrets(ctx, 2, 6):
        d.extend(ctx.secret_line(s, "env"))
        d.add("\n")
    if r.random() < 0.6:
        smtp = ctx.person()
        d.add(f"SMTP_HOST=smtp.{r.choice(['gmail.com', 'office365.com', 'sendgrid.net', 'mailgun.org'])}\nSMTP_PORT=",
              KP("587", "port"), "\nSMTP_USER=", ctx.email(smtp), "\nSMTP_PASSWORD=", ctx.password(smtp), "\n")
    if r.random() < 0.5:
        p = ctx.person()
        d.add("ADMIN_EMAIL=", ctx.email(p), "\n")
        if r.random() < 0.4:
            d.add("ADMIN_PHONE=", ctx.phone(), "\n")
    if r.random() < 0.4:
        d.add("ALLOWED_IPS=", ctx.ip(0), ",", ctx.ip(0), "\n")
    if r.random() < 0.4:
        d.add("# TODO(", ctx.given(ctx.person()), "): rotate these before the ", ctx.kp("date", lang="en"), " release\n")
    d.add("LOG_LEVEL=", r.choice(["info", "debug", "warn"]), "\n")
    return d, KP(f"/{r.choice(['srv', 'opt'])}/{app}/.env", "path") if r.random() < 0.3 else home_path(ctx, owner, f"{r.choice(['projects', 'code', 'src', 'work'])}/{app}/.env")


def compose(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    app = _app(ctx)
    p = ctx.person()
    pw = ctx.password(p)
    d = Doc()
    d.add('version: "3.9"\nservices:\n  db:\n    image: postgres:', KP(r.choice(["15.4", "16.2", "14.10", "16-alpine"]), "version"),
          "\n    environment:\n      POSTGRES_USER: app\n      POSTGRES_PASSWORD: ", pw, "\n      POSTGRES_DB: ", app.replace("-", "_"),
          '\n    ports:\n      - "', KP("5432", "port"), ':5432"\n    volumes:\n      - ')
    d.extend(home_path(ctx, p, f"docker-data/{app}/pg", mac=True) if not ctx.clean else frag(KP("./data/pg", "path")))
    d.add(":/var/lib/postgresql/data\n")
    d.add("  api:\n    image: ghcr.io/acme/", app, "@", KP(K.docker_digest(r), "hash"), "\n    depends_on: [db]\n    environment:\n")
    d.add("      - DATABASE_URL=postgres://app:", pw if not ctx.clean else ctx.password(), "@db:", KP("5432", "port"), f"/{app.replace('-', '_')}\n")
    for s in _secrets(ctx, 1, 4):
        d.extend(ctx.secret_line(s, "compose_env"))
        d.add("\n")
    if r.random() < 0.5:
        d.add("      - ADMIN_EMAIL=", ctx.email(ctx.person()), "\n")
    d.add('    ports:\n      - "', KP("8000", "port"), ':8000"\n')
    if r.random() < 0.5:
        d.add("  mailhog:\n    image: mailhog/mailhog:", KP("v1.0.1", "version"), '\n    ports: ["', KP("8025", "port"), ':8025"]\n')
    add_hook(d, pw, render_b64_line("# k8s secret (base64): POSTGRES_PASSWORD="), "compose_b64_comment")
    return d, KP(f"{app}/docker-compose.yml", "path")


def k8s(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    app = _app(ctx)
    d = Doc()
    d.add(f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {app}\n  labels:\n    app: {app}\nspec:\n  replicas: {r.randint(1, 4)}\n"
          f"  template:\n    spec:\n      containers:\n        - name: {app}\n          image: ghcr.io/acme/{app}@", KP(K.docker_digest(r), "hash"), "\n          env:\n")
    secrets = _secrets(ctx, 1, 3)
    for s in secrets:
        d.add(f"            - name: {s.var}\n              value: ")
        if s.is_pem:
            d.add('"')
            from doc import json_escape
            d.extend(json_escape(ctx.pem_doc(s)))
            d.add('"\n')
        else:
            d.add(ctx.secret_value(s), "\n")
    d.add("            - name: DB_HOST\n              value: ", _db_host(ctx), "\n")
    if r.random() < 0.5:
        d.add("            - name: ALERT_EMAIL\n              value: ", ctx.email(ctx.person()), "\n")
    d.add("---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: ", f"{app}-secrets\ntype: Opaque\nstringData:\n")
    pw = ctx.password()
    d.add("  db-password: ", pw, "\n")
    for s in _secrets(ctx, 0, 2):
        if s.is_pem:
            continue
        d.add(f"  {s.var.lower().replace('_', '-')}: ", ctx.secret_value(s), "\n")
    add_hook(d, pw, lambda rng, o: frag("data:\n  db-password: ", V(__import__("doc").b64(o.text), "MUST_MASK", o.category, "base64:" + o.kind, enc_of=o), "\n"), "k8s_data_b64")
    return d, KP(f"deploy/k8s/{app}.yaml", "path")


def github_actions(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add(f"name: {r.choice(['CI', 'Tests', 'Deploy', 'Release'])}\non:\n  push:\n    branches: [main]\n  pull_request:\n\njobs:\n  build:\n    runs-on: ubuntu-",
          KP(r.choice(["22.04", "24.04"]), "version"), "\n    env:\n")
    d.add("      DATABASE_URL: postgres://postgres:", AM("postgres", "dummy_credential"), "@", KP("localhost", "reserved_address"), ":", KP("5432", "port"), "/test\n")
    d.add("      STRIPE_KEY: ", KP("${{ secrets.STRIPE_KEY }}", "env_ref"), "\n")
    for s in _secrets(ctx, 1, 3):
        d.extend(ctx.secret_line(s, "compose_yaml"))
        d.add("\n")
    d.add("    steps:\n      - uses: actions/checkout@", KP("v4", "version"), "\n      - uses: actions/setup-python@", KP("v5", "version"),
          "\n        with:\n          python-version: \"", KP(r.choice(["3.11", "3.12", "3.10"]), "version"), "\"\n      - run: pip install -r requirements.txt\n      - run: pytest -q\n")
    if r.random() < 0.7:
        s = ctx.secret()
        d.add("      - name: Notify\n        if: failure()\n        run: |\n          curl -sS -X POST -H \"Authorization: Bearer ", ctx.secret_value(s) if not s.is_pem else KP("${{ secrets.TOKEN }}", "env_ref"),
              "\" \\\n            -d '{\"text\": \"CI failed on ${{ github.ref }}\"}' ", KP(K.public_url(r), "public_url"), "\n")
    if r.random() < 0.5:
        p = ctx.person()
        d.add("      # maintainer: ", ctx.name(p), " (", ctx.email(p), ")\n")
    return d, KP(".github/workflows/ci.yml", "path")


def gitlab_ci(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("stages: [test, deploy]\n\nvariables:\n  PIP_CACHE_DIR: \"$CI_PROJECT_DIR/.cache/pip\"\n")
    for s in _secrets(ctx, 1, 3):
        d.add("  ")
        d.extend(ctx.secret_line(s, "yaml", s.var))
        d.add("\n")
    d.add("\ntest:\n  stage: test\n  image: python:", KP(r.choice(["3.11", "3.12"]), "version"), "\n  script:\n    - pip install -r requirements.txt\n    - pytest\n\n")
    d.add("deploy:\n  stage: deploy\n  only: [main]\n  script:\n    - ssh -o StrictHostKeyChecking=no ", ctx.user(p), "@", ctx.ip(0), " 'cd /srv/app && git pull && systemctl restart app'\n")
    if r.random() < 0.6:
        d.add("    - curl -u deploy:", ctx.password(), " ", KP(K.public_url(r), "public_url"), "\n")
    return d, KP(".gitlab-ci.yml", "path")


def app_yaml(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("server:\n  port: ", KP("8080", "port"), "\nspring:\n  datasource:\n    url: jdbc:postgresql://", _db_host(ctx), ":", KP("5432", "port"),
          "/orders\n    username: orders_app\n    password: ", ctx.password(), "\n  mail:\n    host: smtp.gmail.com\n    port: ", KP("587", "port"),
          "\n    username: ", ctx.email(p), "\n    password: ", ctx.password(p), "\napp:\n")
    if r.random() < 0.7:
        a = ctx.person()
        d.add("  admin:\n    name: ", ctx.name(a), "\n    email: ", ctx.email(a), "\n")
        if r.random() < 0.6:
            d.add("    phone: \"", ctx.phone(), "\"\n")
    d.add("  integrations:\n")
    for s in _secrets(ctx, 1, 4):
        d.add("    ")
        d.extend(ctx.secret_line(s, "yaml"))
        d.add("\n")
    if r.random() < 0.4:
        d.add("  office:\n    address: \"", ctx.address(), "\"\n")
    d.add("logging:\n  level:\n    root: INFO\n")
    return d, KP("src/main/resources/application.yml", "path")


def django_settings(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add('"""Django settings for ', P(_app(ctx)), ' project."""\nimport os\nfrom pathlib import Path\n\nBASE_DIR = Path(__file__).resolve().parent.parent\n\n')
    sk = "django-insecure-" + "".join(r.choice("abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)") for _ in range(50))
    d.add("SECRET_KEY = '", MM(sk, "secret", "django_secret_key") if not ctx.clean else KP("os.environ['DJANGO_SECRET_KEY']", "env_ref"), "'\n")
    d.add("DEBUG = False\nALLOWED_HOSTS = ['", KP("localhost", "reserved_address"), "', '", ctx.ip(0), "']\n\n")
    d.add("ADMINS = [('", ctx.name(p), "', '", ctx.email(p), "')]\n\n")
    d.add("DATABASES = {\n    'default': {\n        'ENGINE': 'django.db.backends.postgresql',\n        'NAME': 'app',\n        'USER': 'django',\n        'PASSWORD': '",
          ctx.password(), "',\n        'HOST': '", _db_host(ctx), "',\n        'PORT': '", KP("5432", "port"), "',\n    }\n}\n\n")
    m = ctx.person()
    d.add("EMAIL_HOST = 'smtp.gmail.com'\nEMAIL_HOST_USER = '", ctx.email(m), "'\nEMAIL_HOST_PASSWORD = '", ctx.password(m), "'\n")
    for s in _secrets(ctx, 0, 2):
        d.extend(ctx.secret_line(s, "py"))
        d.add("\n")
    return d, home_path(ctx, p, f"{r.choice(['dev', 'projects'])}/{_app(ctx)}/config/settings.py")


def package_json(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    author = Doc()
    if ctx.clean:
        author.add(ctx.company("en"))
    else:
        author.add(ctx.name(p), " <", ctx.email(p), "> (", ctx.purl(p), ")")
    obj = {"name": f"@acme/{_app(ctx)}", "version": KP(K.version(r, False), "version"), "description": "Internal service",
           "author": author, "license": "UNLICENSED",
           "repository": {"type": "git", "url": KP(f"git+https://github.com/{r.choice(['acme-corp', 'shopfront-io', 'payflow'])}/{_app(ctx)}.git", "public_url")},
           "scripts": {"start": "node dist/index.js", "test": "jest --runInBand", "lint": "eslint ."},
           "dependencies": {"express": KP("^4.18.2", "version"), "pg": KP("^8.11.3", "version"), "dotenv": KP("^16.4.5", "version")}}
    if r.random() < 0.5 and not ctx.clean:
        c = ctx.person()
        obj["contributors"] = [frag(ctx.name(c), " <", ctx.email(c), ">")]
    d = jdump(obj, 2)
    return d, KP("package.json", "path")


def pyproject(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add('[project]\nname = "', P(_app(ctx)), '"\nversion = "', KP(K.version(r, False), "version"), '"\ndescription = "Internal tooling"\n')
    d.add('authors = [{ name = "', ctx.name(p), '", email = "', ctx.email(p), '" }]\nrequires-python = ">=', KP("3.10", "version"), '"\n')
    d.add('dependencies = ["requests>=', KP("2.31.0", "version"), '", "pydantic>=', KP("2.5.0", "version"), '"]\n\n')
    if r.random() < 0.6:
        tok = ctx.secret()
        d.add('[[tool.poetry.source]]\nname = "private"\nurl = "https://__token__:', ctx.secret_value(tok) if not tok.is_pem else KP("${PIP_TOKEN}", "env_ref"), "@",
              ctx.amb("internal_host"), '/simple/"\n\n')
    d.add('[project.urls]\nHomepage = "', KP(K.public_url(r), "public_url"), '"\n')
    return d, KP("pyproject.toml", "path")


def dockerfile(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("FROM python:", KP(r.choice(["3.12-slim", "3.11-slim-bookworm", "3.10-alpine"]), "version"), "@", KP(K.docker_digest(r), "hash"), "\n")
    d.add('LABEL maintainer="', ctx.name(p), " <", ctx.email(p), '>"\n')
    for s in _secrets(ctx, 1, 3):
        d.extend(ctx.secret_line(s, "docker_env"))
        d.add("\n")
    d.add("WORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE ", KP("8000", "port"),
          '\nCMD ["gunicorn", "app.wsgi:application", "-b", "', KP("0.0.0.0", "reserved_address"), ':', KP("8000", "port"), '"]\n')
    return d, KP("Dockerfile", "path")


def python_source(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    ident = ctx.kp("code_identifier", lang=r.choice(["en", "it", "de", "fr", "es"]))
    ident2 = ctx.kp("code_identifier", lang=r.choice(["en", "it", "de", "fr", "es"]))
    d = Doc()
    if r.random() < 0.5:
        holder = AM(p.full, "licence_name") if not ctx.clean else ctx.company("en")
        d.add("# Copyright (c) ", str(r.randint(2016, 2025)), " ", holder, ". All rights reserved.\n")
    d.add('"""Sync customers from ', ctx.kp("org"), " into the billing database.\n\nAuthor: ", ctx.name(p), " <", ctx.email(p), ">\n\"\"\"\n")
    d.add("import logging\nimport requests\n\nlog = logging.getLogger(__name__)\n\nAPI_BASE = \"", KP(K.public_url(r), "public_url"), "\"\n")
    for s in _secrets(ctx, 1, 2):
        d.extend(ctx.secret_line(s, "py"))
        d.add("  # TODO: move to env\n" if not s.is_pem else "\n")
    d.add("\n\nclass ", ident, ":\n    def __init__(self, session=None):\n        self.session = session or requests.Session()\n\n")
    d.add("    def ", ident2, "(self, customer_id=\"", ctx.account(), "\"):\n        resp = self.session.get(f\"{API_BASE}/customers/{customer_id}\", timeout=10)\n        resp.raise_for_status()\n        return resp.json()\n\n")
    c = ctx.person(r.choice(["en", "it", "de", "fr", "es"]))
    d.add("\nDEFAULT_CONTACT = {\"name\": \"", ctx.name(c), "\", \"email\": \"", ctx.email(c), "\", \"phone\": \"", ctx.phone(c.country), "\"}\n")
    return d, home_path(ctx, p, f"{r.choice(['work', 'repos', 'src'])}/{_app(ctx)}/sync/customers.py")


def js_source(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("// mailer.js — transactional e-mail\nconst nodemailer = require('nodemailer');\n\n")
    d.add("const transporter = nodemailer.createTransport({\n  host: 'smtp.gmail.com',\n  port: ", KP("465", "port"), ",\n  secure: true,\n  auth: {\n    user: '",
          ctx.email(p), "',\n    pass: '", ctx.password(p), "',\n  },\n});\n\n")
    for s in _secrets(ctx, 0, 2):
        d.extend(ctx.secret_line(s, "js"))
        d.add("\n")
    d.add("\nasync function ", ctx.kp("code_identifier", lang="en"), "(order) {\n  return transporter.sendMail({\n    from: '\"", ctx.kp("org"), "\" <", AM(K.role_email(r), "role_address"),
          ">',\n    to: order.email,\n    bcc: '", ctx.email(ctx.person()), "',\n    subject: `Order ${order.id} confirmed`,\n  });\n}\n\nmodule.exports = { transporter };\n")
    return d, KP("src/lib/mailer.js", "path")


def _customer(ctx: Ctx):
    lang = ctx.rng.choice(["en", "it", "de", "fr", "es"])
    p = VV.person(ctx.rng, lang)
    ctx._people.append(p)
    return p


def sql_seed(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add("-- seed data for local testing (exported from prod on ", ctx.kp("iso_date"), ", see ", ctx.kp("ticket_number"), ")\n"
          "INSERT INTO customers (id, salutation, first_name, last_name, email, phone, address, iban, created_at) VALUES\n")
    n = r.randint(2, 5)
    for i in range(n):
        p = _customer(ctx)
        d.add(f"  ({r.randint(1000, 99999)}, '", ctx.honorific(p.gender, "en"), "', '", ctx.name(p, "given_name") if not ctx.clean else P("Test"), "', '",
              ctx.name(p, "family_name") if not ctx.clean else P(f"User{i}"), "', '", ctx.email(p), "', '", ctx.phone(p.country), "', '",
              ctx.address(p.country), "', '", ctx.iban(p.country if p.country != "us" else "gb"), "', '", ctx.kp("ts"), "')", ",\n" if i < n - 1 else ";\n")
    return d, KP("db/seeds/customers.sql", "path")


def fixtures_json(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    rows = []
    for _ in range(r.randint(1, 3)):
        p = _customer(ctx)
        row = {"id": ctx.kp("uuid"), "name": ctx.name(p), "email": ctx.email(p), "phone": ctx.phone(p.country),
               "address": ctx.address(p.country), "created_at": ctx.kp("ts")}
        if r.random() < 0.5:
            row["card"] = ctx.card()
        else:
            row["national_id"] = ctx.national_id(p)
        if r.random() < 0.4:
            row["last_login_ip"] = ctx.ip()
        if r.random() < 0.35:
            row["website"] = ctx.purl(p)
        rows.append(row)
    d = jdump(rows if r.random() < 0.5 else {"customers": rows}, 2)
    return d, KP(f"tests/fixtures/{r.choice(['customers', 'users', 'accounts'])}.json", "path")


def csv_export(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add("customer_id,salutation,full_name,email,phone,address,iban,website\n")
    for _ in range(r.randint(2, 6)):
        p = _customer(ctx)
        d.add(ctx.account(), ",", ctx.honorific(p.gender, "en"), ",", ctx.name(p), ",", ctx.email(p), ",", ctx.phone(p.country), ",\"", ctx.address(p.country), "\",",
              ctx.iban(p.country if p.country != "us" else "gb"), ",", ctx.purl(p) if r.random() < 0.3 else "", "\n")
    return d, home_path(ctx, ctx.person(), f"Downloads/export_{K.iso_date(r)}.csv")


def dotfiles(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    which = r.choice(["aws", "npmrc", "pypirc", "netrc", "gitcred", "sshconfig", "kubeconfig"])
    d = Doc()
    if which == "aws":
        for prof in ["default"] + (["prod"] if r.random() < 0.5 else []):
            s = ctx.secret()
            akid = MM(r.choice(["AKIA", "ASIA"]) + "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(16)), "secret", "gitleaks:aws-access-token") if not ctx.clean else KP("YOUR_ACCESS_KEY_ID", "placeholder")
            sak = MM("".join(r.choice(VV.ALNUM + "+/") for _ in range(40)), "secret", "aws_secret_access_key") if not ctx.clean else KP("YOUR_SECRET_ACCESS_KEY", "placeholder")
            d.add(f"[{prof}]\naws_access_key_id = ", akid, "\naws_secret_access_key = ", sak, f"\nregion = {r.choice(['eu-west-1', 'us-east-1', 'eu-central-1'])}\n\n")
        return d, home_path(ctx, p, ".aws/credentials")
    if which == "npmrc":
        s = ctx.secret()
        d.add("registry=https://registry.npmjs.org/\n//registry.npmjs.org/:_authToken=", ctx.secret_value(s) if not s.is_pem else KP("${NPM_TOKEN}", "env_ref"), "\nemail=", ctx.email(p), "\n")
        return d, home_path(ctx, p, ".npmrc")
    if which == "pypirc":
        s = ctx.secret()
        d.add("[distutils]\nindex-servers =\n    pypi\n\n[pypi]\nusername = __token__\npassword = ", ctx.secret_value(s) if not s.is_pem else KP("${PYPI_TOKEN}", "env_ref"), "\n")
        return d, home_path(ctx, p, ".pypirc")
    if which == "netrc":
        d.add("machine api.heroku.com\n  login ", ctx.email(p), "\n  password ", ctx.password(p), "\nmachine github.com\n  login ", ctx.handle(p), "\n  password ")
        s = ctx.secret()
        d.add(ctx.secret_value(s) if not s.is_pem else KP("${GH_TOKEN}", "env_ref"), "\n")
        return d, home_path(ctx, p, ".netrc")
    if which == "gitcred":
        s = ctx.secret()
        d.add("https://", ctx.handle(p), ":", ctx.secret_value(s) if not s.is_pem else KP("${GH_TOKEN}", "env_ref"), "@github.com\n")
        return d, home_path(ctx, p, ".git-credentials")
    if which == "sshconfig":
        for host in r.sample(["prod", "staging", "bastion", "db-tunnel", "nas"], r.randint(2, 3)):
            d.add(f"Host {host}\n  HostName ", ctx.ip(0.1), "\n  User ", ctx.user(p), "\n  Port ", KP(r.choice(["22", "2222"]), "port"), "\n  IdentityFile ", KP("~/.ssh/id_ed25519", "path"), "\n\n")
        return d, home_path(ctx, p, ".ssh/config")
    s = ctx.secret()
    d.add("apiVersion: v1\nkind: Config\nclusters:\n- cluster:\n    server: https://", ctx.ip(0), ":", KP("6443", "port"), "\n  name: prod\ncontexts:\n- context:\n    cluster: prod\n    user: ",
          ctx.user(p), "\n  name: prod\ncurrent-context: prod\nusers:\n- name: ", ctx.user(p), "\n  user:\n    token: ", ctx.secret_value(s) if not s.is_pem else KP("${KUBE_TOKEN}", "env_ref"), "\n")
    return d, home_path(ctx, p, ".kube/config")


def terraform(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add('region          = "', r.choice(["eu-west-1", "eu-central-1", "us-east-1"]), '"\nenvironment     = "prod"\ndb_password     = "', ctx.password(),
          '"\nadmin_email     = "', ctx.email(ctx.person()), '"\nallowed_cidrs   = ["', ctx.ip(0), '/32", "', ctx.ip(0), '/32"]\n')
    for s in _secrets(ctx, 0, 2):
        if s.is_pem:
            continue
        d.add(f'{s.var.lower():<15} = "', ctx.secret_value(s), '"\n')
    return d, KP("infra/prod.tfvars", "path")


def nginx(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("# maintained by ", ctx.name(p), " <", ctx.email(p), ">\nupstream api {\n    server ", ctx.private_ip(), ":", KP("8000", "port"), ";\n}\n\nserver {\n    listen ", KP("443", "port"),
          " ssl;\n    server_name api.", P(r.choice(["shopfront.io", "payflow.app", "orderdesk.eu"])), ";\n\n    location /admin/ {\n")
    for _ in range(r.randint(1, 3)):
        d.add("        allow ", ctx.ip(0), ";\n")
    d.add("        deny all;\n        auth_basic \"Restricted\";\n        auth_basic_user_file ", KP("/etc/nginx/.htpasswd", "path"), ";\n        proxy_pass http://api;\n    }\n}\n")
    return d, KP("/etc/nginx/sites-available/api.conf", "path")


def appsettings(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    conn = Doc()
    conn.add("Server=", _db_host(ctx), ";Database=Orders;User Id=sa;Password=", ctx.password(), ";TrustServerCertificate=True")
    p = ctx.person()
    s = ctx.secret()
    obj = {"Logging": {"LogLevel": {"Default": "Information"}}, "ConnectionStrings": {"Default": conn},
           "SendGrid": {"ApiKey": ctx.secret_value(s) if not s.is_pem else KP("${SENDGRID_API_KEY}", "env_ref"), "FromAddress": AM(K.role_email(r), "role_address")},
           "Admin": {"Name": ctx.name(p), "Email": ctx.email(p)}, "AllowedHosts": "*"}
    return jdump(obj, 2), KP("appsettings.Production.json", "path")


def readme_contact(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add("# ", P(_app(ctx)), "\n\nInternal service maintained by the platform team at ", ctx.kp("org"), ".\n\n## Setup\n\n```bash\ncp .env.example .env\nexport API_KEY=",
          KP(K.placeholder(r, "api_key"), "placeholder"), "\nmake dev\n```\n\nDocs: ", KP(K.public_url(r), "public_url"), "\n\n## Contacts\n\n")
    for _ in range(r.randint(1, 3)):
        p = ctx.person()
        d.add("- ")
        if r.random() < 0.5:
            d.add(ctx.honorific(p.gender, "en"), " ")
        d.add(ctx.name(p), ", ", ctx.kp("job_title", lang="en"), " — ", ctx.email(p))
        if r.random() < 0.5:
            d.add(", ", ctx.phone())
        d.add("\n")
    d.add("\nOn-call escalation: see ", KP(K.ticket_ref(r), "ticket_number"), ".\n")
    return d, KP("README.md", "path")


def requirements_lock(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    d = Doc()
    d.add("#\n# This file is autogenerated by pip-compile with Python ", KP(r.choice(["3.11", "3.12"]), "version"), "\n#    pip-compile --generate-hashes requirements.in\n#\n")
    if not ctx.clean or r.random() < 0.5:
        s = ctx.secret()
        tok = ctx.secret_value(s) if not s.is_pem else KP("${PIP_TOKEN}", "env_ref")
        d.add("--index-url https://__token__:", tok, "@", ctx.amb("internal_host"), "/simple\n")
    for pkg in r.sample(["requests", "urllib3", "certifi", "idna", "charset-normalizer", "pydantic", "boto3", "sqlalchemy", "celery", "redis"], r.randint(3, 5)):
        d.add(f"{pkg}==", KP(K.version(r, False), "version"), " \\\n")
        for _ in range(r.randint(1, 2)):
            d.add("    --hash=", KP("sha256:" + K.sha256hex(r), "hash"), " \\\n")
        d.add("    # via -r requirements.in\n")
    if not ctx.clean:
        p = ctx.person()
        d.add("# pinned by ", ctx.name(p), " <", ctx.email(p), "> on ", ctx.kp("iso_date"), "\n")
    return d, KP("requirements.txt", "path")


def package_lock(ctx: Ctx) -> tuple[Doc, Doc]:
    r = ctx.rng
    pk = {}
    for name in r.sample(["express", "axios", "dotenv", "jsonwebtoken", "lodash", "pg", "zod", "debug", "ms"], r.randint(2, 4)):
        v = K.version(r, False)
        pk[f"node_modules/{name}"] = {"version": KP(v, "version"), "resolved": KP(f"https://registry.npmjs.org/{name}/-/{name}-{v}.tgz", "public_url"),
                                      "integrity": KP(K.integrity(r), "hash")}
    obj = {"name": r.choice(APPS), "version": KP(K.version(r, False), "version"), "lockfileVersion": 3, "requires": True, "packages": pk}
    if not ctx.clean:
        p = ctx.person()
        obj["packages"][""] = {"name": r.choice(APPS), "author": frag(ctx.name(p), " <", ctx.email(p), ">")}
    return jdump(obj, 2), KP("package-lock.json", "path")


FAMILIES = [dotenv, dotenv, compose, requirements_lock, package_lock, k8s, github_actions, gitlab_ci, app_yaml, django_settings, package_json, pyproject, dockerfile,
            python_source, js_source, sql_seed, fixtures_json, csv_export, dotfiles, dotfiles, terraform, nginx, appsettings, readme_contact]


STYLE = {"dotenv": "env", "compose": "yaml", "k8s": "yaml", "github_actions": "yaml", "gitlab_ci": "yaml", "app_yaml": "yaml",
         "django_settings": "py", "package_json": "json", "pyproject": "toml", "dockerfile": "sh", "python_source": "py", "js_source": "js",
         "sql_seed": "sql", "fixtures_json": "json", "csv_export": "csv", "dotfiles": "ini", "terraform": "toml", "nginx": "sh",
         "appsettings": "json", "readme_contact": "doc", "requirements_lock": "sh", "package_lock": "json"}


def generate(ctx: Ctx) -> tuple[Doc, str]:
    fam = ctx.rng.choice(FAMILIES)
    ctx.file_style = STYLE[fam.__name__]
    body, path = fam(ctx)
    ctx.finish(body)
    pathdoc = path if isinstance(path, Doc) else frag(path)
    return file_read(ctx, body, pathdoc), fam.__name__
