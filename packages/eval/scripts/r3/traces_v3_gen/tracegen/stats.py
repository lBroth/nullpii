# SPDX-License-Identifier: Apache-2.0
"""Summary statistics of a generated corpus (no document text is reported)."""

from __future__ import annotations

import statistics
from collections import Counter

from .core import DISTRACTOR_CLASSES, GOLD_LABELS
from .templates import REGISTRY

LEN_BUCKETS = [(300, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 12000), (12000, 16000), (16000, 20001)]


def _pct(values: list[int], q: float) -> int:
    s = sorted(values)
    if not s:
        return 0
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo))


def compute(docs: list) -> dict:
    n = len(docs)
    per_tpl = Counter(d.template_id for d in docs)
    span_counts = Counter()
    span_docs = Counter()
    reg_counts = Counter()
    reg_docs = Counter()
    lengths = []
    gold_per_doc = []
    dist_per_doc = []
    conv_lang = Counter()
    text_lang_docs = Counter()
    locale_docs = Counter()
    modes = Counter()
    attempts = Counter()
    for d in docs:
        a = d.assembled
        lengths.append(len(a.text))
        gold_per_doc.append(len(a.spans))
        dist_per_doc.append(len(a.regions))
        labels = Counter(s["label"] for s in a.spans)
        classes = Counter(r["class"] for r in a.regions)
        span_counts.update(labels)
        span_docs.update(labels.keys())
        reg_counts.update(classes)
        reg_docs.update(classes.keys())
        conv_lang[d.lang] += 1
        text_lang_docs.update(d.text_langs)
        locale_docs.update(d.locales)
        modes[d.mode] += 1
        attempts[d.attempts] += 1
    no_secret = sum(1 for d in docs if not any(s["label"] == "secret" for s in d.assembled.spans))
    no_gold = sum(1 for d in docs if not d.assembled.spans)
    type_docs = Counter()
    type_tpls = Counter()
    for tid, tpl in sorted(REGISTRY.items()):
        if tid not in per_tpl:
            continue
        for t in tpl.types:
            type_tpls[t] += 1
            type_docs[t] += per_tpl[tid]
    return {
        "documents": n,
        "templates": len(per_tpl),
        "documents_per_template": {t: {"count": per_tpl[t], "style": REGISTRY[t].style, "types": list(REGISTRY[t].types)}
                                   for t in sorted(per_tpl)},
        "max_template_share": max(per_tpl.values()) / n,
        "spans_per_category": {label: {"spans": span_counts[label], "documents": span_docs[label]} for label in GOLD_LABELS},
        "distractors_per_class": {c: {"regions": reg_counts[c], "documents": reg_docs[c]} for c in DISTRACTOR_CLASSES},
        "total_gold_spans": sum(span_counts.values()),
        "total_distractor_regions": sum(reg_counts.values()),
        "documents_without_gold_secret": no_secret,
        "documents_without_any_gold": no_gold,
        "generation_modes": dict(sorted(modes.items())),
        "length": {"min": min(lengths), "p10": _pct(lengths, .1), "p25": _pct(lengths, .25),
                   "median": _pct(lengths, .5), "p75": _pct(lengths, .75), "p90": _pct(lengths, .9),
                   "max": max(lengths), "mean": round(statistics.mean(lengths)),
                   "histogram": {f"{lo}-{hi - 1}": sum(1 for x in lengths if lo <= x < hi) for lo, hi in LEN_BUCKETS}},
        "gold_spans_per_document": {"median": _pct(gold_per_doc, .5), "mean": round(statistics.mean(gold_per_doc), 2),
                                    "max": max(gold_per_doc)},
        "distractor_regions_per_document": {"median": _pct(dist_per_doc, .5),
                                            "mean": round(statistics.mean(dist_per_doc), 2), "max": max(dist_per_doc)},
        "conversation_language": dict(sorted(conv_lang.items())),
        "documents_containing_text_language": dict(sorted(text_lang_docs.items())),
        "documents_containing_persona_locale": dict(sorted(locale_docs.items())),
        "documents_per_doc_type": dict(sorted(type_docs.items())),
        "templates_per_doc_type": dict(sorted(type_tpls.items())),
        "length_retries": {str(k): v for k, v in sorted(attempts.items())},
    }


def to_markdown(st: dict) -> str:
    out = []
    n = st["documents"]
    out.append(f"Documents: **{n}**, templates: **{st['templates']}**, largest template share: "
               f"**{st['max_template_share'] * 100:.2f}%** (cap 4%).\n")
    out.append(f"Documents without a gold secret: **{st['documents_without_gold_secret']}** "
               f"({st['documents_without_gold_secret'] / n * 100:.1f}%); without any gold value: "
               f"**{st['documents_without_any_gold']}** ({st['documents_without_any_gold'] / n * 100:.1f}%). "
               f"Generation modes: " + ", ".join(f"{k} {v}" for k, v in st["generation_modes"].items()) + ".\n")
    out.append("### Spans per gold category\n")
    out.append("| category | spans | documents |\n|---|---:|---:|")
    for k, v in st["spans_per_category"].items():
        out.append(f"| `{k}` | {v['spans']} | {v['documents']} |")
    out.append(f"| **total** | **{st['total_gold_spans']}** | |\n")
    g = st["gold_spans_per_document"]
    out.append(f"Gold spans per document: median {g['median']}, mean {g['mean']}, max {g['max']}.\n")
    out.append("### Distractors per class\n")
    out.append("| class | regions | documents |\n|---|---:|---:|")
    for k, v in st["distractors_per_class"].items():
        out.append(f"| `{k}` | {v['regions']} | {v['documents']} |")
    out.append(f"| **total** | **{st['total_distractor_regions']}** | |\n")
    dd = st["distractor_regions_per_document"]
    out.append(f"Distractor regions per document: median {dd['median']}, mean {dd['mean']}, max {dd['max']}.\n")
    ln = st["length"]
    out.append("### Length distribution (characters)\n")
    out.append("| min | p10 | p25 | median | p75 | p90 | max | mean |\n|---:|---:|---:|---:|---:|---:|---:|---:|")
    out.append(f"| {ln['min']} | {ln['p10']} | {ln['p25']} | {ln['median']} | {ln['p75']} | {ln['p90']} | {ln['max']} | {ln['mean']} |\n")
    out.append("| bucket | documents |\n|---|---:|")
    for k, v in ln["histogram"].items():
        out.append(f"| {k} | {v} |")
    out.append("")
    out.append("### Languages\n")
    out.append("Conversation language (user and agent turns): " +
               ", ".join(f"{k} {v}" for k, v in st["conversation_language"].items()) + ".\n")
    out.append("Documents containing free text in each language (user/agent turns, tickets, e-mails, reviews): " +
               ", ".join(f"{k} {v}" for k, v in st["documents_containing_text_language"].items()) + ".\n")
    out.append("Documents containing personal data from each persona locale: " +
               ", ".join(f"{k} {v}" for k, v in st["documents_containing_persona_locale"].items()) + ".\n")
    out.append("### Document types\n")
    out.append("| type | templates | documents |\n|---|---:|---:|")
    for k in st["documents_per_doc_type"]:
        out.append(f"| {k} | {st['templates_per_doc_type'][k]} | {st['documents_per_doc_type'][k]} |")
    out.append("")
    out.append("### Documents per template\n")
    out.append("| template | style | types | documents |\n|---|---|---|---:|")
    for k, v in st["documents_per_template"].items():
        out.append(f"| `{k}` | {v['style']} | {', '.join(v['types'])} | {v['count']} |")
    out.append("")
    out.append("Length retries (attempts needed to land in 300–20,000 chars): " +
               ", ".join(f"{k}: {v}" for k, v in st["length_retries"].items()) + ".")
    return "\n".join(out) + "\n"
