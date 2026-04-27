#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Curiosity benchmark — StreamGuard regex/DFA engine on every dataset.

StreamGuard is a Rust+WASM guardrail engine (Suricata-inspired) that uses
DFA + regex pattern matching, no ML. Built fresh from
github.com/d-barletta/StreamGuard via PyO3 bindings.

Coverage caveat: StreamGuard ships email/url/ipv4/credit_card pattern
rules. That's 3 of our 8 categories:
  email          → private_email
  url            → private_url
  credit_card    → account_number
The other 5 (private_person, private_phone, private_address,
private_date, secret) have no built-in StreamGuard rule and will score
0 — expected by design (regex won't catch contextual PII).

Output goes to `packages/eval/results/` which is gitignored.
"""
from __future__ import annotations

import argparse
import difflib
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1

import streamguard as sg

REWRITES = [
    ("private_email", "[E_REDACT]", lambda r: sg.PatternRule.email_rewrite(r)),
    ("private_url", "[U_REDACT]", lambda r: sg.PatternRule.url_rewrite(r)),
    ("account_number", "[C_REDACT]", lambda r: sg.PatternRule.credit_card_rewrite(r)),
]


def _diff_spans(orig: str, rewritten: str, label: str, marker: str) -> list[Span]:
    """Find replaced regions in `orig` by aligning against `rewritten`.

    For each `replace` op in the SequenceMatcher diff, emit a Span at
    the original-side coordinates with the given label.
    """
    spans: list[Span] = []
    sm = difflib.SequenceMatcher(a=orig, b=rewritten, autojunk=False)
    for tag, i1, i2, _, _ in sm.get_opcodes():
        if tag == "replace" and i2 > i1:
            spans.append(Span(label, i1, i2))
    return spans


def streamguard_predict(text: str) -> list[Span]:
    spans: list[Span] = []
    for label, marker, factory in REWRITES:
        engine = sg.GuardEngine()
        engine.add_pattern_rule(factory(marker))
        decision = engine.feed(text)
        if decision.is_rewrite():
            rewritten = decision.rewritten_text() or ""
            if rewritten != text:
                spans.extend(_diff_spans(text, rewritten, label, marker))
    return spans


def f1_streamguard(samples: list[Sample]) -> tuple[float, float]:
    truths = [list(s.spans) for s in samples]
    t0 = time.perf_counter()
    preds = [streamguard_predict(s.text) for s in samples]
    elapsed = time.perf_counter() - t0
    return macro_f1(evaluate(preds, truths)), elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isotonic", type=int, default=5000)
    parser.add_argument("--wikiann", type=int, default=1000)
    parser.add_argument("--presidio-syn", type=int, default=5000)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "results" / "streamguard.json"),
    )
    parser.add_argument(
        "--log",
        default=str(
            Path(__file__).resolve().parent.parent
            / "results"
            / f"streamguard-{datetime.now():%Y%m%d-%H%M%S}.log"
        ),
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("streamguard")
    log.info("starting; out=%s log=%s", args.out, log_path)

    runs: list[tuple[str, list]] = []
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"bundled-{loc}", list(load(loc).samples)))
    runs.append(("long-prompts-en", list(load("long-prompts-en").samples)))
    iso_n = None if args.isotonic == 0 else args.isotonic
    for loc in ("en", "it", "de", "fr"):
        runs.append((f"isotonic-{loc}", list(public_datasets._load_isotonic(iso_n, lang=loc).samples)))
    if args.presidio_syn > 0:
        runs.append((
            "presidio-synthetic",
            list(public_datasets._load_presidio_synthetic(args.presidio_syn).samples),
        ))
    wiki_n = None if args.wikiann == 0 else args.wikiann
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"wikiann-{loc}", list(public_datasets._load_wikiann(wiki_n, lang=loc).samples)))

    n_total = sum(len(s) for _, s in runs)
    log.info("datasets: %d, total samples: %d", len(runs), n_total)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "_meta": {
            "engine": "StreamGuard 0.2.0 (PyO3 release)",
            "started": datetime.now().isoformat(),
            "n_total": n_total,
        },
        "runs": {},
    }
    for idx, (name, samples) in enumerate(runs, start=1):
        log.info("[%d/%d] %s n=%d — running…", idx, len(runs), name, len(samples))
        f1, elapsed = f1_streamguard(samples)
        per_sample_ms = elapsed / max(1, len(samples)) * 1000
        out["runs"][name] = {
            "n": len(samples),
            "f1": f1,
            "elapsed_s": elapsed,
            "ms_per_sample": per_sample_ms,
        }
        # Persist partial after each dataset.
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        log.info("  F1=%.4f  %.2f ms/sample", f1, per_sample_ms)

    out["_meta"]["finished"] = datetime.now().isoformat()
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("complete — results → %s, log → %s", out_path, log_path)


if __name__ == "__main__":
    main()
