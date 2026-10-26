# SPDX-License-Identifier: Apache-2.0
"""Dump every carrier-pass hit of the selected carrier excerpts for manual review.

    python gen/review_dump.py   ->  cache/review/carrier_hits.tsv

Each row: document id, value, proposed class, kind, rule that fired, applied?, left/right context.
Reviewed decisions that differ from the rules go into gen/carrier_review.tsv (value<TAB>CLASS:kind or skip).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402
from annotate import carrier_pass  # noqa: E402
from common import CACHE  # noqa: E402
from doc import Doc  # noqa: E402


def main() -> None:
    plans = build.make_plan()
    build.assign_carriers(plans)
    out = CACHE / "review"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    with (out / "carrier_hits.tsv").open("w", encoding="utf-8") as fh:
        fh.write("doc\tvalue\tclass\tkind\trule\tapplied\tleft\tright\n")
        for p in plans:
            if p.origin != "carrier":
                continue
            log: list = []
            carrier_pass(Doc(p.excerpt), log)
            for v, cls, kind, why, ok, left, right in log:
                fh.write("\t".join([p.id, v.replace("\t", " ").replace("\n", "⏎"), cls, kind, why, str(ok), left.replace("\t", " "), right.replace("\t", " ")]) + "\n")
                n += 1
    print(f"{n} hits written to {out / 'carrier_hits.tsv'}")


if __name__ == "__main__":
    main()
