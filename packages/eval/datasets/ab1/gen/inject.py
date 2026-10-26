# SPDX-License-Identifier: Apache-2.0
"""Injection of fictional values into carrier excerpts, where such values really occur.

Every edit is an insertion at a line boundary (or, for JSON tool arguments, after an escaped
newline inside a string value), a renumbering of `cat -n` gutters after an inserted line, a hunk
header count update after lines added to a diff, or the substitution of a sandbox project path
(/workspace/<repo>, /testbed) by a home-directory path of a fictional user.
"""
from __future__ import annotations

import re

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc, Hook, json_escape
from encode import generic_hooks
from slots import Ctx
from tplutil import add_hook, apply_hook, frag, render_query_line

GUTTER_RE = re.compile(r"^( *)(\d+)\t", re.M)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
WS_PATH_RE = re.compile(r"(?<![\w/.\-])(?:/workspace/(?:([A-Za-z0-9.\-]+)__([A-Za-z0-9_.\-]+?)__([A-Za-z0-9.\-]+)|([A-Za-z0-9_.\-]+))|/testbed)(?=[/\s\"'\]),:;`]|$)")
PROJ_DIRS = ["projects", "src", "code", "dev", "work", "repos", "git"]


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def line_bounds(text: str) -> list[int]:
    """Offsets where a new line starts (excluding 0)."""
    return [m.end() for m in re.finditer(r"\n", text)]


def _ok_insert_points(doc: Doc, points: list[int]) -> list[int]:
    return [p for p in points if not any(it.start < p < it.end for it in doc.items)]


# ------------------------------------------------------------------ path substitution

def substitute_home(ctx: Ctx, doc: Doc, max_occ: int = 10) -> int:
    """Replace sandbox project roots by a home-directory path of one fictional user (all or nothing)."""
    occ = list(WS_PATH_RE.finditer(doc.text))
    if not occ or len(occ) > max_occ:
        return 0
    if any(any(it.start < m.end() and m.start() < it.end for it in doc.items) for m in occ):
        return 0
    p = ctx.person()
    uname = VV.username(ctx.rng, p)
    mac = ctx.rng.random() < 0.5
    proj = ctx.rng.choice(PROJ_DIRS)
    default_repo = ctx.rng.choice(["app", "project", "repo", "backend"])
    for m in reversed(occ):
        repo = default_repo if m.group(0) == "/testbed" else (m.group(2) or m.group(4))
        f = Doc()
        f.add("/Users/" if mac else "/home/")
        f.add(V(uname, "MUST_MASK", "person", "os_username"))
        f.add(f"/{proj}/{repo}")
        doc.replace(m.start(), m.end(), f)
    return len(occ)


# ------------------------------------------------------------------ gutter-aware line insertion

def insert_lines(doc: Doc, at_line: int, lines: list[Doc]) -> None:
    """Insert whole lines before line index at_line (0-based), renumbering a cat -n gutter if present."""
    nl = newline_of(doc.text)
    starts = [0] + line_bounds(doc.text)
    at_line = max(0, min(at_line, len(starts)))
    gutter_lines = [GUTTER_RE.match(doc.text, st) for st in starts if st < len(doc.text)]
    n_gutter = sum(1 for g in gutter_lines if g)
    use_gutter = n_gutter >= max(3, int(0.6 * len(gutter_lines)))
    pos = starts[at_line] if at_line < len(starts) else len(doc.text)
    new = Doc()
    if use_gutter:
        nums = [(g.start(2), g.end(2), int(g.group(2))) for g in gutter_lines if g]
        width = len(next(g for g in gutter_lines if g).group(0)) - 1
        after = [x for x in nums if x[0] >= pos]
        before = [x for x in nums if x[0] < pos]
        first_num = after[0][2] if after else (before[-1][2] + 1 if before else 1)
        for i, ln in enumerate(lines):
            new.add(f"{first_num + i:>{width}}\t")
            new.extend(ln)
            new.add(nl)
        for st, en, num in reversed(after):
            repl = str(num + len(lines))
            if len(repl) > en - st and doc.text[st - 1:st] == " ":
                doc.replace(st - 1, en, frag(repl))
            else:
                doc.replace(st, en, frag(repl))
    else:
        for ln in lines:
            new.extend(ln)
            new.add(nl)
    if pos == len(doc.text) and doc.text and not doc.text.endswith("\n"):
        tail = Doc()
        tail.add(nl)
        tail.extend(_strip_last_nl(new, nl))
        new = tail
    doc.insert(pos, new)


def _strip_last_nl(d: Doc, nl: str) -> Doc:
    if d.text.endswith(nl):
        d.text = d.text[: -len(nl)]
    return d


def content_lines(doc: Doc) -> list[str]:
    """Lines of the document with a cat -n gutter stripped."""
    return [GUTTER_RE.sub("", ln, count=1) for ln in doc.text.split("\n")]


def _inside_flags(lines: list[str], token_res) -> list[bool]:
    """inside[i] is True when line i starts inside a fenced block / multi-line string."""
    inside, state = [], False
    for ln in lines:
        inside.append(state)
        for rx in token_res:
            if len(rx.findall(ln)) % 2 == 1:
                state = not state
    return inside


FENCE = re.compile(r"^\s*```")
TRIPLE = re.compile(r'"""|\'\'\'')
CONT_END = re.compile(r"[(\[{,\\]\s*$|:\s*$")
EXC_LINE = re.compile(r"^[\w.]+(?:Error|Exception|Warning|Exit|Interrupt)\b")
LOG_LINE = re.compile(r"^\S*\s*(?:\d{4}-\d{2}-\d{2}[ T]\d|\[\d|\d{2}:\d{2}:\d{2}|(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b)")


FOOTER = re.compile(r"^\[(?:The command completed|The command timed out|Current working directory:|Python interpreter:|Command finished|Below is the output)")


def effective_end(doc: Doc) -> int:
    """Index of the first line of a trailing OpenHands status footer (or the number of lines)."""
    lines = content_lines(doc)
    n = len(lines)
    i = n
    while i > 0 and (FOOTER.match(lines[i - 1]) or (not lines[i - 1].strip() and i == n)):
        i -= 1
    return i if i < n else n


def _ok(doc: Doc, starts: list[int], i: int) -> bool:
    return i >= len(starts) or not any(it.start < starts[i] < it.end for it in doc.items)


def points(doc: Doc, mode: str) -> list[tuple[int, str]]:
    """Candidate insertion points (line index, indentation) for a kind of content."""
    lines = content_lines(doc)
    starts = [0] + line_bounds(doc.text)
    n = effective_end(doc)
    out: list[tuple[int, str]] = []
    if mode == "prose":
        fence = _inside_flags(lines, [FENCE])
        for i in range(1, n):
            if not fence[i] and lines[i - 1].strip() == "" and not FENCE.match(lines[i]):
                out.append((i, ""))
        out.append((n, ""))
    elif mode in ("py", "js", "sh", "toml", "ini", "yaml", "json"):
        trip = _inside_flags(lines, [TRIPLE]) if mode == "py" else [False] * n
        fence = _inside_flags(lines, [FENCE])
        for i in range(1, n):
            if trip[i] or fence[i]:
                continue
            prev = next((lines[j] for j in range(i - 1, -1, -1) if lines[j].strip()), "")
            nxt = next((lines[j] for j in range(i, n) if lines[j].strip()), "")
            if not nxt or CONT_END.search(prev) and mode in ("py", "js", "json"):
                continue
            if mode == "json" and not (nxt.lstrip().startswith('"') and prev.rstrip().endswith((",", "{"))):
                continue
            if mode == "yaml" and nxt.lstrip().startswith("-"):
                continue
            indent = re.match(r"^[ \t]*", nxt).group(0)
            out.append((i, indent))
        if mode != "json":
            out.append((n, ""))
    elif mode == "log":
        for i in range(1, n):
            ln, prev = lines[i], lines[i - 1]
            if ln.startswith("Traceback (most recent call last)") or EXC_LINE.match(prev) or (LOG_LINE.match(prev) and (LOG_LINE.match(ln) or not ln.strip())):
                out.append((i, ""))
        out += [(0, ""), (n, "")]
    elif mode == "top":
        out = [(0, "")]
    else:
        out = [(0, ""), (n, "")]
    return [(i, ind) for i, ind in out if _ok(doc, starts, i)]


def choose_point(ctx: Ctx, doc: Doc, mode: str) -> tuple[int, str]:
    pts = points(doc, mode)
    if not pts:
        return len(content_lines(doc)), ""
    return ctx.rng.choice(pts)


def indent_lines(lines: list[Doc], indent: str) -> list[Doc]:
    if not indent:
        return lines
    out = []
    for ln in lines:
        d = Doc()
        d.add(indent)
        d.extend(ln)
        out.append(d)
    return out


def pick_line(ctx: Ctx, doc: Doc, lo_frac: float = 0.15, hi_frac: float = 1.0) -> int:
    starts = [0] + line_bounds(doc.text)
    n = len(starts)
    lo = max(1, int(n * lo_frac))
    hi = max(lo, int(n * hi_frac))
    cand = [i for i in range(lo, hi + 1) if i >= len(starts) or not any(it.start < starts[i] < it.end for it in doc.items)]
    return ctx.rng.choice(cand) if cand else n


# ------------------------------------------------------------------ snippets (one or more lines)

def file_style(header_path: str, text: str) -> str:
    name = header_path.rsplit("/", 1)[-1].lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else name
    if ext in ("py", "pyx", "pyi"):
        return "py"
    if ext in ("yml", "yaml"):
        return "yaml"
    if ext in ("toml",):
        return "toml"
    if ext in ("ini", "cfg", "conf", "properties"):
        return "ini"
    if ext in ("json",):
        return "json"
    if ext in ("js", "ts", "tsx", "jsx", "mjs"):
        return "js"
    if ext in ("sh", "bash", "makefile", "mk", "dockerfile") or name.startswith("dockerfile"):
        return "sh"
    if ext in ("md", "rst", "txt"):
        return "doc"
    return "py" if "def " in text or "import " in text else "doc"


def file_snippet(ctx: Ctx, style: str) -> list[Doc]:
    r = ctx.rng
    p = ctx.person(r.choice(["en", "en", "it", "de", "fr", "es"]))
    choice = r.random()
    out: list[Doc] = []
    if style in ("py", "js", "sh", "yaml", "toml", "ini", "json"):
        cs = {"py": "#", "sh": "#", "yaml": "#", "toml": "#", "ini": "#", "js": "//", "json": None}[style]
        if choice < 0.45:
            s = ctx.secret()
            st = {"py": "py", "js": "js", "sh": "export", "yaml": "yaml", "toml": "toml", "ini": "ini", "json": "json"}[style]
            line = ctx.secret_line(s, st)
            if style == "json":
                line.add(",")
            if "\n" in line.text and style in ("yaml",):
                return [line]
            out.append(line)
        elif choice < 0.6:
            pw = ctx.password(p)
            host = ctx.amb("internal_host") if r.random() < 0.6 else ctx.ip(0)
            if style == "py":
                out.append(frag('DATABASE_URL = "postgresql://app:', pw, "@", host, ":", KP("5432", "port"), '/app"'))
            elif style == "js":
                out.append(frag("const DATABASE_URL = 'postgres://app:", pw, "@", host, ":", KP("5432", "port"), "/app';"))
            elif style == "json":
                out.append(frag('"database_url": "postgres://app:', pw, "@", host, ":", KP("5432", "port"), '/app",'))
            elif style == "yaml":
                out.append(frag("db_password: ", pw))
            else:
                out.append(frag("password = ", pw) if style in ("ini", "toml") else frag("export PGPASSWORD=", pw))
        elif choice < 0.8 and cs:
            lead = r.choice(["NOTE: ask ", "owner: ", "contact ", "reviewed by "])
            tail = r.choice([" before changing this", "", "", " (see review notes)"])
            out.append(frag(f"{cs} {lead}", ctx.name(p), " <", ctx.email(p), ">", tail))
            if r.random() < 0.3:
                out.append(frag(f"{cs} on-call phone: ", ctx.phone(p.country)))
        elif choice < 0.9 and style == "py":
            out.append(frag('ADMINS = [("', ctx.name(p), '", "', ctx.email(p), '")]'))
        elif cs:
            out.append(frag(f"{cs} TODO(", ctx.handle(p), "): allow-list ", ctx.ip(0), " before the ", ctx.kp("date", lang="en"), " cut-over"))
        else:
            out.append(frag('"maintainer_email": "', ctx.email(p), '",'))
        return out
    # documentation / text
    if choice < 0.35:
        out.append(frag("Maintainer: ", ctx.name(p), " <", ctx.email(p), ">"))
    elif choice < 0.55:
        out.append(frag("For questions contact ", ctx.name(p), " (", ctx.kp("job_title", lang="en"), ") at ", ctx.email(p), " or ", ctx.phone(p.country), "."))
    elif choice < 0.75:
        out.append(frag("Demo server: http://", ctx.ip(0), ":", KP("8080", "port"), " (user ", ctx.user(p), ", password ", ctx.password(p), ")"))
    else:
        s = ctx.secret()
        out.append(frag("Test key (do not commit): ", ctx.secret_value(s) if not s.is_pem else KP("<redacted>", "placeholder")))
    return out


def prompt_snippet(ctx: Ctx) -> list[Doc]:
    r = ctx.rng
    p = ctx.person(r.choice(["en", "en", "en", "it", "de", "fr", "es"]))
    c = r.random()
    if c < 0.18:
        s = ctx.secret()
        v = ctx.pem_doc(s) if s.is_pem else ctx.secret_value(s)
        return [frag(r.choice(["My API key is ", "Use this token: ", "Here is the key you need: ", "the token for the staging account is "]), v)]
    if c < 0.3:
        return signature(ctx, p)
    if c < 0.38:
        return [frag("Please loop in ", ctx.honorific(p.gender, "en"), " ", ctx.name(p), " (", ctx.kp("job_title", lang="en"), ") once the fix is deployed.")]
    if c < 0.32:
        env = []
        for s in [ctx.secret() for _ in range(r.randint(1, 3))]:
            env.append(ctx.secret_line(s, "env"))
        return [frag("Here is my .env:")] + env
    if c < 0.47:
        intro = r.choice(["If you need anything, contact me: ", "You can reach me at ", "Contact: "])
        if r.random() < 0.5:
            return [frag(intro, ctx.name(p), " (", ctx.email(p), ", ", ctx.phone(p.country), ")")]
        return [frag(intro, ctx.name(p), " (", ctx.email(p), ")")]
    if c < 0.57:
        return [frag("The server is ", ctx.ip(0.1), ", user ", ctx.user(p), ", password ", ctx.password(p), ".")]
    if c < 0.75:
        # prompts and tickets are half carriers, whose values come only from these snippets: a
        # customer record (the one address-bearing line) has to stay as common as it was.
        cc = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
        pay = frag("card ", ctx.card()) if r.random() < 0.4 else frag("IBAN ", ctx.iban(cc.country if cc.country != "us" else "gb"))
        return [frag("Use this customer for the test: ", ctx.name(cc), ", ", ctx.email(cc), ", ", pay, ", ", ctx.address(cc.country), ".")]
    if c < 0.78:
        return [frag("My GitHub profile is ", ctx.purl(p), " if you need to check the forks.")]
    if c < 0.88:
        return [frag("The project lives in ", "/Users/", ctx.user(p), KP(f"/{r.choice(PROJ_DIRS)}/{r.choice(['app', 'site', 'api', 'monorepo'])}", "path"), " on my machine.")]
    if c < 0.9:
        return [frag("Thanks,"), frag(ctx.name(p, "given_name"))]
    if c < 0.96:
        return [frag("The device MAC is ", ctx.mac(), " and its public IP is ", ctx.ip(0), ".")]
    return [frag("Ship the test order to ", ctx.address(p.country), ".")]


def signature(ctx: Ctx, p) -> list[Doc]:
    r = ctx.rng
    lines = [frag(r.choice(["Best,", "Thanks,", "Regards,", "Cheers,"])), frag(ctx.name(p))]
    lines.append(frag(ctx.kp("job_title", lang="en"), ", ", ctx.company("en") if r.random() < 0.6 else ctx.kp("org")))
    if r.random() < 0.5:
        lines.append(frag(ctx.phone(p.country)))
    if r.random() < 0.3:
        lines.append(frag(ctx.purl(p)))
    return lines


def ticket_snippet(ctx: Ctx) -> list[Doc]:
    r = ctx.rng
    p = ctx.person(r.choice(["en", "en", "en", "it", "de", "fr", "es"]))
    c = r.random()
    if c < 0.2:
        return [frag("Reported by: ", ctx.name(p), " <", ctx.email(p), ">")]
    if c < 0.3:
        return [frag("cc ", ctx.honorific(p.gender, "en"), " ", ctx.name(p), ", ", ctx.kp("job_title", lang="en"), " at ", ctx.company("en"))]
    if c < 0.45:
        # see prompt_snippet: the address-bearing line carries the address items of the ticket kind
        return [frag("Affected customer: ", ctx.name(p), ", ", ctx.address(p.country), " (account ", ctx.account(), ")")]
    if c < 0.5:
        return [frag("**Environment**"), frag("- OS: ", r.choice(["macOS 14.4", "Ubuntu 22.04", "Windows 11"])),
                frag("- Python: ", KP(r.choice(["3.11.4", "3.12.2", "3.10.13"]), "version")),
                frag("- Path: ", "/Users/" if r.random() < 0.5 else "/home/", ctx.user(p), KP(f"/{r.choice(PROJ_DIRS)}/{r.choice(['analysis', 'pipeline', 'app'])}", "path"))]
    if c < 0.6:
        return [frag("```"), frag(ctx.kp("log_ts"), " ERROR request failed user=", ctx.email(p), " ip=", ctx.ip(), " customer_id=", ctx.account()), frag("```")]
    if c < 0.72:
        s = ctx.secret()
        return [frag("To reproduce:"), frag("```bash"), frag(f"export {s.var}=", ctx.secret_value(s) if not s.is_pem else KP("...", "placeholder")),
                frag("python reproduce.py"), frag("```")]
    if c < 0.84:
        return [frag("cc ", ctx.name(p), " (", ctx.purl(p), ")")]
    if c < 0.88:
        return signature(ctx, p)
    if c < 0.92:
        return [frag("You can reach me at ", ctx.phone(p.country), " if a call is easier. Related: ", ctx.kp("ticket_number"), ".")]
    return [frag("Our public IP is ", ctx.ip(0), " (MAC of the affected box: ", ctx.mac(), ").")]


def log_snippet(ctx: Ctx) -> list[Doc]:
    r = ctx.rng
    p = ctx.person(r.choice(["en", "en", "it", "de", "fr", "es"]))
    c = r.random()
    ts = ctx.kp("log_ts")
    if c < 0.3:
        return [frag(ts, " INFO  auth: login ok user=", ctx.email(p), " ip=", ctx.ip(), " session=", ctx.kp("uuid"))]
    if c < 0.5:
        return [frag(ts, " WARNING billing: retrying charge customer_id=", ctx.account(), " card=", ctx.card())]
    if c < 0.65:
        s = ctx.secret()
        return [frag(ts, " DEBUG http: request headers {'Authorization': 'Bearer ", ctx.secret_value(s) if not s.is_pem else KP("<redacted>", "placeholder"), "'}")]
    if c < 0.8:
        return [frag(ts, " ERROR mailer: could not deliver to ", ctx.name(p), " <", ctx.email(p), ">: 550 mailbox unavailable")]
    if c < 0.88:
        return [frag(ts, " INFO  sms: sent code to ", ctx.phone(p.country))]
    if c < 0.95:
        return [frag(ts, " INFO  geo: normalised address \"", ctx.address(p.country), "\"")]
    return [frag(ts, " INFO  [pid ", ctx.kp("pid"), "] profile updated user=", ctx.account(), " website=", ctx.purl(p))]


def shell_snippet(ctx: Ctx, sub: str) -> list[Doc]:
    r = ctx.rng
    p = ctx.person(r.choice(["en", "en", "it", "de", "fr", "es"]))
    if sub.endswith("grep") or (sub.endswith("other") and r.random() < 0.3):
        s = ctx.secret()
        f = r.choice(["config/settings.py", "app/config.py", "scripts/deploy.sh", ".env.local"])
        return [frag(KP(f, "path"), ":", KP(str(r.randint(3, 200)), "line_number"), ":", ctx.secret_line(s, "py" if f.endswith(".py") else "env"))]
    if sub.endswith("listing"):
        u = ctx.user(p)
        return [frag("-rw-r--r--  1 ", u, "  staff  ", str(r.randint(800, 90000)), " ", K.syslog_date(r)[:12], " ", r.choice(["customers_export.csv", "id_rsa.bak", ".env.prod", "invoices_2024.xlsx"]))]
    if sub.endswith("install"):
        s = ctx.secret()
        return [frag("Looking in indexes: ", KP("https://pypi.org/simple", "public_url"), ", https://__token__:", ctx.secret_value(s) if not s.is_pem else KP("****", "placeholder"),
                     "@", ctx.amb("internal_host"), "/simple")]
    if sub.endswith("git_log"):
        return [frag("commit ", ctx.kp("sha")), frag("Author: ", ctx.name(p), " <", ctx.email(p), ">"), frag("Date:   ", KP(K.git_date(r), "date")), frag(""),
                frag("    ", r.choice(["fix: guard against empty payload", "chore: update fixtures", "feat: add export command"])), frag("")]
    if sub.endswith("http"):
        s = ctx.secret()
        return [frag("> Authorization: Bearer ", ctx.secret_value(s) if not s.is_pem else KP("<token>", "placeholder"))]
    c = r.random()
    if c < 0.35:
        cc = VV.person(r, r.choice(["en", "it", "de", "fr", "es"]))
        return [frag("Processing customer ", ctx.name(cc), " <", ctx.email(cc), "> ... ok")]
    if c < 0.6:
        s = ctx.secret()
        return [frag("WARNING: using credentials from environment ", s.var, "=", ctx.secret_value(s) if not s.is_pem else KP("<redacted>", "placeholder"))]
    if c < 0.8:
        return [frag(ctx.user(p), "@", r.choice(["macbook-pro", "devbox", "ubuntu-dev", "thinkpad"]), ":~/", r.choice(PROJ_DIRS), "$ ", r.choice(["git status", "make test", "ls"]))]
    return [frag("Connected to ", ctx.ip(0), " (", ctx.ip(0), ") port ", KP("443", "port"))]


# ------------------------------------------------------------------ diff injection

def inject_diff(ctx: Ctx, doc: Doc) -> bool:
    hunks = list(HUNK_RE.finditer(doc.text))
    if not hunks:
        return False
    h = ctx.rng.choice(hunks)
    fm = list(re.finditer(r"^\+\+\+ b/(\S+)", doc.text[: h.start()], re.M))
    style = file_style(fm[-1].group(1), "") if fm else "py"
    style = {"doc": "env", "json": "env", "sh": "export"}.get(style, style)
    # body of this hunk: lines until next hunk/diff header
    body_start = doc.text.find("\n", h.end()) + 1
    nxt = re.compile(r"^(?:@@ |diff --git )", re.M).search(doc.text, body_start)
    body_end = nxt.start() if nxt else len(doc.text)
    line_starts = [body_start] + [m.end() for m in re.finditer(r"\n", doc.text[body_start:body_end])]
    line_starts = [body_start + (x - body_start) if x >= body_start else x for x in line_starts]
    line_starts = [s for s in line_starts if s < body_end and doc.text[s:s + 1] in (" ", "+", "-")]
    if not line_starts:
        return False
    pos = ctx.rng.choice(line_starts[1:] or line_starts)
    if any(it.start < pos < it.end for it in doc.items):
        return False
    s = ctx.secret()
    if s.is_pem:
        s = ctx.secret()
        if s.is_pem:
            return False
    lines = [ctx.secret_line(s, style if style in ("py", "yaml", "toml", "ini", "js", "env", "export") else "env")]
    if ctx.rng.random() < 0.3:
        p = ctx.person()
        lines.append(frag("ADMIN_EMAIL = '" if style == "py" else "ADMIN_EMAIL=", ctx.email(p), "'" if style == "py" else ""))
    nl = newline_of(doc.text)
    new = Doc()
    for ln in lines:
        new.add("+")
        new.extend(ln)
        new.add(nl)
    doc.insert(pos, new)
    # fix the new-side count of this hunk header
    a, b, c, d = h.group(1), h.group(2), h.group(3), h.group(4)
    new_count = (int(d) if d is not None else 1) + len(lines)
    header = f"@@ -{a}" + (f",{b}" if b is not None else "") + f" +{c},{new_count} @@"
    doc.replace(h.start(), h.end(), frag(header))
    return True


# ------------------------------------------------------------------ JSON tool-argument injection

def json_string_spans(text: str) -> list[tuple[str, int, int]]:
    """(key, start, end) of string values of object keys, offsets of the raw (escaped) content."""
    out = []
    for m in re.finditer(r'"([A-Za-z_]+)"\s*:\s*"', text):
        i = m.end()
        start = i
        while i < len(text):
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                break
            i += 1
        out.append((m.group(1), start, i))
    return out


def escaped_newline_points(text: str, s: int, e: int) -> list[int]:
    pts = []
    i = s
    while i < e:
        if text[i] == "\\":
            if text[i + 1:i + 2] == "n":
                pts.append(i + 2)
            i += 2
            continue
        i += 1
    return pts


def inject_tool_json(ctx: Ctx, doc: Doc) -> int:
    spans = json_string_spans(doc.text)
    n = 0
    # home-path substitution in path-like fields and command strings
    n += substitute_home(ctx, doc, max_occ=6)
    spans = json_string_spans(doc.text)
    code_keys = [(k, s, e) for k, s, e in spans if k in ("file_text", "new_str", "code", "content", "command", "new_string") and e - s > 40]
    if not code_keys:
        return n
    k, s, e = ctx.rng.choice(code_keys)
    raw = json_load_str(doc.text[s:e])
    pts = escaped_newline_points(doc.text, s, e)
    if k == "command" and not pts:
        # prefix the shell command with an export of a secret
        sec = ctx.secret()
        if sec.is_pem:
            return n
        fr = frag(f"export {sec.var}=", ctx.secret_value(sec), " && ")
        doc.insert(s, json_escape(fr))
        return n + 1
    style = "py" if ("def " in raw or "import " in raw) else ("sh" if k == "command" else "ini")
    cand = [(i, ind) for i, ind in points(Doc(raw), style) if 1 <= i <= len(pts)]
    cand = [(i, ind) for i, ind in cand if not any(it.start < pts[i - 1] < it.end for it in doc.items)]
    if not cand:
        return n
    i, ind = ctx.rng.choice(cand)
    pos = pts[i - 1]
    lines = indent_lines(file_snippet(ctx, style), ind)
    fr = Doc()
    for ln in lines:
        fr.extend(ln)
        fr.add("\n")
    esc = json_escape(fr)
    doc.insert(pos, esc)
    _json_hooks(doc, fr, pos + len(esc.text), ind, style)
    return n + len(lines)


def _json_hooks(doc: Doc, fr: Doc, anchor_pos: int, indent: str = "", style: str = "py") -> None:
    """Encoded-copy hooks inside a JSON string: a code comment line carrying the encoded copy."""
    from encode import _how, _render
    for uid, v in sorted(fr.vobj.items()):
        if v.cls != "MUST_MASK" or "\n" in v.text:
            continue
        name = f"json_hook_{uid}"
        doc.anchors[name] = anchor_pos
        if _how(v) is None:
            continue
        doc.hooks.append(Hook(name, (lambda rng, v=v: json_escape(frag(indent, _render("file", "en", v, rng, style), "\n"))), "json_comment", True))


def json_load_str(raw: str) -> str:
    import json
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return raw


# ------------------------------------------------------------------ dispatch

def ps1_line(ctx: Ctx, command: str) -> Doc:
    r = ctx.rng
    p = ctx.person()
    cmd = re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", command or "").strip() or r.choice(["git status", "make test", "ls -la"])
    cmd = cmd.splitlines()[0][:200]
    host = r.choice(["macbook-pro", "devbox", "ubuntu-dev", "thinkpad", "ws-042", "mbp"])
    return frag(ctx.user(p), "@", host, ":~/", r.choice(PROJ_DIRS), "/", r.choice(["api", "app", "service", "lib"]), "$ ", cmd)


def inject(ctx: Ctx, doc: Doc, kind: str, sub: str, header_path: str, command: str = "") -> None:
    """Inject at least one MUST_MASK value into a carrier excerpt (non-clean documents only)."""
    r = ctx.rng
    if kind == "tool_json":
        inject_tool_json(ctx, doc)
        if not doc.mm_items():
            sp = [x for x in json_string_spans(doc.text) if x[2] - x[1] > 0]
            k, s, e = sp[-1] if sp else ("", 0, 0)
            if sp:
                p = ctx.person()
                doc.insert(e, json_escape(frag(r.choice(["\n# reviewed by ", "\n# owner: "]), ctx.name(p), " <", ctx.email(p), ">")))
        return
    ctx.ps1_done = False
    if kind in ("log", "shell", "file") and r.random() < 0.5:
        substitute_home(ctx, doc, max_occ=6)
    n_snip = 1 if len(doc.text) < 1500 else r.randint(1, 3)
    for _ in range(n_snip):
        if kind == "prompt":
            at, _ind = choose_point(ctx, doc, "prose")
            insert_lines(doc, at, prompt_snippet(ctx))
        elif kind == "ticket":
            at, _ind = choose_point(ctx, doc, "prose")
            insert_lines(doc, at, ticket_snippet(ctx))
        elif kind == "file":
            style = file_style(header_path, doc.text)
            mode = "prose" if style == "doc" else style
            at, ind = choose_point(ctx, doc, mode)
            lines = file_snippet(ctx, style)
            if style == "yaml" and ind and any("\n" in ln.text for ln in lines):
                ind = ""
            insert_lines(doc, at, indent_lines(lines, ind))
        elif kind == "log":
            at, _ind = choose_point(ctx, doc, "log")
            insert_lines(doc, at, log_snippet(ctx))
        elif kind == "shell":
            if sub.endswith("git_diff") and inject_diff(ctx, doc):
                continue
            if sub.endswith("git_log") and "Author:" in doc.text:
                insert_lines(doc, 0, shell_snippet(ctx, sub))
                continue
            if sub.endswith("git_log"):
                if not ctx.ps1_done:
                    ctx.ps1_done = True
                    insert_lines(doc, 0, [ps1_line(ctx, command)])
                continue
            if not ctx.ps1_done and (sub.endswith(("git_log", "git_other", "test_run", "script", "other", "install", "listing", "env", "container", "http"))
                                     and r.random() < 0.5):
                ctx.ps1_done = True
                insert_lines(doc, 0, [ps1_line(ctx, command)])
                continue
            lines = shell_snippet(ctx, sub)
            at, _ind = choose_point(ctx, doc, "ends")
            insert_lines(doc, at, lines)
    if not doc.mm_items():
        end = effective_end(doc)
        if kind == "shell" and not ctx.ps1_done:
            ctx.ps1_done = True
            insert_lines(doc, 0, [ps1_line(ctx, command)])
        elif kind == "shell":
            insert_lines(doc, end, shell_snippet(ctx, "other"))
        elif kind == "log":
            insert_lines(doc, end, log_snippet(ctx))
        elif kind == "file":
            insert_lines(doc, end, file_snippet(ctx, file_style(header_path, doc.text)))
        else:
            insert_lines(doc, end, ticket_snippet(ctx) if kind == "ticket" else prompt_snippet(ctx))
