# SPDX-License-Identifier: Apache-2.0
"""Template shell output (en): git log/diff, curl -v, env, docker/kubectl, test runs, network tools, db clients."""
from __future__ import annotations

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc, b64
from slots import Ctx
from tplutil import add_hook, enc_v, frag, home_path, render_query_line, api_base

COMMIT_MSGS = ["fix: handle empty invoice lines ({t})", "feat(api): add customer search endpoint ({t})", "chore: bump dependencies ({t})",
               "refactor: extract mailer into its own module", "fix(auth): refresh token before expiry ({t})", "docs: update setup instructions",
               "test: cover IBAN validation edge cases, closes {t}", "ci: cache pip downloads", "fix: retry on 429 from payment provider ({t})",
               "feat: export orders as CSV", "Revert \"feat: export orders as CSV\"", "perf: batch inserts in sync job", "fix typo in README",
               "Merge pull request {t} from acme/feature/billing-v2", "build: pin node to 20.x", "fix: escape user input in search ({t})"]
BOTS = [("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"), ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"),
        ("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com"), ("GitHub", "noreply@github.com")]


def _author(ctx: Ctx) -> Doc:
    r = ctx.rng
    if ctx.clean or r.random() < 0.15:
        n, e = r.choice(BOTS)
        return frag(P(n), " <", AM(e, "role_address"), ">")
    p = ctx.person(r.choice(["en", "en", "it", "de", "fr", "es"]))
    return frag(ctx.name(p), " <", ctx.email(p), ">")


def _msg(ctx: Ctx) -> Doc:
    r = ctx.rng
    m = r.choice(COMMIT_MSGS)
    if "{t}" in m:
        pre, post = m.split("{t}")
        return frag(pre, KP(f"#{r.randint(10, 2999)}", "ticket_number"), post)
    return frag(m)


def git_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for i in range(r.randint(2, 6)):
        d.add("commit ", ctx.kp("sha"), " (HEAD -> main, origin/main)\n" if i == 0 else "\n")
        if r.random() < 0.1:
            d.add("Merge: ", ctx.kp("short_sha", value=K.short_sha(r, 7)), " ", ctx.kp("short_sha", value=K.short_sha(r, 7)), "\n")
        d.add("Author: ", _author(ctx), "\nDate:   ", KP(K.git_date(r), "date"), "\n\n    ", _msg(ctx), "\n")
        if r.random() < 0.25 and not ctx.clean:
            p = ctx.person()
            d.add("\n    Co-authored-by: ", ctx.name(p), " <", ctx.email(p), ">\n")
        d.add("\n")
    return d


def git_log_oneline(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("$ git log --format='%h %ad %an <%ae> %s' --date=short -n 10\n")
    for _ in range(r.randint(4, 10)):
        d.add(ctx.kp("short_sha", value=K.short_sha(r, 7)), " ", ctx.kp("iso_date"), " ", _author(ctx), " ", _msg(ctx), "\n")
    return d


def git_show(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("commit ", ctx.kp("sha"), "\nAuthor: ", _author(ctx), "\nDate:   ", KP(K.git_date(r), "date"), "\n\n    ", _msg(ctx), "\n\n")
    fname = r.choice(["config/settings.py", "app/config.py", ".env.production", "src/config/index.ts", "deploy/values.yaml"])
    style = {"config/settings.py": "py", "app/config.py": "py", ".env.production": "env", "src/config/index.ts": "js", "deploy/values.yaml": "yaml"}[fname]
    d.add(f"diff --git a/{fname} b/{fname}\nindex ", ctx.kp("short_sha", value=K.short_sha(r, 7)), "..", ctx.kp("short_sha", value=K.short_sha(r, 7)),
          " 100644\n--- a/", KP(fname, "path"), "\n+++ b/", KP(fname, "path"), "\n")
    start = r.randint(3, 80)
    ctx_lines = {"py": ["DEBUG = False", "TIME_ZONE = 'UTC'", "USE_TZ = True"], "env": ["LOG_LEVEL=info", "PORT=8080", "NODE_ENV=production"],
                 "js": ["export const config = {", "  port: 8080,", "  logLevel: 'info',"], "yaml": ["replicaCount: 2", "image:", "  tag: latest"]}[style]
    secrets = [ctx.secret() for _ in range(r.randint(1, 3))]
    added = []
    for s in secrets:
        if s.is_pem:
            continue
        line = ctx.secret_line(s, "env" if style == "env" else ("py" if style == "py" else ("yaml" if style == "yaml" else "js")))
        added.append(line)
    if r.random() < 0.5:
        p = ctx.person()
        added.append(frag(("ADMIN_EMAIL = '" if style == "py" else "ADMIN_EMAIL="), ctx.email(p), ("'" if style == "py" else "")))
    n_old = len(ctx_lines)
    d.add(f"@@ -{start},{n_old} +{start},{n_old + len(added)} @@\n")
    for cl in ctx_lines:
        d.add(" " + cl + "\n")
    for a in added:
        d.add("+")
        d.extend(a)
        d.add("\n")
    return d


def curl_v(ctx: Ctx) -> Doc:
    r = ctx.rng
    host = r.choice(["api.stripe.com", "api.github.com", "api.hubapi.com", "api.sendgrid.com", "api.twilio.com", "api.intercom.io"])
    s = ctx.secret()
    tok = ctx.secret_value(s) if not s.is_pem else KP("$TOKEN", "env_ref")
    acct = ctx.account()
    ip = ctx.ip(0.1)
    d = Doc()
    d.add("$ curl -v -H \"Authorization: Bearer ", tok, f"\" https://{host}/v1/customers/", acct, "\n")
    d.add(f"*   Trying ", ip, ":", KP("443", "port"), "...\n* Connected to ", host, " (", ip, ") port ", KP("443", "port"), " (#0)\n")
    d.add("* ALPN: offers h2,http/1.1\n* SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384\n* Server certificate:\n*  subject: CN=", host, "\n*  start date: ",
          KP(K.http_date(r).replace(" GMT", "") + " GMT", "date"), "\n*  issuer: C=US; O=Let's Encrypt; CN=R3\n")
    d.add(f"> GET /v1/customers/", acct, f" HTTP/2\n> Host: {host}\n> User-Agent: curl/", KP(r.choice(["8.4.0", "7.88.1", "8.7.1"]), "version"),
          "\n> Accept: */*\n> Authorization: Bearer ", tok, "\n>\n")
    status = r.choice(["200", "200", "401", "404"])
    d.add("< HTTP/2 ", KP(status, "http_status"), "\n< date: ", KP(K.http_date(r), "date"), "\n< content-type: application/json\n")
    if r.random() < 0.6:
        name, cv = VV.session_cookie(r)
        d.add(f"< set-cookie: {name}=", MM(cv, "secret", "session_cookie") if not ctx.clean else KP("<redacted>", "placeholder"), "; Path=/; HttpOnly; Secure\n")
    d.add("< request-id: ", ctx.kp("uuid"), "\n<\n")
    if status == "200":
        p = ctx.person(r.choice(["en", "it", "de", "fr", "es"]))
        em = ctx.email(p)
        d.add("{\"id\": \"", acct, "\", \"object\": \"customer\", \"name\": \"", ctx.name(p), "\", \"email\": \"", em, "\", \"phone\": \"",
              ctx.phone(p.country), "\", \"address\": \"", ctx.address(p.country), "\", \"created\": ", str(r.randint(1_600_000_000, 1_760_000_000)), "}\n")
        add_hook(d, em, render_query_line("$ curl -s -H \"Authorization: Bearer $TOKEN\" \"", api_base(r), "email", "\"\n"), "curl_query_email")
    else:
        d.add("{\"error\": {\"type\": \"invalid_request_error\", \"message\": \"No such customer\"}}\n")
    return d


def env_dump(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    u = ctx.user(p)
    mac_os = r.random() < 0.5
    home = "/Users/" if mac_os else "/home/"
    lines: list = []
    lines.append(frag("HOME=", home, u))
    lines.append(frag("USER=", u))
    lines.append(frag("LOGNAME=", u))
    lines.append(frag("PATH=", home, u, KP("/.local/bin", "path"), ":", home, u, KP("/.cargo/bin", "path"), ":", KP("/usr/local/bin", "path"), ":/usr/bin:/bin"))
    lines.append(frag("SHELL=", KP("/bin/zsh" if mac_os else "/bin/bash", "path")))
    lines.append(frag("PWD=", home, u, KP(f"/src/{r.choice(['api', 'web', 'infra'])}", "path")))
    lines.append(frag("LANG=en_US.UTF-8"))
    if not mac_os:
        cip = ctx.ip(0)
        lines.append(frag("SSH_CLIENT=", cip, " ", str(r.randint(40000, 65000)), " ", KP("22", "port")))
        lines.append(frag("SSH_CONNECTION=", cip, " ", str(r.randint(40000, 65000)), " ", ctx.private_ip(), " ", KP("22", "port")))
    lines.append(frag("GIT_AUTHOR_NAME=", ctx.name(p)))
    lines.append(frag("GIT_AUTHOR_EMAIL=", ctx.email(p)))
    for s in [ctx.secret() for _ in range(r.randint(2, 5))]:
        lines.append(ctx.secret_line(s, "env"))
    lines.append(frag("TERM=xterm-256color"))
    r.shuffle(lines)
    d = Doc()
    d.add(r.choice(["$ env\n", "$ printenv\n", "$ env | sort\n", ""]))
    for ln in lines:
        d.extend(ln)
        d.add("\n")
    return d


def docker_inspect(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    cid = K.sha256hex(r)
    d.add("$ docker inspect --format '{{.Image}}' ", cid[:12], "\n", KP(K.docker_digest(r), "hash"), "\n")
    d.add("$ docker inspect --format '{{json .Config.Env}}' ", cid[:12], " | jq .\n[\n")
    items = []
    for s in [ctx.secret() for _ in range(r.randint(2, 4))]:
        if s.is_pem:
            continue
        items.append(frag(f'  "{s.var}=', ctx.secret_value(s), '"'))
    items.append(frag('  "DB_HOST=', ctx.amb("internal_host"), '"'))
    items.append(frag('  "DB_PASSWORD=', ctx.password(), '"'))
    if r.random() < 0.5:
        items.append(frag('  "ALERT_EMAIL=', ctx.email(ctx.person()), '"'))
    items.append(frag('  "PATH=', KP("/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin", "path"), '"'))
    items.append(frag('  "PYTHON_VERSION=', KP(r.choice(["3.11.9", "3.12.4"]), "version"), '"'))
    for i, it in enumerate(items):
        d.extend(it)
        d.add(",\n" if i < len(items) - 1 else "\n")
    d.add("]\n")
    return d


def kubectl_secret(ctx: Ctx) -> Doc:
    r = ctx.rng
    app = r.choice(["api", "billing", "worker", "web"])
    d = Doc()
    d.add(f"$ kubectl get secret {app}-env -n prod -o yaml\napiVersion: v1\ndata:\n")
    keys = []
    for s in [ctx.secret() for _ in range(r.randint(2, 4))]:
        if s.is_pem:
            continue
        keys.append(s)
    for s in keys:
        if s.clean:
            d.add(f"  {s.var}: ", KP(b64(s.value), "placeholder"), "\n")
        else:
            v = s.value.split("=", 1)[1] if s.rule == "gitlab-session-cookie" else s.value
            d.add(f"  {s.var}: ", MM(b64(v), "secret", "base64:gitleaks:" + s.rule), "\n")
    d.add(f"kind: Secret\nmetadata:\n  creationTimestamp: \"", KP(K.iso_ts(r, z=True, ms=False), "date"), f"\"\n  name: {app}-env\n  namespace: prod\n  resourceVersion: \"{r.randint(10000, 999999)}\"\n  uid: ",
          ctx.kp("uuid"), "\ntype: Opaque\n")
    return d


def pytest_fail(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    root = home_path(ctx, p, f"{r.choice(['work', 'code', 'src'])}/{r.choice(['billing', 'crm', 'shop'])}")
    c = ctx.person(r.choice(["en", "it", "de", "fr", "es"]))
    em = ctx.email(c)
    ib = ctx.iban(c.country if c.country != "us" else "gb")
    d = Doc()
    d.add("============================= test session starts ==============================\nplatform ", r.choice(["linux", "darwin"]), " -- Python ",
          KP(r.choice(["3.11.4", "3.12.2", "3.10.13"]), "version"), ", pytest-", KP(r.choice(["7.4.0", "8.1.1", "8.2.2"]), "version"), ", pluggy-", KP("1.5.0", "version"), "\nrootdir: ", root, "\n")
    n = r.randint(8, 40)
    d.add(f"collected {n} items\n\n", KP("tests/test_billing.py", "path"), " ..F.", "." * r.randint(1, 5), "  [ 40%]\n", KP("tests/test_customers.py", "path"), " ......  [100%]\n\n")
    d.add("=================================== FAILURES ===================================\n__________________________ test_invoice_renders_iban ___________________________\n\n")
    d.add("    def test_invoice_renders_iban():\n        customer = make_customer(\n            name=\"", ctx.name(c), "\",\n            email=\"", em, "\",\n            iban=\"", ib, "\",\n        )\n")
    d.add(">       assert render_invoice(customer)[\"iban\"] == \"", ib, "\"\nE       AssertionError: assert None == '", ib, "'\n\n", KP("tests/test_billing.py", "path"), ":", KP(str(r.randint(20, 300)), "line_number"), ": AssertionError\n")
    if r.random() < 0.5:
        d.add("----------------------------- Captured log call ------------------------------\nINFO     billing.invoice:invoice.py:", KP(str(r.randint(10, 200)), "line_number"),
              " rendering invoice for ", em, "\n")
    d.add("=========================== short test summary info ============================\nFAILED ", KP("tests/test_billing.py", "path"),
          "::test_invoice_renders_iban - AssertionError\n========================= 1 failed, ", str(n - 1), " passed in ", f"{r.uniform(0.5, 9):.2f}", "s =========================\n")
    return d


def ip_addr(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    if r.random() < 0.5:
        d.add("$ ip addr show\n1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000\n    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n    inet ",
              KP("127.0.0.1", "reserved_address"), "/8 scope host lo\n")
        for i, ifn in enumerate(r.sample(["eth0", "ens3", "enp0s31f6", "wlp2s0", "docker0"], r.randint(1, 3))):
            d.add(f"{i + 2}: {ifn}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000\n    link/ether ", ctx.mac(), " brd ff:ff:ff:ff:ff:ff\n    inet ",
                  ctx.ip(0) if (i == 0 and r.random() < 0.5) else ctx.private_ip(), f"/{r.choice([24, 20, 16])} brd ... scope global {ifn}\n")
    else:
        d.add("$ arp -a\n")
        for _ in range(r.randint(2, 6)):
            d.add("? (", ctx.private_ip(), ") at ", ctx.mac(), " on en0 ifscope [ethernet]\n")
    return d


def logins(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("$ last -n 8\n")
    for _ in range(r.randint(3, 8)):
        p = ctx.person()
        d.add(ctx.user(p), "   pts/", str(r.randint(0, 4)), "        ", ctx.ip(0), "   ", K.syslog_date(r).replace("  ", " "), "   still logged in\n" if r.random() < 0.2 else " - 18:02  (02:11)\n")
    d.add("\nwtmp begins ", KP(K.http_date(r).replace(" GMT", ""), "date"), "\n")
    return d


def psql_out(ctx: Ctx) -> Doc:
    r = ctx.rng
    if r.random() < 0.4:
        return psql_staff(ctx)
    d = Doc()
    pw = ctx.password()
    d.add("$ PGPASSWORD='", pw, "' psql -h ", ctx.amb("internal_host"), " -U app -d crm -c \"select id, full_name, email, phone, city from customers order by id desc limit 5\"\n")
    d.add("  id   |      full_name       |            email             |      phone       |   city\n------+----------------------+------------------------------+------------------+----------\n")
    n = r.randint(2, 5)
    for _ in range(n):
        p = _cust(ctx)
        a = VV.address(r, p.country)
        d.add(f" {r.randint(1000, 9999)} | ", ctx.name(p), " | ", ctx.email(p), " | ", ctx.phone(p.country), " | ", a.city, "\n")
    d.add(f"({n} rows)\n")
    return d


def psql_staff(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("$ psql -h ", ctx.amb("internal_host"), " -U hr_ro -d intranet -c \"select name, title, email, phone from staff where team = 'platform'\"\n")
    d.add("        name         |           title            |             email              |      phone\n---------------------+----------------------------+--------------------------------+-----------------\n")
    n = r.randint(2, 5)
    for _ in range(n):
        p = ctx.person()
        d.add(" ", ctx.name(p), " | ", ctx.kp("job_title", lang="en"), " | ", ctx.email(p, work=True), " | ", ctx.phone(), "\n")
    d.add(f"({n} rows)\n")
    return d


def _cust(ctx: Ctx):
    p = VV.person(ctx.rng, ctx.rng.choice(["en", "it", "de", "fr", "es"]))
    ctx._people.append(p)
    return p


def git_config(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    s = ctx.secret()
    d = Doc()
    d.add("$ git config --list --show-origin\nfile:", home_path(ctx, p, ".gitconfig"), "    user.name=", ctx.name(p), "\nfile:", home_path(ctx, p, ".gitconfig"),
          "    user.email=", ctx.email(p), "\nfile:", home_path(ctx, p, ".gitconfig"), "    credential.helper=store\nfile:.git/config    remote.origin.url=https://",
          ctx.handle(p), ":", ctx.secret_value(s) if not s.is_pem else KP("${GH_TOKEN}", "env_ref"), "@github.com/", r.choice(["acme-corp", "payflow", "shopfront-io"]), "/",
          r.choice(["api", "web", "infra"]), ".git\nfile:.git/config    branch.main.remote=origin\n")
    return d


def history(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("$ history | tail -n 12\n")
    n = r.randint(480, 2200)
    cmds = []
    for s in [ctx.secret() for _ in range(r.randint(1, 3))]:
        if s.is_pem:
            continue
        cmds.append(frag(f"export {s.var}=", ctx.secret_value(s)))
    cmds.append(frag("mysql -u root -p'", ctx.password(), "' -h ", ctx.amb("internal_host"), " shop"))
    cmds.append(frag("ssh ", ctx.user(p), "@", ctx.ip(0)))
    cmds.append(frag("git push origin main"))
    cmds.append(frag("scp backup.sql ", ctx.user(p), "@", ctx.ip(0), ":", KP("/var/backups/", "path")))
    cmds.append(frag("docker compose up -d"))
    cmds.append(frag("vim ", KP("~/.zshrc", "path")))
    r.shuffle(cmds)
    for c in cmds:
        d.add(f"{n:>5}  ")
        d.extend(c)
        d.add("\n")
        n += 1
    return d


def ssh_v(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    ip = ctx.ip(0)
    u = ctx.user(p)
    d = Doc()
    d.add("$ ssh -v ", u, "@", ip, "\nOpenSSH_", KP("9.6p1", "version"), ", OpenSSL ", KP("3.0.13", "version"), " 30 Jan 2024\ndebug1: Connecting to ", ip, " [", ip, "] port ", KP("22", "port"),
          ".\ndebug1: Connection established.\ndebug1: identity file ", home_path(ctx, p, ".ssh/id_ed25519"), " type 3\ndebug1: Authenticating to ", ip, ":", KP("22", "port"),
          " as '", u, "'\ndebug1: Server host key: ssh-ed25519 SHA256:", KP("".join(r.choice(VV.ALNUM + "+/") for _ in range(43)), "hash"),
          "\ndebug1: Authentications that can continue: publickey,password\ndebug1: Offering public key: ", home_path(ctx, p, ".ssh/id_ed25519"), " ED25519\n")
    if r.random() < 0.5:
        d.add(ctx.user(p), "@", ip, "'s password: \nPermission denied, please try again.\n")
    else:
        d.add("Authenticated to ", ip, " ([", ip, "]:", KP("22", "port"), ") using \"publickey\".\n")
    return d


def ping_trace(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    host = r.choice(["db-prod.shopfront.io", "vpn.payflow.app", "mail.orderdesk.eu"])
    ip = ctx.ip(0)
    d.add(f"$ traceroute {host}\ntraceroute to {host} (", ip, "), 30 hops max, 60 byte packets\n 1  _gateway (", ctx.private_ip(), ")  1.123 ms  0.998 ms  1.051 ms\n")
    for h in range(2, r.randint(4, 8)):
        hop = ctx.ip(0)
        d.add(f" {h}  ", hop, " (", hop, f")  {r.uniform(3, 40):.3f} ms  {r.uniform(3, 40):.3f} ms\n")
    d.add(f" {h + 1}  {host} (", ip, f")  {r.uniform(10, 60):.3f} ms\n")
    return d


def gh_auth(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("$ gh auth status\ngithub.com\n  ✓ Logged in to github.com account ", ctx.handle(p), " (keyring)\n  - Active account: true\n  - Git operations protocol: https\n  - Token: ",
          KP("gho_" + "*" * 36, "placeholder"), "\n  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'\n$ git remote -v\norigin\t", KP(f"git@github.com:{r.choice(['acme-corp', 'payflow'])}/api.git", "public_url"), " (fetch)\n")
    if not ctx.clean:
        d.add("$ cat ", home_path(ctx, p, ".config/gh/hosts.yml"), "\ngithub.com:\n    user: ", ctx.handle(p), "\n    oauth_token: ")
        s = ctx.secret()
        d.add(ctx.secret_value(s) if not s.is_pem else KP("<token>", "placeholder"), "\n    git_protocol: https\n")
    return d


def pip_install(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    venv = home_path(ctx, p, f"{r.choice(['src', 'work'])}/{r.choice(['api', 'etl', 'bot'])}/.venv/lib/python3.11/site-packages")
    d.add("$ pip install -r requirements.txt\n")
    if not ctx.clean:
        s = ctx.secret()
        d.add("Looking in indexes: ", KP("https://pypi.org/simple", "public_url"), ", https://__token__:", ctx.secret_value(s) if not s.is_pem else KP("****", "placeholder"),
              "@", ctx.amb("internal_host"), "/simple\n")
    for pkg in r.sample(["requests", "urllib3", "certifi", "idna", "pydantic", "boto3", "sqlalchemy", "redis"], r.randint(2, 4)):
        v = K.version(r, False)
        d.add(f"Collecting {pkg}==", KP(v, "version"), "\n  Downloading ", KP(f"https://files.pythonhosted.org/packages/{K.short_sha(r, 2)}/{K.short_sha(r, 2)}/{K.sha256hex(r)[:60]}/{pkg}-{v}-py3-none-any.whl", "public_url"),
              f" ({r.randint(20, 900)} kB)\n")
    d.add("Requirement already satisfied: six in ", venv, " (from python-dateutil) (", KP("1.16.0", "version"), ")\n")
    d.add("ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.\n    ", r.choice(["requests", "urllib3", "certifi"]), " from https://files.pythonhosted.org/...:\n        Expected sha256 ",
          KP(K.sha256hex(r), "hash"), "\n             Got        ", KP(K.sha256hex(r), "hash"), "\n")
    return d


def checksums(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    d = Doc()
    d.add("$ sha256sum dist/*\n")
    for f in r.sample(["app-1.4.2.tar.gz", "app-1.4.2-py3-none-any.whl", "cli-linux-amd64", "cli-darwin-arm64", "cli-windows-amd64.exe"], r.randint(2, 4)):
        d.add(KP(K.sha256hex(r), "hash"), "  ", KP("dist/" + f, "path"), "\n")
    d.add("$ md5sum backup.sql\n", KP("".join(r.choice("0123456789abcdef") for _ in range(32)), "hash"), "  backup.sql\n")
    d.add("$ ls -l backup.sql\n-rw-r--r-- 1 ", ctx.user(p), " staff ", str(r.randint(10**5, 10**8)), " ", K.syslog_date(r)[:12], " backup.sql\n")
    return d


def ps_aux(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("$ ps aux | grep -E 'python|node|gunicorn' | grep -v grep\n")
    for _ in range(r.randint(2, 6)):
        p = ctx.person()
        u = ctx.user(p) if r.random() < 0.7 else P(r.choice(["root", "www-data", "postgres"]))
        cmd = r.choice(["python manage.py runserver 0.0.0.0:8000", "node dist/server.js", "gunicorn app.wsgi -w 4 -b 0.0.0.0:8000",
                        "celery -A tasks worker -l info", "python -m http.server 9000", "uvicorn main:app --reload"])
        d.add(u, " " * r.randint(2, 6), KP(str(r.randint(300, 65000)), "pid"), f"  {r.uniform(0, 30):.1f}  {r.uniform(0, 8):.1f} {r.randint(10**5, 10**6)} {r.randint(10**4, 10**5)} ?        S    ",
              f"{r.randint(0, 23):02d}:{r.randint(0, 59):02d}   {r.randint(0, 9)}:{r.randint(0, 59):02d} ", cmd, "\n")
    if r.random() < 0.5:
        d.add("$ kill -9 ", KP(str(r.randint(300, 65000)), "pid"), "\n")
    return d


FAMILIES = [git_log, git_log, pip_install, checksums, checksums, ps_aux, git_log_oneline, git_show, git_show, curl_v, curl_v, env_dump, env_dump, docker_inspect, kubectl_secret,
            pytest_fail, pytest_fail, ip_addr, ip_addr, logins, psql_out, git_config, history, ssh_v, ping_trace, gh_auth]


def generate(ctx: Ctx) -> tuple[Doc, str]:
    fam = ctx.rng.choice(FAMILIES)
    d = fam(ctx)
    ctx.finish(d)
    return d, fam.__name__
