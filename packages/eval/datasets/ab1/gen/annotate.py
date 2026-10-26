# SPDX-License-Identifier: Apache-2.0
"""Regex annotation passes.

carrier_pass(doc): run on the raw carrier excerpt before injection. Finds e-mails, phone numbers,
IP and MAC addresses, key-like strings (the gitleaks rule list plus assignment / entropy patterns),
names in authorship contexts, handles and home-directory usernames, and classifies each hit as
AMBIGUOUS (carrier_pii, role_address, licence_name, ...) or MUST_KEEP (reserved addresses, versions).
Reviewed decisions that override the rules live in gen/carrier_review.tsv.

keep_pass(doc): run on every document at the end. Annotates MUST_KEEP kinds (public URLs, hashes,
UUIDs, versions, dates, placeholders, env references, paths, ticket numbers, line numbers, ports,
PIDs, HTTP status codes, code identifiers, organisation names) and AMBIGUOUS internal hosts and
private IPs, never overlapping an existing item.

Two rules of the 2026-10-25 audit are applied here: a UUID that directly follows a session-like key
is AMBIGUOUS `session_id` (SPEC lists UUIDs as MUST_KEEP but session cookies as secrets), and a
base64/URL-encoded value that decodes to a dummy credential of the SPEC AMBIGUOUS list is AMBIGUOUS
`dummy_credential` rather than a MUST_KEEP placeholder. Both only reclassify items; no span, value
or document changes.
"""
from __future__ import annotations

import base64
import ipaddress
import math
import re
import urllib.parse
from collections import Counter
from functools import lru_cache
from pathlib import Path

from doc import AMBIGUOUS, MUST_KEEP, Doc
import values as VV

REVIEW_PATH = Path(__file__).resolve().parent / "carrier_review.tsv"

ROLE_LOCAL = set(VV.handmade_lines("role_localparts.txt")) | {"no_reply", "donotreply", "do-not-reply", "maintainers",
                                                               "bugs", "webmaster", "github", "git", "root", "mailer-daemon",
                                                               "press", "office", "jobs", "careers", "feedback", "marketing",
                                                               "newsletter", "service", "mail", "users", "announce"}
FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "js", "ts", "py", "css", "html", "json", "txt", "md", "lock", "yml", "yaml",
             "toml", "cfg", "ini", "xml", "sh", "rb", "go", "rs", "java", "map", "ico", "webp", "pdf", "zip", "gz", "whl", "so",
             "dll", "exe", "mjs", "cjs", "vue", "tsx", "jsx", "scss", "less", "wasm", "pyc", "pyi", "pyx", "h", "c", "cpp", "test",
             "local", "internal", "invalid", "localhost", "example", "lan", "corp", "home", "fixture"}
GENERIC_USERS = {"root", "runner", "ubuntu", "user", "openhands", "admin", "ec2-user", "vagrant", "node", "app", "jovyan",
                 "circleci", "travis", "vscode", "codespace", "coder", "dev", "test", "runneradmin", "docker", "www-data",
                 "nobody", "shared", "username", "you", "me", "default", "builder", "build", "jenkins", "gitlab-runner",
                 "appuser", "worker", "service", "centos", "debian", "pi", "guest", "linuxbrew", "deploy", "ci", "conda",
                 "testuser", "foo", "bar", "name", "yourname", "your_username", "<user>", "$user", "%user%", "public",
                 "opendevin", "openhands-user", "dev-user", "safety-db", "runner-user", "sandbox", "agent"}
DECORATOR_WORDS = {"property", "staticmethod", "classmethod", "pytest", "dataclass", "override", "abstractmethod", "app",
                   "router", "mock", "patch", "functools", "lru_cache", "cached_property", "param", "return", "returns",
                   "raises", "deprecated", "throws", "see", "since", "author", "version", "type", "types", "typing",
                   "contextmanager", "wraps", "click", "unittest", "skip", "fixture", "receiver", "login_required",
                   "media", "import", "keyframes", "font", "apply", "tailwind", "layer", "charset", "example", "todo",
                   "note", "brief", "file", "link", "code", "inheritdoc", "test", "before", "after", "jit", "njit",
                   "overload", "final", "api", "pyqtSlot", "Override", "Test", "Bean", "Autowired", "Component",
                   "GetMapping", "PostMapping", "Entity", "Column", "Id", "Input", "Output", "Injectable", "NgModule",
                   "echo", "rm", "mkdir", "cd", "python", "npm", "make", "cp", "mv", "printf", "if", "for", "set"}
JIRA_STOP = {"UTF", "ISO", "SHA", "RFC", "PEP", "CVE", "HTTP", "TLS", "SSL", "AES", "MD", "CP", "WIN", "GMT", "UTC", "X",
             "CWE", "GHSA", "RSA", "ECDSA", "EC", "PKCS", "SHA1", "SHA256", "IEEE", "ANSI", "CSS", "ES", "TCP", "UDP",
             "IPV", "PY", "LATIN", "WINDOWS", "COVID", "PR", "DO", "NOT", "MAX", "MIN", "SEC", "REV", "UTF8", "BASE",
             "SIGTERM", "SIGKILL", "E", "W", "F", "C", "B", "N", "D", "S", "Q", "T", "U", "R", "H", "A"}
ORG_REGEX_EXCLUDE = {"Lambda", "Vault", "Linear", "Notion", "Express", "Orange", "Meta", "Apple", "Amazon", "Angular", "Rust",
                     "React", "pandas", "npm", "Consul", "Jira", "Kotlin", "Spring Boot", "Figma", "Okta", "Klarna", "Matomo",
                     "Oracle", "Docker", "Python", "Google", "Microsoft", "Mozilla", "Ubuntu", "Debian", "Firebase", "Homebrew",
                     "Confluence", "Salesforce", "Intercom", "Snowflake", "Airflow", "Shopify", "DHL", "UPS", "SAP", "IBM",
                     "TypeScript", "Express", "Cloud Run", "Vodafone"}

# ------------------------------------------------------------------ helpers

EMAIL_RE = re.compile(r"(?<![\w.%+\-/=\\])([A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,24})(?![\w\-]|\.[A-Za-z0-9])")
IPV4_RE = re.compile(r"(?<![\w.])((?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d))(?![\w]|\.\d)")
IPV6_RE = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{1,4}:){2,7}(?::|[0-9A-Fa-f]{1,4})(?:(?::[0-9A-Fa-f]{1,4}){0,6})|::1|::ffff:[\d.]+|fe80::[0-9A-Fa-f:]+)(?![\w:])")
MAC_RE = re.compile(r"(?<![\w:\-.])((?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})(?![\w:\-])")
PHONE_RES = [
    re.compile(r"(?<![\w+/.\-])(\+\d{1,3}[ .\-]?(?:\(0?\d{1,4}\)[ .\-]?)?\d{1,4}(?:[ .\-]?\d{2,4}){2,4})(?![\w.\-])"),
    re.compile(r"(?<![\w/.\-])(\(\d{3}\) ?\d{3}-\d{4})(?![\w])"),
    re.compile(r"(?<![\w/.\-:])(\d{3}-\d{3}-\d{4})(?![\w\-])"),
    re.compile(r"(?<![\w/.\-:])(0\d{1,4}[ /\-]\d{3,4}[ \-]?\d{3,5})(?![\w.\-/])"),
]
NAME = r"[A-Z\u00C0-\u00DE][\w'\u00C0-\u017F.\-]+(?: (?:van |von |de |da |di |del |der |le |la )?[A-Z\u00C0-\u00DE][\w'\u00C0-\u017F.\-]+){1,3}"
NAME_CTX_RES = [
    (re.compile(r"(?:Author|Commit|AuthorName|Committer):\s+(" + NAME + r")\s+<"), "carrier_pii"),
    (re.compile(r"(?:Signed-off-by|Co-authored-by|Reviewed-by|Reported-by|Tested-by|Acked-by|Helped-by):\s+(" + NAME + r")\s+<", re.I), "carrier_pii"),
    (re.compile(r"Copyright\s+(?:\(c\)|©|\(C\))?\s*(?:\d{4}(?:\s*[-,]\s*\d{4})*,?\s+)?(?:by\s+)?(" + NAME + r")"), "licence_name"),
    (re.compile(r"\(c\)\s+\d{4}(?:\s*-\s*\d{4})?\s+(" + NAME + r")"), "licence_name"),
    (re.compile(r"__(?:author|maintainer|credits)__\s*=\s*[\[(]?['\"](" + NAME + r")"), "licence_name"),
    (re.compile(r"\b(?:author|maintainer)\s*=\s*['\"](" + NAME + r")['\"]"), "licence_name"),
    (re.compile(r"[\"'](?:author|maintainer)[\"']\s*:\s*[\"'](" + NAME + r")\s*(?:<|[\"'])"), "licence_name"),
    (re.compile(r"(?<![\w@])(" + NAME + r")\s+<[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+>"), "carrier_pii"),
    (re.compile(r"(?<![\w@])(" + NAME + r")\s+\(@[A-Za-z0-9\-]+\)"), "carrier_pii"),
    (re.compile(r"\{\s*name\s*=\s*[\"'](" + NAME + r")[\"']"), "licence_name"),
    (re.compile(r"@author\s+(" + NAME + r")"), "licence_name"),
    (re.compile(r"(?:Thanks|Regards|Cheers|Best),?\s*\n\s*(" + NAME + r")\s*$", re.M), "carrier_pii"),
]
NAME_STOP = {"GitHub", "GitHub Actions", "Dependabot", "The Python Software Foundation", "Python Software Foundation",
             "The Authors", "The Contributors", "Contributors", "The", "Open Source", "Google LLC", "Google Inc", "Microsoft Corporation",
             "Free Software Foundation", "The Apache Software Foundation", "Apache Software Foundation", "Copyright", "Software",
             "The Regents", "Individual", "All Rights Reserved", "All", "See", "Permission", "The Pallets Projects", "Pallets",
             "Django Software Foundation", "Facebook", "Meta Platforms", "Unknown", "Anonymous", "None", "Name", "Your Name",
             "John Doe", "Jane Doe", "Example", "Test User", "Test", "Bot", "Renovate Bot", "OpenHands", "OpenHands Bot"}
HANDLE_RE = re.compile(r"(?<![\w@/.`'\"<\-])@([A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?)(?![\w\-.(/@])")
HOME_RE = re.compile(r"(?:/home/|/Users/|C:\\\\?Users\\\\?|/u/)([A-Za-z0-9][\w.\-]{1,31})(?=[/\\])")
ASSIGN_KEY_RE = re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|auth[_\-]?token|private[_\-]?key|client[_\-]?secret)"
                           r"[\"']?\s*[:=]\s*[\"']([^\s\"',;]{6,})[\"']")
ENTROPIC_RE = re.compile(r"(?<![\w+/=\-.])([A-Za-z0-9+/_\-]{28,})(?![\w+/=\-])")


def entropy(s: str) -> float:
    c = Counter(s)
    n = len(s)
    return -sum(v / n * math.log2(v / n) for v in c.values())


DOC_NETS4 = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
DOC_NET6 = ipaddress.ip_network("2001:db8::/32")


def classify_ip(s: str) -> tuple[str, str] | None:
    try:
        a = ipaddress.ip_address(s)
    except ValueError:
        return None
    if s in ("127.0.0.1", "0.0.0.0", "::1", "::") or a.is_loopback or a.is_unspecified:
        return MUST_KEEP, "reserved_address"
    if a.version == 4 and any(a in n for n in DOC_NETS4):
        return MUST_KEEP, "reserved_address"
    if a.version == 6 and a in DOC_NET6:
        return MUST_KEEP, "reserved_address"
    if a.is_private or a.is_link_local or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")):
        return AMBIGUOUS, "rfc1918_ip"
    return AMBIGUOUS, "carrier_pii"


def is_reserved_domain(dom: str) -> bool:
    d = dom.lower().rstrip(".")
    labels = d.split(".")
    if labels[-1] in ("test", "invalid", "localhost", "example"):
        return True
    return len(labels) >= 2 and labels[-2] == "example" and labels[-1] in ("com", "org", "net")


def classify_email(e: str) -> tuple[str, str] | None:
    local, dom = e.rsplit("@", 1)
    if dom.rsplit(".", 1)[-1].lower() in FILE_TLDS:
        return None
    if is_reserved_domain(dom):
        return MUST_KEEP, "reserved_address"
    if local.lower() in ROLE_LOCAL or "noreply" in dom.lower() or local.lower().startswith(("noreply", "no-reply")):
        return AMBIGUOUS, "role_address"
    return AMBIGUOUS, "carrier_pii"


@lru_cache(maxsize=1)
def gitleaks_rules():
    from secrets_gl import load_rules
    rules, *_ = load_rules()
    return rules


@lru_cache(maxsize=1)
def review_overrides() -> dict[str, tuple[str, str] | None]:
    out: dict[str, tuple[str, str] | None] = {}
    if not REVIEW_PATH.exists():
        return out
    for line in REVIEW_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        val, decision = line.rsplit("\t", 1)
        out[val] = None if decision == "skip" else tuple(decision.split(":", 1))  # type: ignore[assignment]
    return out


PLACEHOLDERISH = re.compile(r"(?i)^(?:x+|\*+|your[_\-].*|<.*>|\$\{?.*|%.*%|.*(?:example|placeholder|dummy|fake|changeme|redacted|xxxx|test|sample|mock|secret|password|foo|bar|token).*)$")
HASHISH = re.compile(r"^(?:[0-9a-f]{7,128}|[0-9A-F]{32,128}|sha\d+[-:].*|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")


def keylike_class(v: str, assignment: bool = False) -> tuple[str, str] | None:
    if "(" in v or v.startswith(("self.", "os.", "config.", "settings.")) or HASHISH.match(v):
        return None
    if not assignment and re.fullmatch(r"[A-Za-z_.\-/]+", v):
        return None  # identifiers, dotted attribute paths and file names
    if PLACEHOLDERISH.match(v):
        return AMBIGUOUS, "dummy_credential"
    return AMBIGUOUS, "carrier_pii"


# ------------------------------------------------------------------ carrier pass

def carrier_hits(text: str) -> list[tuple[int, int, str, str, str]]:
    """Return (start, end, class, kind, why) proposals on raw carrier text (may overlap; resolved by order)."""
    hits: list[tuple[int, int, str, str, str]] = []
    for m in EMAIL_RE.finditer(text):
        local_dom = m.group(1)
        if local_dom.startswith("git@") and local_dom.split("@")[1] in ("github.com", "gitlab.com", "bitbucket.org"):
            continue
        c = classify_email(local_dom)
        if c:
            hits.append((m.start(1), m.end(1), c[0], c[1], "email"))
    for rx, kind in NAME_CTX_RES:
        for m in rx.finditer(text):
            name = m.group(1).rstrip(".,")
            if name in NAME_STOP or name.split()[0] in ("The", "This", "All", "See", "Copyright"):
                continue
            hits.append((m.start(1), m.start(1) + len(name), AMBIGUOUS, kind, "name_ctx"))
    for m in HOME_RE.finditer(text):
        u = m.group(1)
        if u.lower() in GENERIC_USERS or u.startswith("$") or u.startswith("<"):
            continue
        hits.append((m.start(1), m.end(1), AMBIGUOUS, "carrier_pii", "home_user"))
    for r in gitleaks_rules():
        for m in r.py.finditer(text):
            g = r.secret_group if r.secret_group and m.group(r.secret_group) is not None else 0
            if r.secret_group and m.group(r.secret_group) is None:
                g = next((i for i in range(1, (r.py.groups or 0) + 1) if m.group(i)), 0)
            s, e = m.span(g)
            v = text[s:e].strip("\"'")
            if not v:
                continue
            s = text.index(v, s)
            e = s + len(v)
            if r.entropy and entropy(v) < r.entropy:
                continue
            c = keylike_class(v)
            if c:
                hits.append((s, e, c[0], c[1], "gitleaks:" + r.id))
    for m in ASSIGN_KEY_RE.finditer(text):
        v = m.group(1)
        c = keylike_class(v, assignment=True)
        if c:
            hits.append((m.start(1), m.end(1), c[0], c[1], "assign"))
    for m in ENTROPIC_RE.finditer(text):
        v = m.group(1)
        if re.search(r"(?i)sha(?:1|256|384|512)[:\-]$", text[max(0, m.start(1) - 8):m.start(1)]):
            continue
        if entropy(v) < 4.2 or not (re.search(r"[a-z]", v) and re.search(r"[A-Z]", v) and re.search(r"\d", v)):
            continue
        if "/" in v and v.count("/") >= 2 and not v.endswith("="):
            continue  # path-like
        c = keylike_class(v)
        if c:
            hits.append((m.start(1), m.end(1), c[0], c[1], "entropy"))
    for m in IPV4_RE.finditer(text):
        before = text[max(0, m.start() - 12):m.start()]
        if re.search(r"(?:version|ver|v|==|>=|<=|-|python|\d\.)\s*$", before, re.I):
            continue
        c = classify_ip(m.group(1))
        if c:
            hits.append((m.start(1), m.end(1), c[0], c[1], "ipv4"))
    for m in IPV6_RE.finditer(text):
        s = m.group(1)
        if s.count(":") < 2 or not re.search(r"[0-9a-fA-F]{2}", s.replace(":", "")) and s != "::1":
            continue
        c = classify_ip(s)
        if c:
            hits.append((m.start(1), m.end(1), c[0], c[1], "ipv6"))
    for m in MAC_RE.finditer(text):
        v = m.group(1)
        if len(set(v.replace(":", "").replace("-", "").replace(".", ""))) <= 2:
            continue
        hits.append((m.start(1), m.end(1), AMBIGUOUS, "carrier_pii", "mac"))
    for rx in PHONE_RES:
        for m in rx.finditer(text):
            v = m.group(1)
            digits = re.sub(r"\D", "", v)
            if not (9 <= len(digits) <= 15) or len(set(digits)) <= 2:
                continue
            hits.append((m.start(1), m.end(1), AMBIGUOUS, "carrier_pii", "phone"))
    for m in HANDLE_RE.finditer(text):
        h = m.group(1)
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].strip(" \t*#/0123456789") == "" or h in DECORATOR_WORDS or h.isdigit():
            continue
        if h.lower() in DECORATOR_WORDS or len(h) < 2:
            continue
        hits.append((m.start(), m.end(), AMBIGUOUS, "maintainer_handle", "handle"))
    return hits


def carrier_pass(doc: Doc, log: list | None = None) -> None:
    overrides = review_overrides()
    hits = carrier_hits(doc.text)
    # reviewed values the rules do not find are annotated wherever they occur in the excerpt
    for val, dec in overrides.items():
        if dec is None:
            continue
        for m in re.finditer(re.escape(val), doc.text):
            hits.insert(0, (m.start(), m.end(), dec[0], dec[1], "review"))
    for s, e, cls, kind, why in hits:
        v = doc.text[s:e]
        if v in overrides:
            o = overrides[v]
            if o is None:
                continue
            cls, kind = o
        ok = doc.annotate(s, e, cls, kind, kind, "carrier_pass")
        if log is not None:
            log.append((v, cls, kind, why, ok, doc.text[max(0, s - 40):s].replace("\n", "⏎"), doc.text[e:e + 40].replace("\n", "⏎")))


# ------------------------------------------------------------------ keep pass

URL_RE = re.compile(r"\b(?:https?|ftp|wss?|ssh|git|postgres(?:ql)?|mysql|redis|rediss|mongodb(?:\+srv)?|amqps?|s3|sftp)://[^\s<>\"'`\\]+")
GIT_REMOTE_RE = re.compile(r"\bgit@(?:github\.com|gitlab\.com|bitbucket\.org):[\w.\-/]+")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Audit rule 1: a UUID directly after a session-like key is ambiguous — SPEC.md keeps UUIDs but
# masks session cookies — so it is AMBIGUOUS `session_id`. Every other UUID stays MUST_KEEP `uuid`.
SESSION_KEY_RE = re.compile(r"(?i)(?<![\w])(?:session_id|sessionid|session|sid|token|cookie)[\"']?\s*[:=]\s*[\"']?$")
SESSION_KEY_BACK = 40
HASH_RES = [
    re.compile(r"(?i)\bsha(?:1|256|384|512)[-:][A-Za-z0-9+/=]{20,}"),
    re.compile(r"(?<![\w\-])[0-9a-f]{64}(?![\w\-])"),
    re.compile(r"(?<![\w\-])[0-9a-f]{32}(?![\w\-])"),
]
SHA40_RE = re.compile(r"(?<![\w\-])[0-9a-f]{40}(?![\w\-])")
SHORT_SHA_RES = [
    re.compile(r"^commit ([0-9a-f]{7,40})\b", re.M),
    re.compile(r"^(?:\*\s+|\|\s+\*\s+)?([0-9a-f]{7,12}) (?=\S)", re.M),
    re.compile(r"\bindex ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})\b"),
    re.compile(r"\b(?:commit|Merge:|merge|revert|reverts|cherry-pick|HEAD is now at|sha|SHA|rev|at)\s+([0-9a-f]{7,12})\b"),
    re.compile(r"\bMerge: ([0-9a-f]{7,12}) ([0-9a-f]{7,12})\b"),
    re.compile(r"\[[\w./\-]+ ([0-9a-f]{7,12})\]"),
]
MONTH_WORDS = "|".join(sorted({m for ms in __import__("keepvals").MONTHS.values() for m in ms} | {m.capitalize() for ms in __import__("keepvals").MONTHS.values() for m in ms}, key=len, reverse=True))
DATE_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:[.,]\d{1,9})?(?:Z|[+\-]\d{2}:?\d{2}| ?UTC)?(?![\d])"),
    re.compile(r"\b\d{2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/\d{4}:\d{2}:\d{2}:\d{2} [+\-]\d{4}"),
    re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} \d{2}:\d{2}:\d{2}(?: (?:GMT|UTC|[+\-]\d{4}))?"),
    re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) {1,2}\d{1,2} \d{2}:\d{2}:\d{2} \d{4}(?: [+\-]\d{4})?"),
    re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2}", re.M),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}(?:\.|º)? (?:de )?(?:" + MONTH_WORDS + r")(?: de)? \d{4}\b"),
    re.compile(r"\b(?:" + MONTH_WORDS + r") \d{1,2}, \d{4}\b"),
    re.compile(r"(?<![\d/.])\d{2}[./]\d{2}[./]\d{4}(?![\d/.])"),
    re.compile(r"(?<![\d:])\d{2}:\d{2}:\d{2}(?:[.,]\d{3,6})?(?![\d:])"),
]
VERSION_RES = [
    re.compile(r"\b(?:Chrome|Safari|Firefox|Version|Gecko|AppleWebKit|Edg|OPR|Mobile)/(\d+(?:\.\d+)+)"),
    re.compile(r"(?<![\w.\-/])v?\d+\.\d+\.\d+(?:[\-+][0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*|\.?(?:post|dev|rc|a|b)\d+)?(?![\w.]*\d)(?![\w])"),
    re.compile(r"(?:==|>=|<=|~=|!=|\^|~|@|\bversion[=: ]+\"?|\bVersion:? |\bpython|\bPython |\bnode |\bv)(\d+\.\d+)(?![\d.])"),
]
ENVREF_RES = [
    re.compile(r"\$\{\{\s*[^}]+?\s*\}\}"),
    re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:[:?+=\-][^}\s]*)?\}"),
    re.compile(r"(?<![\w$\\])\$[A-Z_][A-Z0-9_]{1,}\b"),
    re.compile(r"(?<![\w%])%[A-Z_][A-Z0-9_]+%"),
    re.compile(r"\bprocess\.env\.[A-Za-z_][A-Za-z0-9_]*"),
    re.compile(r"\bos\.environ(?:\.get)?[\[(]\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*[\])]"),
    re.compile(r"\bos\.getenv\(\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*\)"),
    re.compile(r"\bENV\[[\"'][A-Z_][A-Z0-9_]*[\"']\]"),
]
PLACEHOLDER_RES = [
    # anonymisation tags left in carrier text by an upstream Presidio-style pass (WildChat-1M
    # replaced some personal data with them): a placeholder, so MUST_KEEP
    re.compile(r"<PRESIDIO_ANONYMIZED_[A-Z0-9_]+>"
               r"|<(?:EMAIL_ADDRESS|PHONE_NUMBER|PERSON|LOCATION|DATE_TIME|CREDIT_CARD|IBAN_CODE|IP_ADDRESS|NRP"
               r"|MEDICAL_LICENSE|US_SSN|US_PHONE_NUMBER|US_BANK_NUMBER|US_PASSPORT|US_DRIVER_LICENSE|US_ITIN)>"),
    re.compile(r"\bYOUR_[A-Z0-9_]+\b"),
    re.compile(r"\byour[_\-][a-z0-9_\-]+\b"),
    re.compile(r"<(?:your[\-_ ])?[a-z][a-z0-9_ \-]*(?:token|key|secret|password|pass|username|user|email|host|id|name|phone|address)[a-z0-9_ \-]*>", re.I),
    re.compile(r"(?<![\w])x{6,}(?![\w])|(?<![\w])X{6,}(?![\w])"),
    re.compile(r"\*{4,}"),
    re.compile(r"\bREPLACE_[A-Z0-9_]+\b"),
    re.compile(r"\[(?:REDACTED|FILTERED|MASKED|HIDDEN)\]|<redacted>|\bchangeme-in-prod\b"),
    re.compile(r"\{\{\s*[\w.]+\s*\}\}"),
]
RESERVED_RES = [
    re.compile(r"[\w.+\-]+@(?:[\w\-]+\.)*example\.(?:com|org|net)\b"),
    re.compile(r"\b(?:[\w\-]+\.)*example\.(?:com|org|net)\b"),
    re.compile(r"\blocalhost\b"),
    re.compile(r"(?<![\w.])(?:127\.0\.0\.1|0\.0\.0\.0)(?![\w]|\.\d)"),
    re.compile(r"(?<![\w:])::1(?![\w:])"),
    re.compile(r"(?<![\w.])(?:192\.0\.2|198\.51\.100|203\.0\.113)\.\d{1,3}(?![\w]|\.\d)"),
    re.compile(r"(?<![\w:])2001:db8:[0-9a-fA-F:]*(?![\w:])"),
]
TICKET_RES = [
    re.compile(r"(?<![\w&#/])#(\d{1,6})(?![\w])"),
    re.compile(r"\b(GH-\d{1,6})\b", re.I),
    re.compile(r"\b(INC\d{7})\b"),
    re.compile(r"(?i)\b(?:issue|issues|pr|pull request|ticket|bug|fixes|closes|resolves|refs?)\s+#?(\d{1,6})\b"),
    re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b"),
]
LINE_RES = [
    re.compile(r"\bline (\d{1,6})\b"),
    re.compile(r"\.(?:py|js|ts|tsx|jsx|java|go|rb|rs|c|cc|cpp|h|kt|php|scala|cs|swift|pyx|mjs|cjs):(\d{1,6})\b"),
]
STATUS_RES = [
    re.compile(r"\bHTTP/\d(?:\.\d)? (\d{3})\b"),
    re.compile(r"(?i)\b(?:status|status_code|statusCode|http_status|code)[=:\"'\s]+(\d{3})\b"),
    re.compile(r"\" (\d{3}) (?:\d+|-)"),
    re.compile(r"\b(\d{3}) (?:OK|Created|Accepted|No Content|Moved Permanently|Found|Not Modified|Bad Request|Unauthorized|"
               r"Forbidden|Not Found|Method Not Allowed|Conflict|Unprocessable Entity|Too Many Requests|Internal Server Error|"
               r"Bad Gateway|Service Unavailable|Gateway Timeout)\b"),
]
PID_RES = [
    re.compile(r"\b(?:pid|PID)[=:\s]\s*(\d{1,7})\b"),
    re.compile(r"\b[Pp]rocess \[(\d{1,7})\]"),
    re.compile(r"^\[[\d\- :+]+\] \[(\d{1,7})\] \[(?:INFO|DEBUG|WARNING|ERROR|CRITICAL)\]", re.M),
    re.compile(r"\bwith pid:? (\d{1,7})\b"),
    re.compile(r"\bkill(?: -9| -TERM| -HUP)? (\d{2,7})\b"),
    re.compile(r"\b[\w.\-]+\[(\d{1,7})\]:"),
    re.compile(r"\b[Pp]rocess (\d{2,7})\b"),
]
PORT_RES = [
    re.compile(r"(?<=localhost:)(\d{2,5})\b"),
    re.compile(r"(?<=127\.0\.0\.1:)(\d{2,5})\b"),
    re.compile(r"(?<=0\.0\.0\.0:)(\d{2,5})\b"),
    re.compile(r"(?i)\bport[= :]+(\d{2,5})\b"),
    re.compile(r"\s-p\s+(\d{2,5}):(\d{2,5})\b"),
    re.compile(r"\bPORT=(\d{2,5})\b"),
    re.compile(r"(?<=[a-z0-9\]]):(\d{2,5})(?=/|\s|$|\"|'|,|\))", re.M),
]
PATH_RES = [
    re.compile(r"(?<![\w/.:~\-@\\])(/(?:[\w.@%+~\-]+/)+[\w.@%+~\-]+/?)"),
    re.compile(r"(?<![\w/])(~/[\w.@%+\-/]+)"),
    re.compile(r"(?<![\w/.:@\-])((?:\.{1,2}/)?(?:[\w.@+\-]+/)+[\w@+\-]+\.[A-Za-z][A-Za-z0-9]{0,7})(?![\w/])"),
    re.compile(r"(?<![\w])([A-Z]:(?:\\{1,2}[\w .\-]+){2,})"),
]
IDENT_RES = [
    re.compile(r"\b(?:def|function|func|fn)\s+([A-Za-z_]\w*)\s*[(<]"),
    re.compile(r"\bclass\s+([A-Za-z_]\w*)\s*[(:{<]|\bclass\s+([A-Za-z_]\w*)\s+(?:extends|implements)\b"),
    re.compile(r"\b(?:interface|struct|enum)\s+([A-Z]\w*)\s*[{<]"),
    re.compile(r"File \"[^\"\n]+\", line \d+, in ([A-Za-z_]\w*)\b"),
    re.compile(r"\bat ((?:[\w$]+\.)+[\w$<>]+)\("),
]


def _url_kind(url: str) -> tuple[str, str]:
    m = re.match(r"^[a-z0-9+]+://(?:[^@/\s]+@)?(\[[^\]]+\]|[^:/?#\s]+)", url, re.I)
    host = (m.group(1) if m else "").strip("[]").lower()
    c = classify_ip(host) if re.match(r"^[\d.]+$|^[0-9a-f:]+:[0-9a-f:]*$", host) else None
    if c:
        if c[1] == "rfc1918_ip":
            return AMBIGUOUS, "internal_host"
        return c
    if host in ("localhost",) or host.endswith(".localhost"):
        return MUST_KEEP, "reserved_address"
    if is_reserved_domain(host):
        return MUST_KEEP, "reserved_address"
    if "." not in host or host.rsplit(".", 1)[-1] in ("internal", "local", "lan", "corp", "intranet", "home", "consul", "svc", "cluster") \
            or ".svc." in host or host.endswith(".svc.cluster.local"):
        return AMBIGUOUS, "internal_host"
    path = url.split(host, 1)[1] if host in url.lower() else ""
    prof = re.match(r"^(?:www\.)?(github\.com|gitlab\.com|twitter\.com|x\.com|instagram\.com|medium\.com|mastodon\.social|facebook\.com)$", host)
    if prof and re.match(r"^/@?[\w.\-]+/?$", path):
        return AMBIGUOUS, "maintainer_handle"
    if host.endswith("linkedin.com") and path.startswith("/in/"):
        return AMBIGUOUS, "maintainer_handle"
    return MUST_KEEP, "public_url"


def _trim_url(s: str) -> str:
    s = s.rstrip(".,;:!?_*")
    while s and s[-1] in ")]}" and s.count(s[-1]) > s.count({")": "(", "]": "[", "}": "{"}[s[-1]]):
        s = s[:-1].rstrip(".,;:!?")
    return s


def _items_inside(doc: Doc, s: int, e: int):
    return sorted((it for it in doc.items if it.start < e and s < it.end), key=lambda x: x.start)


def _ann(doc: Doc, s: int, e: int, cls: str, kind: str) -> bool:
    return doc.annotate(s, e, cls, kind, kind, "keep_pass")


def _url_pass(doc: Doc) -> None:
    for m in URL_RE.finditer(doc.text):
        raw = _trim_url(m.group(0))
        s, e = m.start(), m.start() + len(raw)
        inside = _items_inside(doc, s, e)
        if not inside:
            cls, kind = _url_kind(raw)
            _ann(doc, s, e, cls, kind)
            continue
        first = inside[0]
        if first.start <= s:
            continue
        prefix = doc.text[s:first.start]
        if "@" in prefix or not re.match(r"^[a-z0-9+]+://[^/]+/", prefix, re.I):
            continue
        cut = prefix.split("?", 1)[0] if "?" in prefix else prefix
        cut = cut.rstrip("/=&#:")
        if len(cut) > len(prefix.split("/", 3)[0]) + 4:
            cls, kind = _url_kind(cut)
            _ann(doc, s, s + len(cut), cls, kind)


def _simple(doc: Doc, rx: re.Pattern, cls: str, kind: str, groups: bool = False, check=None) -> None:
    for m in rx.finditer(doc.text):
        spans = [m.span(i) for i in range(1, (rx.groups or 0) + 1) if m.group(i)] if groups and rx.groups else [m.span(0)]
        for s, e in spans:
            v = doc.text[s:e]
            if check and not check(v, doc.text, s, e):
                continue
            _ann(doc, s, e, cls, kind)


def _path_pass(doc: Doc) -> None:
    for rx in PATH_RES:
        for m in rx.finditer(doc.text):
            s, e = m.span(1)
            v = doc.text[s:e].rstrip(".,:;")
            e = s + len(v)
            if len(v) < 4 or v.count("/") + v.count("\\") < 1:
                continue
            if re.match(r"^/?\d+(?:/\d+)*/?$", v):
                continue
            inside = _items_inside(doc, s, e)
            if not inside:
                if rx is PATH_RES[0] and v.count("/") < 2:
                    continue
                _ann(doc, s, e, MUST_KEEP, "path")
                continue
            # split around existing items (e.g. a username inside a home path)
            pos = s
            for it in inside:
                if it.start > pos:
                    seg = doc.text[pos:it.start]
                    if seg.count("/") >= 2 and not seg.endswith(("/home/", "/Users/")):
                        _ann(doc, pos, it.start, MUST_KEEP, "path")
                pos = max(pos, it.end)
            if pos < e:
                seg = doc.text[pos:e]
                if seg.startswith(("/", "\\")) and len(seg) >= 3:
                    _ann(doc, pos, e, MUST_KEEP, "path")


def _version_ok(v: str, text: str, s: int, e: int) -> bool:
    core = v.lstrip("v")
    parts = core.split("-")[0].split("+")[0].split(".")
    if len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts):
        return False  # IP-like, left to the IP handling
    if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 4 and parts[1].isdigit() and int(parts[1]) <= 12:
        return False  # date-like 2024.03.05
    return True


def _port_ok(v: str, text: str, s: int, e: int) -> bool:
    """host:port only when the token before the colon is a hostname (has a letter) or an IPv4 address."""
    m = re.search(r"([\w.\-\]\[]+):$", text[max(0, s - 80):s])
    if not m:
        return True
    host = m.group(1).strip("[]")
    return bool(re.search(r"[A-Za-z]", host)) or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host))


def _ticket_ok(v: str, text: str, s: int, e: int) -> bool:
    if re.match(r"^[A-Z][A-Z0-9]{1,9}-\d", v):
        return v.split("-")[0] not in JIRA_STOP
    if v in ("0", "00"):
        return False
    before = text[max(0, s - 12):s]
    if re.search(r"(?:color|background|fill|stroke)\s*[:=]\s*[\"']?#?$", before, re.I):
        return False
    return True


def _hash_ok(v: str, text: str, s: int, e: int) -> bool:
    return bool(re.search(r"\d", v) and re.search(r"[a-fA-F]", v)) or v.startswith("sha")


def _after_session_key(text: str, start: int) -> bool:
    """True when a session-like key sits directly before `start` (audit rule 1)."""
    return bool(SESSION_KEY_RE.search(text[max(0, start - SESSION_KEY_BACK):start]))


def _uuid_class(text: str, start: int) -> tuple[str, str]:
    """Audit rule 1: a UUID after a session-like key is ambiguous — SPEC.md keeps UUIDs but masks
    session cookies — so it is AMBIGUOUS `session_id`; every other UUID stays MUST_KEEP `uuid`."""
    return (AMBIGUOUS, "session_id") if _after_session_key(text, start) else (MUST_KEEP, "uuid")


def session_id_pass(doc: Doc) -> None:
    """Reclassify UUIDs placed by a template or an injection (`session=<uuid>` and friends): they are
    already items when the keep pass runs, so the UUID rule above cannot reach them. Only the class
    and the kind change; the span, the text and the item count stay the same."""
    for it in doc.items:
        if it.cls == MUST_KEEP and it.kind == "uuid" and _after_session_key(doc.text, it.start):
            it.cls = AMBIGUOUS
            it.category = it.kind = "session_id"


# Audit rule 2: an encoded value that decodes to a dummy credential of the SPEC AMBIGUOUS list (the
# list `keepvals.dummy_cred` draws from) is AMBIGUOUS `dummy_credential`, not a MUST_KEEP placeholder.
B64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")


@lru_cache(maxsize=1)
def dummy_credentials() -> frozenset[str]:
    return frozenset(VV.handmade_lines("dummy_credentials.txt"))


def decoded_forms(v: str) -> list[str]:
    """Every base64 / URL-encoded reading of a value (one that does not change it is not a reading)."""
    out: list[str] = []
    if len(v) >= 4 and len(v) % 4 == 0 and B64_RE.fullmatch(v):
        try:
            out.append(base64.b64decode(v).decode())
        except (ValueError, UnicodeDecodeError):
            pass
    if "%" in v:
        d = urllib.parse.unquote(v)
        if d != v:
            out.append(d)
    return out


def is_encoded_dummy(v: str) -> bool:
    return any(d in dummy_credentials() for d in decoded_forms(v))


def encoded_dummy_pass(doc: Doc) -> None:
    """Reclassify encoded dummy credentials. An encoded value that decodes to a real placeholder
    (REPLACE_WITH_…, YOUR_…) stays MUST_KEEP `placeholder`; one that decodes to a dummy credential
    is AMBIGUOUS `dummy_credential`. Only the class and the kind change: the item keeps its span and
    its text, and no item is added or removed."""
    for it in doc.items:
        if it.cls == MUST_KEEP and it.kind == "placeholder" and is_encoded_dummy(doc.text[it.start:it.end]):
            it.cls = AMBIGUOUS
            it.category = it.kind = "dummy_credential"


@lru_cache(maxsize=1)
def _org_re() -> re.Pattern:
    orgs = [o for o in VV.handmade_lines("orgs.txt") if o not in ORG_REGEX_EXCLUDE]
    orgs.sort(key=len, reverse=True)
    return re.compile(r"(?<![\w.\-/@])(?:" + "|".join(re.escape(o) for o in orgs) + r")(?![\w\-/@]|\.\w)")


@lru_cache(maxsize=1)
def _title_re() -> re.Pattern:
    titles = [t for ts in VV.lang_table("job_titles.tsv").values() for t in ts if " " in t or len(t) >= 8 or t in ("CTO", "CEO")]
    titles = sorted(set(titles), key=len, reverse=True)
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(t) for t in titles) + r")(?![\w])")


def keep_pass(doc: Doc) -> None:
    _url_pass(doc)
    _simple(doc, GIT_REMOTE_RE, MUST_KEEP, "public_url")
    for rx in RESERVED_RES[:2]:
        _simple(doc, rx, MUST_KEEP, "reserved_address")
    for m in UUID_RE.finditer(doc.text):
        cls, kind = _uuid_class(doc.text, m.start())
        _ann(doc, m.start(), m.end(), cls, kind)
    for rx in HASH_RES:
        _simple(doc, rx, MUST_KEEP, "hash", check=_hash_ok)
    _simple(doc, SHA40_RE, MUST_KEEP, "sha", check=_hash_ok)
    for rx in SHORT_SHA_RES:
        _simple(doc, rx, MUST_KEEP, "sha", groups=True, check=lambda v, *a: bool(re.search(r"[a-f]", v) and re.search(r"\d", v)))
    for rx in ENVREF_RES:
        _simple(doc, rx, MUST_KEEP, "env_ref")
    for rx in PLACEHOLDER_RES:
        _simple(doc, rx, MUST_KEEP, "placeholder")
    _path_pass(doc)
    for rx in DATE_RES:
        _simple(doc, rx, MUST_KEEP, "date")
    for rx in RESERVED_RES[2:]:
        _simple(doc, rx, MUST_KEEP, "reserved_address")
    # remaining IPs: private ones are AMBIGUOUS, public ones in template text should not exist
    for m in IPV4_RE.finditer(doc.text):
        c = classify_ip(m.group(1))
        if c and c[1] == "rfc1918_ip":
            _ann(doc, m.start(1), m.end(1), c[0], c[1])
    _simple(doc, VERSION_RES[0], MUST_KEEP, "version", groups=True)
    _simple(doc, VERSION_RES[1], MUST_KEEP, "version", check=_version_ok)
    _simple(doc, VERSION_RES[2], MUST_KEEP, "version", groups=True)
    for rx in TICKET_RES:
        _simple(doc, rx, MUST_KEEP, "ticket_number", groups=bool(rx.groups), check=_ticket_ok)
    for rx in LINE_RES:
        _simple(doc, rx, MUST_KEEP, "line_number", groups=True)
    for rx in STATUS_RES:
        _simple(doc, rx, MUST_KEEP, "http_status", groups=True)
    for rx in PID_RES:
        _simple(doc, rx, MUST_KEEP, "pid", groups=True)
    for rx in PORT_RES:
        _simple(doc, rx, MUST_KEEP, "port", groups=True, check=_port_ok)
    for rx in IDENT_RES:
        _simple(doc, rx, MUST_KEEP, "code_identifier", groups=True)
    _simple(doc, _org_re(), MUST_KEEP, "org")
    _simple(doc, _title_re(), MUST_KEEP, "job_title")
    session_id_pass(doc)
    encoded_dummy_pass(doc)
