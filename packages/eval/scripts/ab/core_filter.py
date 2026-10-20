# SPDX-License-Identifier: Apache-2.0
"""nullpii's default-config spans filtered to the core label space (PROTOCOL
rule change 10, item 6).

Reads `score_capture.mjs` checkpoints (`[start, end, label, score]` rows) of
`--tool` and writes `<tool>@core-<dataset>.jsonl` beside them, without the
spans of the extended categories that the core regime disables. The default
config still prompts the model with those categories, so this is a
post-filter of its output, reported next to the raw row and to the core
regime's own run.

  python core_filter.py --checkpoints ~/nullpii-bench/r3/checkpoints \\
      --tool nullpii-H3b-A11-cuda-default --datasets r3-redact,r3-piilo
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# GLINER_EXTENDED_CATEGORIES in src/types/labels.ts.
EXTENDED = frozenset(
    {"private_organization", "private_occupation", "private_demographic", "private_sensitive", "private_title"}
)
SUFFIX = "@core"
LABEL_FIELD = 2


def filter_rows(lines: list[str]) -> tuple[list[str], int, int]:
    """Rows without extended-category spans, plus kept and dropped counts."""
    out, kept, dropped = [], 0, 0
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        spans = []
        for span in row["spans"]:
            if len(span) <= LABEL_FIELD:
                raise ValueError(f"idx {row['idx']}: span without a label; not a score_capture checkpoint")
            if span[LABEL_FIELD] in EXTENDED:
                dropped += 1
            else:
                spans.append(span)
        kept += len(spans)
        out.append(json.dumps({"idx": row["idx"], "spans": spans}))
    return out, kept, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoints", type=Path, required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--datasets", required=True)
    args = ap.parse_args()

    for ds in args.datasets.split(","):
        src = args.checkpoints / f"{args.tool}-{ds}.jsonl"
        rows, kept, dropped = filter_rows(src.read_text(encoding="utf-8").splitlines())
        dst = args.checkpoints / f"{args.tool}{SUFFIX}-{ds}.jsonl"
        dst.write_text("".join(f"{r}\n" for r in rows), encoding="utf-8")
        print(f"{ds}: {len(rows)} docs, {kept} spans kept, {dropped} extended-category spans dropped", flush=True)


if __name__ == "__main__":
    main()
