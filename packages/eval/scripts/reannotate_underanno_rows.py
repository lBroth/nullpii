#!/usr/bin/env python3
"""Re-annotate under-labelled rows in `nullpii-bench.jsonl`.

Strategy: independent regex pass — no ML / nullpii feedback loop.
Only enrich rows that are clearly under-annotated (text >300 chars
with ≤1 ground-truth span). Skip ambiguous categories (person,
address, generic dates) where regex would manufacture noise; only
add spans for syntactically-anchored PII (email, IPv4 / IPv6, MAC,
international phone, IBAN with mod-97, credit-card with Luhn,
canonical secret prefixes).

Usage:
  python packages/eval/scripts/reannotate_underanno_rows.py \
    --input  packages/eval/datasets/nullpii-bench.jsonl \
    --output packages/eval/datasets/nullpii-bench.jsonl.new \
    --report packages/eval/datasets/nullpii-bench-reannotation.report.txt

Then diff `.new` vs original, eyeball the report, and rename.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# ─── Regex pack (independent of nullpii core to avoid self-validation) ─

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"
)
# IPv6 - loose; full + ::-compressed.
IPV6_RE = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b")
MAC_RE = re.compile(r"(?<![:0-9A-Fa-f])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])")
PHONE_INTL_RE = re.compile(r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}")
AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA|A3T[A-Z0-9]|ABIA|ACCA)[A-Z2-7]{16}\b")
GH_PAT_RE = re.compile(r"\bghp_[A-Za-z0-9]{36,255}\b")
STRIPE_LIVE_RE = re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b")
GCP_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
SLACK_RE = re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")
# Generic 13-19 digit run for Luhn (matches credit cards w/ separators)
CC_RE = re.compile(r"\b(?:\d[ \-.]?){13,19}\b")
# IBAN: country code + 2 check + body
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{1,4}){2,8}\b")
# Broadcast / null / multicast MAC reserved set
RESERVED_MAC_PREFIXES = ("ffffffffffff", "000000000000")
RESERVED_MAC_HEAD = ("01005e", "3333", "0180c2")


def luhn_valid(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    alt = False
    for d in reversed(digits):
        x = int(d)
        if alt:
            x *= 2
            if x > 9:
                x -= 9
        total += x
        alt = not alt
    return total % 10 == 0


def iban97_valid(s: str) -> bool:
    compact = re.sub(r"\s+", "", s).upper()
    if not 15 <= len(compact) <= 34:
        return False
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", compact):
        return False
    rotated = compact[4:] + compact[:4]
    buf = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rotated)
    rem = 0
    for i in range(0, len(buf), 7):
        rem = int(str(rem) + buf[i : i + 7]) % 97
    return rem == 1


def mac_non_reserved(s: str) -> bool:
    hex_ = re.sub(r"[-:]", "", s).lower()
    if len(hex_) != 12:
        return False
    if hex_ in RESERVED_MAC_PREFIXES:
        return False
    return not any(hex_.startswith(p) for p in RESERVED_MAC_HEAD)


def detect_spans(text: str) -> list[tuple[int, int, str]]:
    """Conservative regex-only PII detection. Only emit spans for
    structurally-anchored / validator-passing matches."""
    spans: list[tuple[int, int, str]] = []
    for m in EMAIL_RE.finditer(text):
        spans.append((m.start(), m.end(), "private_email"))
    for m in IPV6_RE.finditer(text):
        spans.append((m.start(), m.end(), "private_ip"))
    for m in IPV4_RE.finditer(text):
        spans.append((m.start(), m.end(), "private_ip"))
    for m in MAC_RE.finditer(text):
        if mac_non_reserved(m.group()):
            spans.append((m.start(), m.end(), "private_mac"))
    for m in PHONE_INTL_RE.finditer(text):
        spans.append((m.start(), m.end(), "private_phone"))
    for m in AWS_KEY_RE.finditer(text):
        spans.append((m.start(), m.end(), "secret"))
    for m in GH_PAT_RE.finditer(text):
        spans.append((m.start(), m.end(), "secret"))
    for m in STRIPE_LIVE_RE.finditer(text):
        spans.append((m.start(), m.end(), "secret"))
    for m in GCP_KEY_RE.finditer(text):
        spans.append((m.start(), m.end(), "secret"))
    for m in SLACK_RE.finditer(text):
        spans.append((m.start(), m.end(), "secret"))
    for m in IBAN_RE.finditer(text):
        if iban97_valid(m.group()):
            spans.append((m.start(), m.end(), "account_number"))
    for m in CC_RE.finditer(text):
        if luhn_valid(m.group()):
            spans.append((m.start(), m.end(), "account_number"))
    # Dedupe overlapping spans, prefer earliest start / longest
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out: list[tuple[int, int, str]] = []
    for s in spans:
        if out and s[0] < out[-1][1]:
            continue
        out.append(s)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--min-text-len", type=int, default=300)
    parser.add_argument("--max-spans-existing", type=int, default=1)
    args = parser.parse_args()

    rows = [json.loads(l) for l in args.input.open()]
    report_lines: list[str] = []
    enriched_count = 0
    new_span_count = 0

    out_rows = []
    for idx, row in enumerate(rows):
        text = row["text"]
        existing_spans = row.get("spans", [])
        if (
            len(text) > args.min_text_len
            and len(existing_spans) <= args.max_spans_existing
        ):
            new_spans = detect_spans(text)
            # Convert existing spans to tuples for set ops
            existing_tup = []
            for s in existing_spans:
                if isinstance(s, dict):
                    existing_tup.append((s["start"], s["end"], s["label"]))
                else:
                    existing_tup.append(tuple(s))
            existing_set = set(existing_tup)
            added = [s for s in new_spans if s not in existing_set]
            if added:
                merged = sorted(set(existing_tup) | set(new_spans), key=lambda s: s[0])
                # Drop overlaps preferring earliest
                final: list[tuple[int, int, str]] = []
                for s in merged:
                    if final and s[0] < final[-1][1]:
                        continue
                    final.append(s)
                row = {
                    "text": text,
                    "spans": [
                        {"label": lbl, "start": st, "end": en}
                        for st, en, lbl in final
                    ],
                }
                enriched_count += 1
                new_span_count += len(added)
                report_lines.append(
                    f"idx={idx} text[:100]={text[:100]!r}\n"
                    f"  existing_spans: {existing_tup}\n"
                    f"  added:          {added}\n"
                    f"  final:          {final}\n"
                )
        out_rows.append(row)

    with args.output.open("w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with args.report.open("w") as f:
        f.write(f"rows enriched: {enriched_count}\n")
        f.write(f"new spans added: {new_span_count}\n")
        f.write(f"total rows: {len(rows)}\n\n")
        f.write("\n".join(report_lines))

    print(f"enriched {enriched_count} rows with {new_span_count} new spans")
    print(f"output: {args.output}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
