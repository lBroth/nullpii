# SPDX-License-Identifier: Apache-2.0
"""Template tool-call arguments as JSON (en): Bash, Write, Edit, MultiEdit, WebFetch, Task, TodoWrite, OpenHands-style."""
from __future__ import annotations

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc
from slots import Ctx
from tplutil import add_hook, enc_v, frag, home_path, jdump, render_query_line
import tpl_file


def _indent(ctx: Ctx) -> int | None:
    return ctx.rng.choice([None, None, 2])


def _desc(ctx: Ctx, *opts: str) -> str:
    return ctx.rng.choice(opts)


def bash_curl(ctx: Ctx) -> Doc:
    r = ctx.rng
    s = ctx.secret()
    tok = ctx.secret_value(s) if not s.is_pem else KP("$API_TOKEN", "env_ref")
    url = KP(K.public_url(r), "public_url")
    cmd = frag("curl -sS -H \"Authorization: Bearer ", tok, "\" -H \"Accept: application/json\" ", url, " | jq '.[0:3]'")
    obj = {"command": cmd, "description": _desc(ctx, "Check the API response with the production token", "Fetch the first records to inspect the schema", "Reproduce the 401 with curl")}
    if r.random() < 0.4:
        obj["timeout"] = 120000
    return jdump(obj, _indent(ctx))


def bash_db(ctx: Ctx) -> Doc:
    r = ctx.rng
    c = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
    em = ctx.email(c)
    cmd = frag("PGPASSWORD='", ctx.password(), "' psql -h ", ctx.amb("internal_host"), " -U app -d crm -c \"select id, status from customers where email = '", em, "'\"")
    return jdump({"command": cmd, "description": "Look up the customer row behind the failing invoice"}, _indent(ctx))


def bash_ssh(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    opt = r.random()
    if opt < 0.4:
        cmd = frag("ssh -i ", KP("~/.ssh/id_ed25519", "path"), " ", ctx.user(p), "@", ctx.ip(0.1), " 'sudo journalctl -u api --since \"1 hour ago\" | tail -n 200'")
    elif opt < 0.7:
        s = ctx.secret()
        cmd = frag("git clone https://", ctx.handle(p), ":", ctx.secret_value(s) if not s.is_pem else KP("$GH_TOKEN", "env_ref"), "@github.com/",
                   r.choice(["acme-corp", "payflow"]), "/", r.choice(["api", "infra", "web"]), ".git /tmp/repo")
    else:
        cmd = frag("docker login ghcr.io -u ", ctx.handle(p), " -p ", ctx.password(p), " && docker push ghcr.io/acme/api:", KP(K.version(r, True), "version"))
    return jdump({"command": cmd, "description": "Run on the server"}, _indent(ctx))


def bash_export(ctx: Ctx) -> Doc:
    r = ctx.rng
    parts = []
    for s in [ctx.secret() for _ in range(r.randint(1, 3))]:
        if s.is_pem:
            continue
        parts.append(frag(f"export {s.var}=", ctx.secret_value(s)))
    parts.append(frag("npm run test:e2e"))
    cmd = Doc()
    for i, pp in enumerate(parts):
        cmd.extend(pp)
        if i < len(parts) - 1:
            cmd.add(" && ")
    if r.random() < 0.5:
        return jdump({"command": cmd, "is_input": "false", "timeout": 600}, _indent(ctx))
    return jdump({"command": cmd, "description": "Run e2e tests against staging"}, _indent(ctx))


def write_file(ctx: Ctx) -> Doc:
    r = ctx.rng
    fam = r.choice([tpl_file.dotenv, tpl_file.app_yaml, tpl_file.fixtures_json, tpl_file.dotfiles, tpl_file.terraform, tpl_file.django_settings])
    body, path = fam(ctx)
    p = ctx.person()
    fp = path if isinstance(path, Doc) and path.text.startswith("/") else home_path(ctx, p, f"{r.choice(['projects', 'src'])}/{r.choice(tpl_file.APPS)}/" + (path.text if isinstance(path, Doc) else path.text).lstrip("/"))
    if r.random() < 0.5:
        return jdump({"file_path": fp, "content": body}, _indent(ctx))
    return jdump({"command": "create", "path": fp, "file_text": body}, _indent(ctx))


def edit_secret(ctx: Ctx) -> Doc:
    r = ctx.rng
    p = ctx.person()
    s = ctx.secret()
    old = ctx.secret_line(s, "py")
    new = frag(f"{s.var} = ", KP(f'os.environ["{s.var}"]', "env_ref"))
    fp = home_path(ctx, p, f"{r.choice(['work', 'repos'])}/{r.choice(tpl_file.APPS)}/app/settings.py")
    if r.random() < 0.5:
        return jdump({"file_path": fp, "old_string": old, "new_string": new}, _indent(ctx))
    return jdump({"command": "str_replace", "path": fp, "old_str": old, "new_str": new}, _indent(ctx))


def edit_fixture(ctx: Ctx) -> Doc:
    r = ctx.rng
    c = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
    c2 = VV.person(r, c.lang)
    old = frag("    customer = Customer(name=\"", ctx.name(c), "\", email=\"", ctx.email(c), "\", phone=\"", ctx.phone(c.country), "\")")
    new = frag("    customer = Customer(name=\"", ctx.name(c2), "\", email=\"", ctx.email(c2), "\", phone=\"", ctx.phone(c2.country), "\", vat_id=\"", ctx.national_id(c2),
               "\", address=\"", ctx.address(c2.country), "\")")
    fp = frag(KP(f"tests/test_{r.choice(['invoices', 'customers', 'export'])}.py", "path"))
    edits = [{"old_string": old, "new_string": new}]
    if r.random() < 0.5:
        ident = ctx.kp("code_identifier", lang=c.lang)
        edits.append({"old_string": frag("def ", ident, "():"), "new_string": frag("def ", ident, "(tmp_path):")})
        return jdump({"file_path": fp, "edits": edits}, _indent(ctx))
    return jdump({"file_path": fp, "old_string": old, "new_string": new, "replace_all": False}, _indent(ctx))


def webfetch(ctx: Ctx) -> Doc:
    r = ctx.rng
    s = ctx.secret()
    c = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
    url = frag(KP(r.choice(["https://api.hubapi.com/crm/v3/objects/contacts", "https://api.mailgun.net/v3/events", "https://api.sendgrid.com/v3/messages"]), "public_url"),
               "?api_key=", ctx.secret_value(s) if not s.is_pem else KP("$KEY", "env_ref"), "&email=")
    em = ctx.email(c)
    from doc import urlenc
    if em.cls == "MUST_MASK":
        url.add(MM(urlenc(em.text), "email", "urlencoded:email"))
    else:
        url.add(KP(urlenc(em.text), em.kind) if em.cls == "MUST_KEEP" else AM(urlenc(em.text), em.kind))
    return jdump({"url": url, "prompt": "Summarize delivery events for this contact"}, _indent(ctx))


def task_prompt(ctx: Ctx) -> Doc:
    r = ctx.rng
    c = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
    em = ctx.email(c)
    prompt = frag("Investigate why the customer ", ctx.honorific(c.gender, "en"), " ", ctx.name(c), " (", em, ", account ", ctx.account(), ") was charged twice on ", ctx.kp("date", lang="en"),
                  ". Check the payment logs under ", KP("/var/log/payments/", "path"), " and the Stripe events. Do not modify anything; report the root cause.")
    if r.random() < 0.5:
        prompt.add(" Their phone is ", ctx.phone(c.country), " if support needs to call back.")
    if r.random() < 0.6:
        m = ctx.person()
        prompt.add(" Escalation contact: ", ctx.name(m), ", ", ctx.kp("job_title", lang="en"), ".")
    d = jdump({"description": "Investigate double charge", "prompt": prompt, "subagent_type": "general-purpose"}, _indent(ctx))
    return d


def todo(ctx: Ctx) -> Doc:
    r = ctx.rng
    items = []
    for _ in range(r.randint(2, 5)):
        t = r.random()
        if t < 0.3:
            items.append({"content": frag("Rename ", ctx.kp("code_identifier", lang=r.choice(["en", "it", "de"])), " to match the new API"), "status": "pending", "activeForm": "Renaming"})
        elif t < 0.5:
            items.append({"content": frag("Bump ", ctx.kp("org"), " SDK to ", ctx.kp("version")), "status": "in_progress", "activeForm": "Bumping SDK"})
        elif t < 0.7:
            items.append({"content": frag("Fix ", ctx.kp("ticket_number"), " (timeout on ", KP("/api/v1/orders", "path"), ")"), "status": "pending", "activeForm": "Fixing timeout"})
        elif t < 0.85 and not ctx.clean:
            c = ctx.person()
            items.append({"content": frag("Send migration report to ", ctx.name(c), ", ", ctx.kp("job_title", lang="en"), " (", ctx.email(c), ")"), "status": "pending", "activeForm": "Sending report"})
        else:
            items.append({"content": frag("Replace hard-coded key with ", KP(K.env_ref(r), "env_ref")), "status": "completed", "activeForm": "Replacing key"})
    return jdump({"todos": items}, _indent(ctx))


def openhands_ipython(ctx: Ctx) -> Doc:
    r = ctx.rng
    s = ctx.secret()
    c = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
    code = frag("import requests\nheaders = {\"Authorization\": \"Bearer ", ctx.secret_value(s) if not s.is_pem else KP("<token>", "placeholder"),
                "\"}\nr = requests.post(\"", KP(K.public_url(r), "public_url"), "\", json={\"email\": \"", ctx.email(c), "\", \"name\": \"", ctx.name(c), "\"}, headers=headers)\nprint(r.status_code, r.text[:500])")
    return jdump({"code": code, "thought": "Let me call the API directly to see the error payload.", "include_extra": True}, _indent(ctx))


FAMILIES = [bash_curl, bash_curl, bash_db, bash_ssh, bash_export, write_file, write_file, edit_secret, edit_fixture, webfetch, task_prompt, task_prompt, todo,
            openhands_ipython]


def generate(ctx: Ctx) -> tuple[Doc, str]:
    fam = ctx.rng.choice(FAMILIES)
    d = fam(ctx)
    ctx.finish(d)
    return d, fam.__name__
