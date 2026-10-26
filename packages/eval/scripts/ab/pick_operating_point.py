# SPDX-License-Identifier: Apache-2.0
"""Pick a competitor's operating point across tuning passes (rule change 9).

A grid-edge extension pass writes its own `operating-point.json` under a
separate work dir. The tool's operating point is the pass whose confirmed
macro char-F2 on the tuning set is highest. The pick overwrites the first
pass's file, which `r2_run.py --tuning` reads; that file is first kept
beside it as `operating-point.pass1.json`, so rerunning the pick is safe.

  python pick_operating_point.py --tool nemotron-pii-raw \\
      --passes results/ab-loop/r9-tuning results/ab-loop/r9-tuning-ext
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

OP_FILE = "operating-point.json"
PASS1_FILE = "operating-point.pass1.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--passes", type=Path, nargs="+", required=True,
                    help="tune_operating_point.py work dirs; the first is the one r2_run.py reads")
    args = ap.parse_args()

    first = args.passes[0] / args.tool
    if not (first / PASS1_FILE).exists():
        shutil.copyfile(first / OP_FILE, first / PASS1_FILE)
    candidates = {str(first / PASS1_FILE): json.loads((first / PASS1_FILE).read_text(encoding="utf-8"))}
    for work in args.passes[1:]:
        path = work / args.tool / OP_FILE
        candidates[str(path)] = json.loads(path.read_text(encoding="utf-8"))

    source = max(candidates, key=lambda p: candidates[p]["operating_point"]["macro_f2"])
    for path, op in candidates.items():
        print(f"[{args.tool}] {path}: {op['operating_point']['macro_f2']:.4f}{'  <- picked' if path == source else ''}")
    (first / OP_FILE).write_text(
        json.dumps({**candidates[source], "picked_from": source}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
