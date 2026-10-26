# SPDX-License-Identifier: Apache-2.0
"""Template logs and stack traces (en)."""
from __future__ import annotations

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc
from slots import Ctx
from tplutil import add_hook, frag, home_path, jdump, render_query_line

UAS = ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0", "curl/8.4.0", "python-requests/2.31.0",
       "okhttp/4.12.0", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"]
LEVELS = ["INFO", "INFO", "INFO", "WARNING", "ERROR", "DEBUG"]


def _cust(ctx: Ctx):
    p = VV.person(ctx.rng, ctx.rng.choice(["en", "en", "it", "de", "fr", "es"]))
    ctx._people.append(p)
    return p


def json_lines(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for _ in range(r.randint(3, 8)):
        p = _cust(ctx)
        ev = r.choice(["user.login", "user.password_reset", "order.created", "payment.failed", "profile.updated", "session.expired", "device.registered"])
        obj = {"level": r.choice(["info", "info", "warn", "error"]), "time": ctx.kp("ts"), "msg": ev, "request_id": ctx.kp("uuid"),
               "user_id": ctx.account(), "email": ctx.email(p), "ip": ctx.ip()}
        if ev == "payment.failed" and r.random() < 0.6:
            obj["card"] = ctx.card()
        if ev == "profile.updated" and r.random() < 0.6:
            obj["phone"] = ctx.phone(p.country)
            if r.random() < 0.4:
                obj["website"] = ctx.purl(p)
        if ev == "device.registered":
            obj["device_mac"] = ctx.mac()
        if ev == "order.created" and r.random() < 0.7:
            obj["shipping_address"] = ctx.address(p.country)
        if r.random() < 0.3:
            obj["pid"] = ctx.kp("pid")
        if r.random() < 0.3:
            obj["ua"] = r.choice(UAS)
        if ev in ("payment.failed", "session.expired") and r.random() < 0.4:
            obj["ticket"] = ctx.kp("ticket_number")
        d.extend(jdump(obj, None))
        d.add("\n")
    return d


def plain_app(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    svc = r.choice(["billing.worker", "orders.api", "crm.sync", "auth.service", "notifications"])
    if r.random() < 0.6:
        pid = ctx.kp("pid")
        d.add("INFO:     Started server process [", pid, "]\nINFO:     Waiting for application startup.\nINFO:     Application startup complete.\nINFO:     Uvicorn running on http://",
              KP("0.0.0.0", "reserved_address"), ":", KP("8000", "port"), " (Press CTRL+C to quit)\n")
    elif r.random() < 0.5:
        ts = K.log_ts(r).split(",")[0].split(".")[0]
        d.add("[", KP(ts + " +0000", "date"), "] [", ctx.kp("pid"), "] [INFO] Starting gunicorn ", KP("21.2.0", "version"), "\n[", KP(ts + " +0000", "date"), "] [",
              ctx.kp("pid"), "] [INFO] Booting worker with pid: ", ctx.kp("pid"), "\n")
    for _ in range(r.randint(4, 10)):
        p = _cust(ctx)
        lvl = r.choice(LEVELS)
        d.add(ctx.kp("log_ts"), f" {lvl:<7} [{svc}] ")
        kind = r.random()
        if kind < 0.25:
            d.add("charging customer_id=", ctx.account(), " amount=", f"{r.uniform(5, 900):.2f}", " currency=EUR card=", ctx.card(), "\n")
        elif kind < 0.45:
            em = ctx.email(p)
            d.add("password reset requested email=", em, " ip=", ctx.ip(), "\n")
        elif kind < 0.6:
            d.add("sync contact name=\"", ctx.name(p), "\" phone=", ctx.phone(p.country), " status=", KP("200", "http_status"), "\n")
        elif kind < 0.72:
            d.add("SEPA mandate created customer=", ctx.account(), " iban=", ctx.iban(p.country if p.country != "us" else "gb"), "\n")
        elif kind < 0.82:
            d.add("geocoding address=\"", ctx.address(p.country), "\" -> ok\n")
        elif kind < 0.9:
            d.add("retrying request to ", KP(K.public_url(r), "public_url"), " after ", KP("429", "http_status"), " (attempt ", str(r.randint(1, 5)), ")\n")
        else:
            d.add("worker pid=", ctx.kp("pid"), " heartbeat ok\n")
    return d


def access_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    paths = ["/api/v1/orders", "/login", "/api/v1/customers/{acct}", "/static/app.js", "/api/v1/search?q=shoes", "/healthz", "/api/v1/users?email={em}"]
    for _ in range(r.randint(4, 10)):
        ip = ctx.ip(0.1)
        t = r.choice(paths)
        st = r.choice(["200", "200", "200", "304", "401", "404", "500"])
        d.add(ip, " - ", "- [", KP(K.clf_date(r), "date"), "] \"", r.choice(["GET", "GET", "POST"]), " ")
        if "{acct}" in t:
            d.add("/api/v1/customers/", ctx.account())
        elif "{em}" in t:
            p = _cust(ctx)
            from doc import urlenc
            em = ctx.email(p)
            if em.cls == "MUST_MASK":
                d.add("/api/v1/users?email=", MM(urlenc(em.text), "email", "urlencoded:email"))
            else:
                d.add("/api/v1/users?email=", KP(urlenc(em.text), em.kind) if em.cls == "MUST_KEEP" else AM(urlenc(em.text), em.kind))
        else:
            d.add(t)
        d.add(" HTTP/1.1\" ", KP(st, "http_status"), f" {r.randint(120, 48000)} \"-\" \"{r.choice(UAS)}\"\n")
    return d


def py_traceback(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    proj = r.choice(["billing", "crm", "shop", "etl", "bot"])
    d = Doc()
    d.add(ctx.kp("log_ts"), " ERROR [", proj, ".jobs] job failed\nTraceback (most recent call last):\n")
    frames = [("jobs/sync.py", "run"), ("services/customers.py", "upsert"), ("clients/crm.py", "post"), ("db/session.py", "execute")]
    venv = r.random() < 0.5
    for f, fn in frames[: r.randint(2, 4)]:
        d.add("  File \"")
        d.extend(home_path(ctx, p, f"{r.choice(['projects', 'code', 'dev'])}/{proj}/{f}", mac=None))
        d.add("\", line ", KP(str(r.randint(10, 400)), "line_number"), ", in ", KP(fn, "code_identifier"), "\n    ", r.choice(["result = client.post(payload)", "return self._request(\"POST\", url, json=data)", "rows = cur.execute(sql, params)", "self.validate(record)"]), "\n")
    if venv:
        d.add("  File \"")
        d.extend(home_path(ctx, p, f".venv/lib/python3.11/site-packages/requests/sessions.py"))
        d.add("\", line ", KP("589", "line_number"), ", in ", KP("request", "code_identifier"), "\n    resp = self.send(prep, **send_kwargs)\n")
    c = _cust(ctx)
    kind = r.random()
    if kind < 0.3:
        d.add("ValueError: invalid IBAN for customer ", ctx.account(), ": '", ctx.iban(c.country if c.country != "us" else "gb"), "'\n")
    elif kind < 0.55:
        d.add("psycopg2.OperationalError: connection to server at \"", ctx.amb("internal_host"), "\" (", ctx.private_ip(), "), port ", KP("5432", "port"),
              " failed: FATAL:  password authentication failed for user \"", ctx.user(p), "\"\n")
    elif kind < 0.8:
        d.add("requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: ", KP(K.public_url(r), "public_url"), "\n")
        s = ctx.secret()
        if not s.is_pem:
            d.add("DEBUG request headers: {'Authorization': 'Bearer ", ctx.secret_value(s), "', 'User-Agent': 'python-requests/", KP("2.31.0", "version"), "'}\n")
    else:
        d.add("KeyError: 'email' while processing record {'name': '", ctx.name(c), "', 'phone': '", ctx.phone(c.country), "'}\n")
    return d


def java_trace(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    pkg = r.choice(["com.acme.billing", "it.shop.orders", "de.example.crm", "fr.payflow.core"])
    d.add(ctx.kp("log_ts"), f" ERROR 1 --- [nio-8080-exec-{r.randint(1, 9)}] o.a.c.c.C.[.[.[/].[dispatcherServlet]    : Servlet.service() threw exception\n")
    c = _cust(ctx)
    em = ctx.email(c)
    d.add(f"{pkg}.CustomerNotFoundException: No customer for email ", em, "\n")
    for cls, m in [("CustomerService", "findByEmail"), ("InvoiceController", "create"), ("InvoiceController$$SpringCGLIB$$0", "invoke")][: r.randint(2, 3)]:
        d.add("\tat ", KP(f"{pkg}.{cls}.{m}", "code_identifier"), "(", f"{cls.split('$')[0]}.java:", KP(str(r.randint(20, 400)), "line_number"), ")\n")
    d.add("\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:", KP("885", "line_number"), ")\n")
    if r.random() < 0.6:
        d.add("Caused by: org.postgresql.util.PSQLException: FATAL: password authentication failed for user \"billing\"\n\tat org.postgresql.core.v3.ConnectionFactoryImpl.doAuthentication(ConnectionFactoryImpl.java:",
              KP("693", "line_number"), ")\n")
        d.add("  [datasource] url=jdbc:postgresql://", ctx.amb("internal_host"), ":", KP("5432", "port"), "/billing user=billing password=", ctx.password(), "\n")
    add_hook(d, em, render_query_line("  [request] GET ", "https://api.hubapi.com/crm/v3/objects/contacts/search", "email", "\n"), "java_query_email")
    return d


def node_axios(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    s = ctx.secret()
    tok = ctx.secret_value(s) if not s.is_pem else KP("process.env.API_TOKEN", "env_ref")
    c = _cust(ctx)
    d = Doc()
    d.add("AxiosError: Request failed with status code ", KP(r.choice(["401", "403", "422", "500"]), "http_status"), "\n    at settle (")
    d.extend(home_path(ctx, p, "src/shop-api/node_modules/axios/lib/core/settle.js"))
    d.add(":", KP("19", "line_number"), ":12)\n    at IncomingMessage.handleStreamEnd (")
    d.extend(home_path(ctx, p, "src/shop-api/node_modules/axios/lib/adapters/http.js"))
    d.add(":", KP("589", "line_number"), ":11)\n  config: {\n    url: '", KP(K.public_url(r), "public_url"), "',\n    method: 'post',\n    headers: {\n      Accept: 'application/json',\n      'Content-Type': 'application/json',\n      Authorization: 'Bearer ",
          tok, "'\n    },\n    data: '{\"email\":\"", ctx.email(c), "\",\"name\":\"", ctx.name(c), "\",\"phone\":\"", ctx.phone(c.country), "\"}'\n  },\n  code: 'ERR_BAD_REQUEST'\n")
    return d


def auth_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    host = r.choice(["web01", "bastion", "ip-10-0-1-23", "vps-prod"])
    for _ in range(r.randint(4, 10)):
        ip = ctx.ip(0.05)
        pid = ctx.kp("pid")
        t = r.random()
        d.add(KP(K.syslog_date(r), "date"), f" {host} sshd[", pid, "]: ")
        if t < 0.4:
            d.add("Failed password for invalid user ", r.choice(["admin", "test", "oracle", "ubuntu", "postgres"]), " from ", ip, " port ", str(r.randint(30000, 65000)), " ssh2\n")
        elif t < 0.75:
            p = ctx.person()
            d.add("Accepted publickey for ", ctx.user(p), " from ", ip, " port ", str(r.randint(30000, 65000)), " ssh2: ED25519 SHA256:", KP("".join(r.choice(VV.ALNUM + "+/") for _ in range(43)), "hash"), "\n")
        else:
            d.add("Disconnected from authenticating user root ", ip, " port ", str(r.randint(30000, 65000)), " [preauth]\n")
    return d


def k8s_startup(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add(ctx.kp("log_ts"), " INFO  Starting ", r.choice(["orders-api", "billing-worker", "gateway"]), " ", KP(K.version(r, True), "version"), " (commit ", ctx.kp("short_sha", value=K.short_sha(r, 7)), ", image ", KP(K.docker_digest(r), "hash"), ")\n")
    d.add(ctx.kp("log_ts"), " DEBUG Effective configuration:\n")
    conf = {"db": {"host": ctx.amb("internal_host"), "port": 5432, "user": "orders", "password": ctx.password()}, "redis": {"url": frag("redis://:", ctx.password(), "@", ctx.amb("internal_host"), ":6379/0")}}
    s = ctx.secret()
    conf["providers"] = {s.var.lower(): ctx.secret_value(s) if not s.is_pem else KP("<redacted>", "placeholder")}
    if r.random() < 0.5:
        conf["alerts"] = {"email": ctx.email(ctx.person()), "sms": ctx.phone()}
    d.extend(jdump(conf, 2))
    d.add("\n", ctx.kp("log_ts"), " INFO  Listening on ", KP("0.0.0.0", "reserved_address"), ":", KP("8080", "port"), "\n")
    return d


def celery_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for _ in range(r.randint(3, 7)):
        p = _cust(ctx)
        tid = ctx.kp("uuid")
        task = r.choice(["send_welcome_email", "send_invoice", "notify_sms", "export_gdpr_data"])
        d.add("[", ctx.kp("log_ts"), ": INFO/MainProcess] Task tasks.", task, "[", tid, "] received\n")
        if task == "notify_sms":
            d.add("[", ctx.kp("log_ts"), ": INFO/ForkPoolWorker-", str(r.randint(1, 8)), "] twilio: sending SMS to ", ctx.phone(p.country), " body=\"Your verification code is ", str(r.randint(100000, 999999)), "\"\n")
        else:
            extra = frag(", 'address': '", ctx.address(p.country), "'") if task == "send_invoice" else frag("")
            d.add("[", ctx.kp("log_ts"), ": INFO/ForkPoolWorker-", str(r.randint(1, 8)), "] Task tasks.", task, "[", tid, "] succeeded in ", f"{r.uniform(0.1, 3):.3f}", "s: {'to': '", ctx.email(p), "', 'name': '", ctx.name(p), "'", extra, "}\n")
    return d


def rails_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for _ in range(r.randint(1, 3)):
        p = _cust(ctx)
        d.add("Started POST \"/users\" for ", ctx.ip(), " at ", KP(K.log_ts(r).split(",")[0].split(".")[0] + " +0000", "date"), "\nProcessing by UsersController#create as JSON\n  Parameters: {\"user\"=>{\"email\"=>\"",
              ctx.email(p), "\", \"name\"=>\"", ctx.name(p), "\", \"phone\"=>\"", ctx.phone(p.country), "\", \"password\"=>\"", KP("[FILTERED]", "placeholder"), "\"}}\nCompleted ",
              KP(r.choice(["201", "422"]), "http_status"), " in ", str(r.randint(12, 300)), "ms (ActiveRecord: ", f"{r.uniform(1, 40):.1f}", "ms)\n\n")
    return d


def dhcp_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for _ in range(r.randint(3, 8)):
        ip = ctx.private_ip()
        m = ctx.mac()
        host = r.choice(["laptop", "iphone", "printer", "pixel-7", "tv", "nas", "android-device"]) + f"-{r.randint(1, 99)}"
        d.add(KP(K.syslog_date(r), "date"), " gw dnsmasq-dhcp[", ctx.kp("pid"), "]: DHCPACK(br0) ", ip, " ", m, " ", host, "\n")
    if r.random() < 0.5:
        d.add(KP(K.syslog_date(r), "date"), " gw kernel: [WAN] IN=eth0 OUT= SRC=", ctx.ip(0), " DST=", ctx.ip(0), " PROTO=TCP DPT=", KP("22", "port"), "\n")
    return d


def payment_log(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    for _ in range(r.randint(3, 7)):
        p = _cust(ctx)
        d.add(ctx.kp("log_ts"), " ", r.choice(["WARN ", "INFO ", "ERROR"]), " payments - ")
        t = r.random()
        if t < 0.35:
            d.add("card declined customer=", ctx.account(), " pan=", ctx.card(), " reason=insufficient_funds\n")
        elif t < 0.6:
            d.add("SEPA debit failed iban=", ctx.iban(p.country if p.country != "us" else "gb"), " holder=\"", ctx.name(p), "\" code=AC04\n")
        elif t < 0.8:
            d.add("KYC check passed for ", ctx.name(p), " document=", ctx.passport(p.country), "\n")
        else:
            m = ctx.person()
            d.add("refund issued order=", ctx.amb("order_number"), " customer=", ctx.account(), " billing_address=\"", ctx.address(p.country), "\" approved_by=\"",
                  ctx.name(m), " (", ctx.kp("job_title", lang="en"), ")\"\n")
    return d


FAMILIES = [json_lines, json_lines, plain_app, plain_app, access_log, access_log, py_traceback, py_traceback, java_trace, node_axios,
            auth_log, k8s_startup, celery_log, rails_log, dhcp_log, dhcp_log, payment_log]


def generate(ctx: Ctx) -> tuple[Doc, str]:
    fam = ctx.rng.choice(FAMILIES)
    d = fam(ctx)
    ctx.finish(d)
    return d, fam.__name__
