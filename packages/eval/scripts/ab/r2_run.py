# SPDX-License-Identifier: Apache-2.0
"""Run competitors on the gated report set R2 (PROTOCOL rule change 9).

Each tool runs twice: at the operating point `tune_operating_point.py`
froze on the tuning set, and at its default. Both land in one checkpoint
directory, the tuned run as `<tool>` and the default as `<tool>@default`,
so `char_metrics.py` scores them in the single R2 look the rule allows.

Prints completion only. `bench_full.py` writes per-dataset scores into its
own log under `--work`; reading that log before every candidate is frozen
would be a second look at R2, so this script never echoes it.

  python r2_run.py --tools nemotron-pii-raw,openmed-small --tuning results/ab-loop/r9-tuning \\
      --work results/ab-loop/r2-report
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
R2_SETS = "piimb-mapa-eur-lex,piimb-privy,piimb-gretel,traces-v2"
DEFAULT_SUFFIX = "@default"


def bench(tool: str, config: dict, out: Path, backend: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(SCRIPTS / "bench_full.py"), "--tools", tool, "--backend", backend,
            "--datasets", R2_SETS, "--out-dir", str(out)]
    if config:
        cfg = out / "tool-config.json"
        cfg.write_text(json.dumps({tool: config}, sort_keys=True) + "\n", encoding="utf-8")
        argv += ["--tool-config", str(cfg)]
    with (out / "bench.log").open("a", encoding="utf-8") as log:
        subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def link(src: Path, combined: Path, tool: str, name: str) -> None:
    """Expose `src`'s checkpoints of `tool` under `name` in `combined`."""
    combined.mkdir(parents=True, exist_ok=True)
    for ds in R2_SETS.split(","):
        target = combined / f"{name}-{ds}.jsonl"
        target.unlink(missing_ok=True)
        target.symlink_to((src / "checkpoints" / f"{tool}-{ds}.jsonl").resolve())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", required=True)
    ap.add_argument("--tuning", type=Path, required=True, help="tune_operating_point.py --work dir")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--backend", default="cuda")
    args = ap.parse_args()

    combined = args.work / "checkpoints"
    for tool in args.tools.split(","):
        op = json.loads((args.tuning / tool / "operating-point.json").read_text(encoding="utf-8"))
        config = op["operating_point"]["config"]
        bench(tool, {}, args.work / tool / "default", args.backend)
        link(args.work / tool / "default", combined, tool, f"{tool}{DEFAULT_SUFFIX}")
        if config:
            bench(tool, config, args.work / tool / "tuned", args.backend)
            link(args.work / tool / "tuned", combined, tool, tool)
        else:
            link(args.work / tool / "default", combined, tool, tool)
        print(f"[r2] {tool}: done ({'tuned' if config else 'default'} operating point)", flush=True)


if __name__ == "__main__":
    main()
