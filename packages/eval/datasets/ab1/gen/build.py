# SPDX-License-Identifier: Apache-2.0
"""Build AB-1 component A (agent traffic) end to end.

    python gen/build.py            # uses cache/pool.jsonl and cache/pool_real.jsonl (built by
                                   # gen/carriers.py if missing)

Outputs data/ab1.jsonl, data/stats.json, data/CANARY. Deterministic from MASTER_SEED.
"""
from __future__ import annotations

import collections
import json
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from annotate import carrier_pass, keep_pass  # noqa: E402
from carriers import (POOL_PATH, REAL_POOL_PATH, VIEW_HEADER_RE, build_pool, build_real_pool, cut_excerpt,  # noqa: E402
                      is_english, load_pool, load_real_pool)
from common import (CANARY, CLEAN_SHARE, DATA, ENCODED_SHARE, EXCERPT_MAX, EXCERPT_MIN, FB_PARQUET, KIND_TOTAL, KINDS,  # noqa: E402
                    LANGS, MULTILINGUAL_KINDS, SWE_PARQUET, rng_for)
from doc import MUST_MASK, Doc  # noqa: E402
from inject import file_style, inject  # noqa: E402
from secrets_gl import SecretFactory  # noqa: E402
from slots import Ctx  # noqa: E402
import tpl_file  # noqa: E402
import tpl_json  # noqa: E402
import tpl_lang  # noqa: E402
import tpl_log  # noqa: E402
import tpl_shell  # noqa: E402

TEMPLATES = {"file": tpl_file.generate, "shell": tpl_shell.generate, "log": tpl_log.generate, "tool_json": tpl_json.generate,
             "prompt": tpl_lang.generate_prompt, "ticket": tpl_lang.generate_ticket}

# carrier subtype quotas (shares within the carrier half of each kind); prompt and ticket carriers
# come from one source per language instead, see LANG_CARRIER_BUCKET.
CARRIER_MIX = {
    "file": {("file", "config"): 0.34, ("file", "config_cat"): 0.08, ("file", "fb_config_cat"): 0.04, ("file", "source"): 0.24,
             ("file", "source_cat"): 0.1, ("file", "fb_source_cat"): 0.04, ("file", "doc"): 0.16},
    "shell": {("shell", "git_diff"): 0.14, ("shell", "git_log"): 0.12, ("shell", "test_run"): 0.12, ("shell", "git_other"): 0.06,
              ("shell", "install"): 0.06, ("shell", "listing"): 0.06, ("shell", "grep"): 0.1, ("shell", "http"): 0.04, ("shell", "script"): 0.06,
              ("shell", "other"): 0.04, ("shell", "container"): 0.02, ("shell", "fb_git_other"): 0.04, ("shell", "fb_install"): 0.03,
              ("shell", "fb_test_run"): 0.03, ("shell", "fb_script"): 0.03, ("shell", "fb_http"): 0.02, ("shell", "fb_listing"): 0.02,
              ("shell", "fb_other"): 0.01},
    "log": {("log", "bash"): 0.7, ("log", "fb_run"): 0.15, ("log", "fb_ipython"): 0.15},
    "tool_json": {("tool_json", "str_replace_editor:create"): 0.3, ("tool_json", "str_replace_editor:str_replace"): 0.3,
                  ("tool_json", "execute_bash"): 0.2, ("tool_json", "fb:run"): 0.1, ("tool_json", "fb:run_ipython"): 0.1},
}

# Prompts and tickets: one carrier source per language. English keeps the English carrier material
# (openhands-feedback user messages, SWE-rebench issue descriptions); it/de/fr/es take the phase-A
# real pools (WildChat-1M first user turns, GitHub issues).
LANG_CARRIER_BUCKET = {
    "prompt": {"en": ("prompt", "user_message"), "it": ("prompt", "wildchat:it"), "de": ("prompt", "wildchat:de"),
               "fr": ("prompt", "wildchat:fr"), "es": ("prompt", "wildchat:es")},
    "ticket": {"en": ("ticket", "issue"), "it": ("ticket", "gh_issue:it"), "de": ("ticket", "gh_issue:de"),
               "fr": ("ticket", "gh_issue:fr"), "es": ("ticket", "gh_issue:es")},
}


@dataclass
class Plan:
    id: str
    split: str
    kind: str
    lang: str
    origin: str
    clean: bool = False
    carrier: dict | None = None
    excerpt: str = ""
    sub: str = ""
    header_path: str = ""
    encode: bool = False
    meta: dict = field(default_factory=dict)


# ------------------------------------------------------------------ planning

def split_counts(n: int) -> tuple[int, int]:
    dev = round(n / 6)
    return dev, n - dev


def make_plan() -> list[Plan]:
    plans: list[Plan] = []
    for kind in KINDS:
        total = KIND_TOTAL[kind]
        cells = []  # (lang, origin, count)
        if kind in MULTILINGUAL_KINDS:
            per = total // len(LANGS)
            for lang in LANGS:
                cells.append((lang, "carrier", per // 2))
                cells.append((lang, "template", per - per // 2))
        else:
            cells.append(("en", "carrier", total // 2))
            cells.append(("en", "template", total - total // 2))
        for lang, origin, n in cells:
            dev, test = split_counts(n)
            for i in range(n):
                plans.append(Plan("", "dev" if i < dev else "test", kind, lang, origin))
    # ids: shuffled within kind, stable
    out = []
    for kind in KINDS:
        ps = [p for p in plans if p.kind == kind]
        rng = rng_for("ids", kind)
        rng.shuffle(ps)
        for i, p in enumerate(ps):
            p.id = f"ab1-{kind}-{i + 1:04d}"
        out.extend(sorted(ps, key=lambda x: x.id))
    assign_clean(out)
    return out


def assign_clean(plans: list[Plan]) -> None:
    """Exactly round(20%) clean documents per (split, kind), spread over languages and origins."""
    for split in ("dev", "test"):
        for kind in KINDS:
            group = [p for p in plans if p.split == split and p.kind == kind]
            k = round(CLEAN_SHARE * len(group))
            rng = rng_for("clean", split, kind)
            by_cell = collections.defaultdict(list)
            for p in group:
                by_cell[(p.lang, p.origin)].append(p)
            cells = sorted(by_cell)
            for c in cells:
                rng.shuffle(by_cell[c])
            # round-robin over cells so every language/origin gets its share
            chosen = 0
            idx = 0
            while chosen < k:
                c = cells[idx % len(cells)]
                lst = by_cell[c]
                taken = sum(1 for p in lst if p.clean)
                if taken < len(lst):
                    lst[taken].clean = True
                    chosen += 1
                idx += 1


# ------------------------------------------------------------------ carriers

def header_path_of(cand: dict) -> str:
    m = VIEW_HEADER_RE.match(cand["field_text"])
    if m:
        return m.group(1)
    cmd = cand.get("command", "")
    m = re.search(r"(?:cat|head|tail|sed -n \S+)\s+(\S+)\s*$", cmd)
    return m.group(1) if m else ""


def carrier_buckets(kind: str, lang: str) -> dict:
    """The carrier buckets a (kind, language) cell draws from, with their shares."""
    if kind in LANG_CARRIER_BUCKET:
        return {LANG_CARRIER_BUCKET[kind][lang]: 1.0}
    return CARRIER_MIX[kind]


def assign_carriers(plans: list[Plan]) -> None:
    pool = load_pool() + load_real_pool()
    by_bucket = collections.defaultdict(list)
    for c in pool:
        by_bucket[(c["kind"], c["sub"])].append(c)
    used_groups: dict[str, set] = collections.defaultdict(set)
    for kind in KINDS:
        targets = [p for p in plans if p.kind == kind and p.origin == "carrier"]
        if not targets:
            continue
        by_lang: dict[str, list[Plan]] = collections.defaultdict(list)
        for p in targets:
            by_lang[p.lang].append(p)
        for lang in sorted(by_lang):
            mix = carrier_buckets(kind, lang)
            n = len(by_lang[lang])
            quotas = {b: int(n * share) for b, share in mix.items()}
            rest = n - sum(quotas.values())
            for b in sorted(mix, key=lambda b: -mix[b])[:rest]:
                quotas[b] += 1
            chosen = []
            seen_text: set[str] = set()
            for bucket in sorted(quotas):
                q = quotas[bucket]
                got = 0
                for cand in by_bucket.get(bucket, []):
                    if got >= q:
                        break
                    if cand["group"] in used_groups[kind]:
                        continue
                    ex = excerpt_for(kind, cand)
                    if ex is None:
                        continue
                    sig = " ".join(cand["field_text"][ex[0]:ex[1]].lower().split())[:150]
                    if sig in seen_text:
                        continue  # the same canned message reused in another session
                    seen_text.add(sig)
                    used_groups[kind].add(cand["group"])
                    chosen.append((bucket, cand, ex))
                    got += 1
                if got < q:
                    raise RuntimeError(f"not enough carriers for {bucket}: {got}/{q}")
            rng = rng_for("carrier-assign", kind, lang)
            rng.shuffle(chosen)
            for p, (bucket, cand, (s, e)) in zip(sorted(by_lang[lang], key=lambda x: x.id), chosen):
                p.carrier = {"dataset": cand["dataset"], "revision": cand["revision"], "row": cand["row"],
                             "start": s, "end": e}
                if "url" in cand:
                    p.carrier["url"] = cand["url"]
                if "license" in cand:
                    p.carrier["license"] = cand["license"]
                p.excerpt = cand["field_text"][s:e]
                p.sub = bucket[1]
                p.header_path = header_path_of(cand)
                p.meta["command"] = cand.get("command", "")


def excerpt_for(kind: str, cand: dict) -> tuple[int, int] | None:
    text = cand["field_text"]
    rng = rng_for("excerpt", cand["cid"])
    if kind == "tool_json":
        if EXCERPT_MIN <= len(text) <= EXCERPT_MAX:
            try:
                json.loads(text)
            except json.JSONDecodeError:
                return None
            return 0, len(text)
        return None
    if kind == "ticket" and "span" in cand:
        lo, hi = cand["span"]
    else:
        lo, hi = 0, len(text)
    seg = text[lo:hi]
    # English prose carriers must read as English; the it/de/fr/es carriers were selected by the
    # phase-A scripts under the same stop-word check for their own language.
    if kind in ("prompt", "ticket") and cand.get("lang", "en") == "en" and not is_english(seg):
        return None
    if kind in ("prompt", "ticket") and EXCERPT_MIN <= len(seg.strip()) and len(seg) <= EXCERPT_MAX:
        s = lo + (len(seg) - len(seg.lstrip("\n\r")))
        e = hi - (len(seg) - len(seg.rstrip()))
        if (s == 0 or text[s - 1] == "\n") and EXCERPT_MIN <= e - s:
            return s, e
    target = rng.randint(700, 3600)
    return cut_excerpt(text, lo, hi, rng, target)


# ------------------------------------------------------------------ generation

FACTORY: SecretFactory | None = None


def generate(plan: Plan, encode: bool) -> tuple[Doc, Ctx, str]:
    for attempt in range(25):
        rng = rng_for("doc", plan.id, attempt)
        ctx = Ctx(rng, plan.lang, plan.clean, FACTORY)
        ctx.kind = plan.kind
        ctx.encode = encode
        ctx.enc_rng = rng_for("enc", plan.id, attempt)
        if plan.origin == "template":
            doc, fam = TEMPLATES[plan.kind](ctx)
        else:
            doc = Doc(plan.excerpt)
            if plan.kind == "file":
                ctx.file_style = {"doc": "doc"}.get(file_style(plan.header_path, plan.excerpt), file_style(plan.header_path, plan.excerpt))
            carrier_pass(doc)
            if not plan.clean:
                inject(ctx, doc, plan.kind, plan.sub, plan.header_path, plan.meta.get("command", ""))
            ctx.finish(doc)
            fam = plan.sub
        keep_pass(doc)
        doc.check()
        n_mm = len(doc.mm_items())
        if plan.clean and n_mm:
            raise AssertionError(f"{plan.id}: clean document with MUST_MASK items")
        if not plan.clean and n_mm == 0:
            continue
        if plan.kind == "tool_json":
            json.loads(doc.text)
        return doc, ctx, fam
    raise RuntimeError(f"{plan.id}: could not generate a valid document")


def injected_count(doc: Doc) -> int:
    return sum(1 for it in doc.items if it.cls == MUST_MASK and it.enc_of_uid is None)


def main() -> None:
    global FACTORY
    if not (SWE_PARQUET.exists() and FB_PARQUET.exists()):
        import download
        download.main()
    if not POOL_PATH.exists():
        build_pool()
    if not REAL_POOL_PATH.exists():
        build_real_pool()
    FACTORY = SecretFactory()
    plans = make_plan()
    assign_carriers(plans)
    # pass 1: no encoded copies
    first = {}
    for p in plans:
        doc, ctx, fam = generate(p, False)
        first[p.id] = (injected_count(doc), ctx.hookable, fam)
    total_injected = sum(v[0] for v in first.values())
    target = round(ENCODED_SHARE * total_injected)
    rng = rng_for("encode-select")
    eligible = [p for p in plans if not p.clean and first[p.id][1]]
    rng.shuffle(eligible)
    selected = {p.id for p in eligible[:target]}
    if len(selected) < target:
        raise RuntimeError(f"only {len(selected)} documents can carry an encoded copy, need {target}")
    rows = []
    stats_rules = collections.Counter()
    fam_counts = collections.Counter()
    for p in plans:
        enc = p.id in selected
        doc, ctx, fam = generate(p, enc)
        if enc and ctx.encoded_label is None:
            raise RuntimeError(f"{p.id}: selected for an encoded copy but no hook applied")
        if injected_count(doc) != first[p.id][0]:
            raise RuntimeError(f"{p.id}: base document changed between passes")
        items = doc.finalize()
        for it in items:
            if it["kind"].startswith("gitleaks:") and it["encoded_of"] is None:
                stats_rules[it["kind"].split(":", 1)[1]] += 1
        fam_counts[(p.kind, p.origin, fam)] += 1
        rows.append({"id": p.id, "split": p.split, "kind": p.kind, "lang": p.lang, "origin": p.origin, "carrier": p.carrier,
                     "text": doc.text, "items": items})
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "ab1.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (DATA / "CANARY").write_text(CANARY + "\n", encoding="utf-8")
    write_stats(rows, stats_rules, fam_counts, total_injected, target)
    print(f"wrote {len(rows)} documents; injected values {total_injected}; encoded copies {target}")


def write_stats(rows, rules, fams, total_injected: int, n_encoded: int) -> None:
    def key(*xs):
        return "|".join(xs)
    docs = collections.Counter()
    cls_cat = collections.defaultdict(collections.Counter)
    clean = collections.Counter()
    enc = collections.Counter()
    for r in rows:
        docs[key(r["split"], r["kind"], r["lang"], r["origin"])] += 1
        mm = [it for it in r["items"] if it["class"] == "MUST_MASK"]
        if not mm:
            clean[r["split"]] += 1
        for it in r["items"]:
            cls_cat[r["split"]][key(it["class"], it["category"])] += 1
            if it["encoded_of"] is not None:
                enc[r["split"]] += 1
    factory = FACTORY
    stats = {
        "documents": len(rows),
        "documents_by_split_kind_lang_origin": dict(sorted(docs.items())),
        "items_by_split_class_category": {s: dict(sorted(c.items())) for s, c in sorted(cls_cat.items())},
        "clean_documents": dict(clean),
        "injected_values_total": total_injected,
        "encoded_copies": dict(enc),
        "encoded_copies_total": n_encoded,
        "gitleaks": {"tag": "v8.30.1", "commit": "83d9cd684c87d95d656c1458ef04895a7f1cbd8e",
                     "rules_in_config": len(factory.rules) + len(factory.excluded) + len(factory.failed),
                     "rules_usable": len(factory.rules), "rules_excluded": factory.excluded, "rules_failed": factory.failed,
                     "secret_values_per_rule": dict(sorted(rules.items())), "rules_drawn_at_least_once": len(rules)},
        "template_families": {key(*k): v for k, v in sorted(fams.items())},
    }
    (DATA / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
