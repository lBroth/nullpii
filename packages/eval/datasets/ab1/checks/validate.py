# SPDX-License-Identifier: Apache-2.0
"""Validate AB-1 component A (data/ab1.jsonl) against SPEC.md and the build brief.

    python checks/validate.py                 # all checks, including the full carrier scan
    python checks/validate.py --no-carrier-scan

Checks: schema; offsets in range, non-empty, non-overlapping; encoded copies decode to their original;
the frozen file is byte-identical to a fresh in-memory rebuild (so every item covers exactly the value
the generator placed); split / kind / language shares; clean-document share; encoded-copy share;
Luhn / mod-97 / check-character validity; gitleaks format of every drawn secret; minimum test-split
counts; tool_json documents parse; carrier records and excerpt bounds; canary; the two audit rules of
2026-10-25 (a UUID after a session-like key is AMBIGUOUS session_id; an encoded dummy credential is
AMBIGUOUS dummy_credential); every MUST_MASK value fictional (absent from the full text of all four
carrier datasets at the pinned revisions, the two phase-A real pools included whole).
Exit status 1 if any check fails.
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import io
import ipaddress
import json
import re
import sys
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gen"))

import values as VV  # noqa: E402
from common import (CACHE, CANARY, CLEAN_SHARE, ENCODED_SHARE, EXCERPT_MAX, EXCERPT_MIN, FB_DATASET, FB_PARQUET,  # noqa: E402
                    FB_REVISION, GH_ISSUES_DATASET, GH_ISSUES_REVISION, KIND_TOTAL, KINDS, LANGS,
                    MULTILINGUAL_KINDS, REAL_LANGS, SWE_DATASET, SWE_PARQUET, SWE_REVISION,
                    WILDCHAT_DATASET, WILDCHAT_REVISION)

DATA = ROOT / "data" / "ab1.jsonl"
REAL_DIR = CACHE / "real"
CARRIER_KEYS = {"dataset", "revision", "row", "start", "end"}
CARRIER_OPTIONAL_KEYS = {"url", "license"}  # github-issues carriers only
PINNED = {(SWE_DATASET, SWE_REVISION), (FB_DATASET, FB_REVISION),
          (WILDCHAT_DATASET, WILDCHAT_REVISION), (GH_ISSUES_DATASET, GH_ISSUES_REVISION)}
KIND_SHARE = {k: v / 1200 for k, v in KIND_TOTAL.items()}
MM_CATS = {"secret", "person", "email", "phone", "address", "account", "ip", "mac", "url", "passport", "driver_license",
           "national_id", "iban", "card"}
ID_CATS = {"account", "passport", "driver_license", "national_id", "iban", "card"}
MIN_TEST = {"secret": 150, "person": 150, "email": 150, "phone": 150, "address": 150, "ids": 150, "ip": 150, "mac": 40, "url": 40}
KEEP_MIN_TEST = 100
PP = 0.02

# The two corrections of the 2026-10-25 audit (gen/annotate.py: keep_pass), re-derived here from the
# frozen text alone: a UUID directly after a session-like key is AMBIGUOUS session_id, and an encoded
# value that decodes to a dummy credential of the SPEC AMBIGUOUS list is AMBIGUOUS dummy_credential.
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
SESSION_KEY_RE = re.compile(r"(?i)(?<![\w])(?:session_id|sessionid|session|sid|token|cookie)[\"']?\s*[:=]\s*[\"']?$")
SESSION_KEY_BACK = 40
B64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
DUMMY_CREDENTIALS = frozenset(VV.handmade_lines("dummy_credentials.txt"))
SESSION_ID_COUNTS = {"dev": 3, "test": 20}
ENCODED_DUMMY_ITEMS = 1

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def load() -> list[dict]:
    with DATA.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


# ------------------------------------------------------------------ structure

def check_schema(rows: list[dict]) -> None:
    bad = []
    ids = set()
    for r in rows:
        keys = {"id", "split", "kind", "lang", "origin", "carrier", "text", "items"}
        if set(r) != keys:
            bad.append((r.get("id"), "keys"))
            continue
        if r["id"] in ids:
            bad.append((r["id"], "duplicate id"))
        ids.add(r["id"])
        if r["split"] not in ("dev", "test") or r["kind"] not in KINDS or r["lang"] not in LANGS or r["origin"] not in ("carrier", "template"):
            bad.append((r["id"], "enum"))
        if (r["origin"] == "carrier") != (r["carrier"] is not None):
            bad.append((r["id"], "carrier/origin"))
        if r["carrier"] is not None:
            ck = set(r["carrier"])
            if not CARRIER_KEYS <= ck or ck - CARRIER_KEYS - CARRIER_OPTIONAL_KEYS:
                bad.append((r["id"], "carrier keys"))
        for it in r["items"]:
            if set(it) != {"start", "end", "class", "category", "kind", "encoded_of"}:
                bad.append((r["id"], "item keys"))
            elif it["class"] not in ("MUST_MASK", "MUST_KEEP", "AMBIGUOUS"):
                bad.append((r["id"], "class"))
            elif it["class"] == "MUST_MASK" and it["category"] not in MM_CATS:
                bad.append((r["id"], f"category {it['category']}"))
            elif it["class"] != "MUST_MASK" and it["category"] != it["kind"]:
                bad.append((r["id"], "keep/ambiguous category must equal kind"))
    check("schema: fields, enums, unique ids", not bad, f"{len(rows)} rows; problems: {bad[:5]}")


def check_offsets(rows: list[dict]) -> None:
    bad, overlaps, ws = [], [], []
    for r in rows:
        t = r["text"]
        its = sorted(r["items"], key=lambda x: (x["start"], x["end"]))
        for it in its:
            if not (0 <= it["start"] < it["end"] <= len(t)):
                bad.append((r["id"], it))
            v = t[it["start"]:it["end"]]
            if v != v.strip() or not v:
                ws.append((r["id"], v[:30]))
        for a, b in zip(its, its[1:]):
            if b["start"] < a["end"]:
                overlaps.append((r["id"], a, b))
    check("offsets: inside text, non-empty", not bad, f"{len(bad)} bad")
    check("offsets: no item has leading/trailing whitespace", not ws, f"{len(ws)} items, e.g. {ws[:3]}")
    check("items: no overlaps", not overlaps, f"{len(overlaps)} overlapping pairs")


def check_encoded(rows: list[dict]) -> tuple[int, int]:
    n_enc, bad = 0, []
    injected = 0
    for r in rows:
        t = r["text"]
        for it in r["items"]:
            if it["class"] != "MUST_MASK":
                continue
            if it["encoded_of"] is None:
                injected += 1
                continue
            n_enc += 1
            o = r["items"][it["encoded_of"]]
            ov, ev = t[o["start"]:o["end"]], t[it["start"]:it["end"]]
            ok = o["class"] == "MUST_MASK" and o["encoded_of"] is None and o["category"] == it["category"]
            how = it["kind"].split(":", 1)[0]
            if how == "base64":
                ok = ok and base64.b64decode(ev).decode() == _json_unescape(ov)
            elif how == "urlencoded":
                ok = ok and urllib.parse.unquote(ev) == _json_unescape(ov)
            else:
                ok = False
            if not ok:
                bad.append((r["id"], ov[:20], ev[:30]))
    check("encoded copies: link to a MUST_MASK original and decode to it", not bad, f"{n_enc} copies; bad {bad[:3]}")
    share = n_enc / injected if injected else 0
    check("encoded copies: ~5% of injected values (5% ± 1pp)", abs(share - ENCODED_SHARE) <= 0.01,
          f"{n_enc} of {injected} injected values = {share:.2%}")
    return n_enc, injected


def _json_unescape(s: str) -> str:
    if "\\" not in s:
        return s
    try:
        return json.loads('"' + s + '"')
    except json.JSONDecodeError:
        return s


# ------------------------------------------------------------------ shares

def check_shares(rows: list[dict]) -> None:
    n = len(rows)
    check("size: 1,200 documents, dev 200 / test 1,000", n == 1200 and sum(r["split"] == "dev" for r in rows) == 200,
          f"{n} documents, dev {sum(r['split'] == 'dev' for r in rows)}")
    for k in KINDS:
        rk = [r for r in rows if r["kind"] == k]
        share = len(rk) / n
        check(f"kind share {k}: {KIND_SHARE[k]:.0%} ± 2pp", abs(share - KIND_SHARE[k]) <= PP, f"{share:.2%}")
        dev = sum(r["split"] == "dev" for r in rk) / len(rk)
        check(f"split {k}: dev 1/6 ± 2pp", abs(dev - 1 / 6) <= PP, f"dev {dev:.2%}")
        if k in MULTILINGUAL_KINDS:
            for lang in LANGS:
                lk = [r for r in rk if r["lang"] == lang]
                ls = len(lk) / len(rk)
                check(f"language share {k}/{lang}: 20% ± 2pp", abs(ls - 0.2) <= PP, f"{ls:.2%}")
                ncar = sum(r["origin"] == "carrier" for r in lk)
                check(f"carrier share {k}/{lang}: exactly 50%", bool(lk) and 2 * ncar == len(lk),
                      f"{ncar}/{len(lk)} = {ncar / len(lk):.2%}")
        else:
            check(f"language {k}: en only", all(r["lang"] == "en" for r in rk))
            orig = sum(r["origin"] == "carrier" for r in rk) / len(rk)
            check(f"carrier share {k}: 50% ± 2pp", abs(orig - 0.5) <= PP, f"{orig:.2%}")
    for split in ("dev", "test", "all"):
        rs = rows if split == "all" else [r for r in rows if r["split"] == split]
        clean = sum(1 for r in rs if not any(it["class"] == "MUST_MASK" for it in r["items"]))
        check(f"clean documents ({split}): 20% ± 2pp", abs(clean / len(rs) - CLEAN_SHARE) <= PP, f"{clean}/{len(rs)} = {clean / len(rs):.2%}")


# ------------------------------------------------------------------ value validity

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def check_values(rows: list[dict]) -> None:
    from secrets_gl import SecretFactory, canonical_line
    factory = SecretFactory()
    stats = collections.Counter()
    bad = collections.defaultdict(list)
    for r in rows:
        t = r["text"]
        for it in r["items"]:
            if it["class"] != "MUST_MASK" or it["encoded_of"] is not None:
                continue
            v = _json_unescape(t[it["start"]:it["end"]])
            cat, kind = it["category"], it["kind"]
            if kind.startswith("urlencoded:"):
                v, kind = urllib.parse.unquote(v), kind.split(":", 1)[1]
            elif kind.startswith("base64:"):
                v, kind = base64.b64decode(v).decode(), kind.split(":", 1)[1]
            ok = True
            if cat == "card":
                ok = VV.luhn_ok(v) and len(_digits(v)) in (15, 16)
            elif cat == "iban":
                ok = VV.iban_ok(v)
                if ok and v.replace(" ", "").startswith("IT"):
                    b = v.replace(" ", "")
                    ok = VV.it_cin(b[5:]) == b[4]
                if ok and v.replace(" ", "").startswith("FR"):
                    b = v.replace(" ", "")[4:]
                    ok = VV.fr_rib_key(b[:5], b[5:10], b[10:21]) == b[21:]
                if ok and v.replace(" ", "").startswith("ES"):
                    b = v.replace(" ", "")[4:]
                    ok = VV.es_dc(b[:4], b[4:8], b[10:]) == b[8:10]
            elif kind == "it_codice_fiscale":
                ok = VV.cf_ok(v)
            elif kind in ("es_dni", "es_nie"):
                ok = VV.dni_ok(v)
            elif kind == "fr_nir":
                ok = VV.nir_ok(v)
            elif kind == "de_steuer_id":
                ok = VV.steuer_ok(v)
            elif kind == "us_ssn":
                ok = bool(re.fullmatch(r"(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}", v))
            elif kind == "gb_nino":
                ok = bool(re.fullmatch(r"[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]", v))
            elif cat == "email":
                ok = bool(re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", v))
            elif cat == "ip":
                try:
                    a = ipaddress.ip_address(v)
                    ok = a.is_global and not any(a in ipaddress.ip_network(n) for n in
                                                 ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32") if ipaddress.ip_network(n).version == a.version)
                except ValueError:
                    ok = False
            elif cat == "mac":
                ok = bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}", v))
            elif cat == "phone":
                ok = 9 <= len(_digits(v)) <= 15
            elif cat == "secret" and kind.startswith("gitleaks:"):
                rid = kind.split(":", 1)[1]
                rule = factory.by_id[rid]
                vv = v if rid != "gitlab-session-cookie" else "_gitlab_session=" + v
                if rid == "private-key":
                    m = re.search(r"-----BEGIN ([A-Z ]+)-----", t[max(0, it["start"] - 60):it["start"]].replace("\\n", "\n"))
                    vv = f"-----BEGIN {m.group(1)}-----\n{v}\n-----END {m.group(1)}-----" if m else v
                ok = factory._verify(rule, vv) is None
            stats[cat] += 1
            if not ok:
                bad[cat].append((r["id"], v[:40]))
    check("cards: Luhn-valid", not bad["card"], f"{stats['card']} checked; bad {bad['card'][:3]}")
    check("IBANs: mod-97 (and IT CIN, FR RIB key, ES DC) valid", not bad["iban"], f"{stats['iban']} checked; bad {bad['iban'][:3]}")
    check("national ids: valid check characters / structure", not bad["national_id"], f"{stats['national_id']} checked; bad {bad['national_id'][:3]}")
    check("secrets: every gitleaks-drawn value matches its rule (regex, entropy, allowlists)", not bad["secret"],
          f"{stats['secret']} secrets checked; bad {bad['secret'][:3]}")
    for cat in ("email", "ip", "mac", "phone"):
        check(f"{cat}: format", not bad[cat], f"{stats[cat]} checked; bad {bad[cat][:3]}")


def check_counts(rows: list[dict]) -> None:
    mm = collections.Counter()
    keep = collections.Counter()
    for r in rows:
        if r["split"] != "test":
            continue
        for it in r["items"]:
            if it["class"] == "MUST_MASK":
                mm["ids" if it["category"] in ID_CATS else it["category"]] += 1
            elif it["class"] == "MUST_KEEP":
                keep[it["kind"]] += 1
    for cat, need in MIN_TEST.items():
        check(f"test split MUST_MASK {cat} >= {need}", mm[cat] >= need, str(mm[cat]))
    low = {k: v for k, v in keep.items() if v < KEEP_MIN_TEST}
    check(f"test split: every MUST_KEEP kind >= {KEEP_MIN_TEST}", not low, f"{len(keep)} kinds; low: {low}")


def check_misc(rows: list[dict]) -> None:
    bad_json = [r["id"] for r in rows if r["kind"] == "tool_json" and not _parses(r["text"])]
    check("tool_json documents are valid JSON", not bad_json, f"bad: {bad_json[:5]}")
    bad_ex = []
    for r in rows:
        c = r["carrier"]
        if c is None:
            continue
        if not (EXCERPT_MIN <= c["end"] - c["start"] <= EXCERPT_MAX):
            bad_ex.append((r["id"], c["end"] - c["start"]))
        clean = not any(it["class"] == "MUST_MASK" for it in r["items"])
        if clean and len(r["text"]) != c["end"] - c["start"]:
            bad_ex.append((r["id"], "clean carrier text differs from excerpt length"))
    check("carrier excerpts: 300-6,000 characters; clean carrier docs are the verbatim excerpt", not bad_ex, f"bad {bad_ex[:3]}")
    bad_c = []
    seen_datasets = collections.Counter()
    for r in rows:
        c = r["carrier"]
        if c is None:
            continue
        seen_datasets[c["dataset"]] += 1
        if (c["dataset"], c["revision"]) not in PINNED:
            bad_c.append((r["id"], "unpinned dataset/revision"))
            continue
        if c["dataset"] == GH_ISSUES_DATASET:
            full, _, number = c["row"].rpartition("#")
            if not ({"url", "license"} <= set(c) and number.isdigit() and full
                    and c["url"] == f"https://github.com/{full}/issues/{number}"):
                bad_c.append((r["id"], "github carrier without url/licence"))
        elif set(c) & CARRIER_OPTIONAL_KEYS:
            bad_c.append((r["id"], "url/licence on a non-github carrier"))
        elif c["dataset"] == WILDCHAT_DATASET:
            if not re.fullmatch(r"[0-9a-f]{32}/turn\d+", c["row"]):
                bad_c.append((r["id"], "wildchat row"))
    check("carrier records: pinned dataset and revision; WildChat row <hash>/turn<i>; GitHub row "
          "<repo>#<number> with its url and repository SPDX licence", not bad_c, f"bad {bad_c[:3]}")
    check("carrier records: all four dataset/revision pairs are used", set(seen_datasets) == {d for d, _ in PINNED},
          f"{len(seen_datasets)} datasets: {dict(seen_datasets)}")
    canary = (ROOT / "data" / "CANARY").read_text(encoding="utf-8").splitlines()[0] if (ROOT / "data" / "CANARY").exists() else ""
    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    check("canary: data/CANARY first line and README", canary == CANARY and CANARY in readme)


# ------------------------------------------------------------------ audit rules (2026-10-25)

def _decodings(v: str) -> list[str]:
    """Every base64 / URL-encoded reading of a value (a reading that changes nothing does not count)."""
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


def check_audit_rules(rows: list[dict]) -> None:
    """The two corrections of the audit, re-derived from the frozen text: the class and kind of every
    UUID-shaped and of every encoded item must be the one the rules give."""
    uuid_bad: list[tuple] = []
    session = collections.Counter()
    enc_bad: list[tuple] = []
    enc_dummy = 0
    placeholder_encoded = 0
    for r in rows:
        t = r["text"]
        for it in r["items"]:
            v = t[it["start"]:it["end"]]
            if it["kind"] in ("uuid", "session_id"):
                after = bool(SESSION_KEY_RE.search(t[max(0, it["start"] - SESSION_KEY_BACK):it["start"]]))
                want = ("AMBIGUOUS", "session_id") if after else ("MUST_KEEP", "uuid")
                if (it["class"], it["kind"]) != want or not UUID_RE.fullmatch(v):
                    uuid_bad.append((r["id"], it["class"], it["kind"], want))
                elif it["kind"] == "session_id":
                    session[r["split"]] += 1
            dummy = any(d in DUMMY_CREDENTIALS for d in _decodings(v))
            if it["class"] == "MUST_KEEP" and it["kind"] == "placeholder":
                if dummy:
                    enc_bad.append((r["id"], "encoded dummy credential left as a MUST_KEEP placeholder"))
                elif _decodings(v):
                    placeholder_encoded += 1
            elif it["class"] == "AMBIGUOUS" and it["kind"] == "dummy_credential" and dummy:
                enc_dummy += 1
    check("audit rule 1: a UUID directly after a session-like key (`session`, `session_id`, `sessionId`, `sid`, "
          "`token`, `cookie`, `=` or `:`, optional quotes, case-insensitive) is AMBIGUOUS session_id, every other "
          "UUID is MUST_KEEP uuid",
          not uuid_bad and dict(session) == SESSION_ID_COUNTS,
          f"{dict(session)} session_id items; {len(uuid_bad)} wrong: {uuid_bad[:3]}")
    check("audit rule 2: a base64 / URL-encoded value that decodes to a dummy credential of the SPEC AMBIGUOUS "
          "list is AMBIGUOUS dummy_credential, not a MUST_KEEP placeholder",
          not enc_bad and enc_dummy == ENCODED_DUMMY_ITEMS,
          f"{enc_dummy} encoded dummy credential item(s), {placeholder_encoded} encoded placeholders that decode "
          f"to a real placeholder stay MUST_KEEP; {len(enc_bad)} wrong: {enc_bad[:3]}")


def _parses(t: str) -> bool:
    try:
        json.loads(t)
        return True
    except json.JSONDecodeError:
        return False


# ------------------------------------------------------------------ rebuild equality

def check_rebuild() -> None:
    import build
    tmp = io.StringIO()
    target = ROOT / "data"
    frozen = DATA.read_bytes()
    frozen_stats = (target / "stats.json").read_bytes()
    with redirect_stdout(tmp):
        build.main()
    same = DATA.read_bytes() == frozen and (target / "stats.json").read_bytes() == frozen_stats
    if not same:
        DATA.write_bytes(frozen)
        (target / "stats.json").write_bytes(frozen_stats)
    check("determinism: a fresh build reproduces data/ab1.jsonl and stats.json byte for byte "
          "(each item was checked against the value the generator placed)", same, hashlib.sha256(frozen).hexdigest()[:16])


# ------------------------------------------------------------------ fictional values

def mm_values(rows: list[dict]) -> dict[str, list[str]]:
    vals: dict[str, list[str]] = collections.defaultdict(list)
    for r in rows:
        t = r["text"]
        for it in r["items"]:
            if it["class"] == "MUST_MASK":
                v = _json_unescape(t[it["start"]:it["end"]])
                vals[v].append(r["id"])
    return vals


def name_tokens() -> set[str]:
    out = set()
    for lang in LANGS:
        for which in ("given_male", "given_female", "surnames"):
            for n in VV.names(lang, which):
                out.add(n)
                out.add(n.lower())
                out.add(VV.fold(n, lang).lower())
    return out


def scan_carriers(values: list[str]) -> dict[str, int]:
    """Whole-token occurrence counts of each value in all text of every carrier dataset (cached per value)."""
    import ahocorasick
    import pyarrow.parquet as pq
    cache = CACHE / "carrier_scan_values_v2.json"
    known: dict[str, int] = json.loads(cache.read_text()) if cache.exists() else {}
    todo = sorted(set(values) - set(known))
    if todo:
        A = ahocorasick.Automaton()
        for i, v in enumerate(todo):
            A.add_word(v, i)
        A.make_automaton()
        hits: collections.Counter = collections.Counter()

        def feed(text: str | None) -> None:
            if not text:
                return
            for end, i in A.iter(text):
                v = todo[i]
                s = end - len(v) + 1
                before = text[s - 1] if s > 0 else " "
                after = text[end + 1] if end + 1 < len(text) else " "
                if before.isalnum() or after.isalnum():
                    continue
                hits[v] += 1

        pf = pq.ParquetFile(SWE_PARQUET)
        for rg in range(pf.metadata.num_row_groups):
            tab = pf.read_row_group(rg, columns=["trajectory", "model_patch"]).to_pylist()
            for rec in tab:
                feed(rec["model_patch"])
                for m in rec["trajectory"]:
                    feed(m["content"])
                    for tc in m["tool_calls"] or []:
                        feed(tc["function"]["arguments"])
        for rec in pq.read_table(FB_PARQUET).to_pylist():
            feed(rec["feedback"])
            for st in rec["trajectory"]:
                feed(st["content"])
                feed(st["extras"])
                feed(st["message"])
        # the phase-A real pools, whole (not only the candidates the build selected from)
        for lang in REAL_LANGS:
            with (REAL_DIR / f"wildchat_{lang}.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    feed(json.loads(line)["text"])
            with (REAL_DIR / f"gh_issues_{lang}.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    row = json.loads(line)
                    feed(row.get("title"))
                    feed(row.get("body"))
        for v in todo:
            known[v] = hits.get(v, 0)
        cache.write_text(json.dumps(known, indent=0, sort_keys=True))
    return {v: known[v] for v in values}


def check_fictional(rows: list[dict]) -> None:
    vals = mm_values(rows)
    names = name_tokens()
    exempt = {v for v in vals if (" " not in v and (v in names or v.lower() in names))}
    to_scan = sorted(v for v in vals if v not in exempt)
    hits = scan_carriers(to_scan)
    found = {v: n for v, n in hits.items() if n}
    check("fictional: no MUST_MASK value occurs in the carrier datasets' text (whole-token match, all four "
          "datasets, every row)",
          not found, f"{len(to_scan)} values scanned, {len(exempt)} single-token list names exempt; found: {list(found.items())[:10]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-carrier-scan", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()
    rows = load()
    check_schema(rows)
    check_offsets(rows)
    check_encoded(rows)
    check_shares(rows)
    check_values(rows)
    check_counts(rows)
    check_misc(rows)
    check_audit_rules(rows)
    if not args.no_rebuild:
        check_rebuild()
    if not args.no_carrier_scan:
        check_fictional(rows)
    width = max(len(n) for n, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
