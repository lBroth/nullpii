# SPDX-License-Identifier: Apache-2.0
"""Run competitors on a gated report set: R2 (PROTOCOL rule change 9) by
default, R3 (rule change 10) with `--datasets`.

Each tool runs twice: at the operating point `tune_operating_point.py`
froze on the tuning set, and at its default. Both land in one checkpoint
directory, the tuned run as `<tool>` and the default as `<tool>@default`,
so `char_metrics.py` scores them in the single R2 look the rule allows.

Prints completion only. `bench_full.py` writes per-dataset scores into its
own log under `--work`; reading that log before every candidate is frozen
would be a second look at R2, so this script never echoes it.

  python r2_run.py --tools nemotron-pii-raw,openmed-small --tuning results/ab-loop/r9-tuning \\
      --work results/ab-loop/r2-report
  python r2_run.py --tools deberta --tuning results/ab-loop/r10-tuning --work results/ab-loop/r3-report \\
      --datasets r3-redact,r3-tonic-human,r3-eu-clinical,r3-redactionbench,r3-mama-deid-val
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


def bench(tool: str, config: dict, out: Path, backend: str, datasets: str, keep_unmapped: bool = False) -> None:
    cfg = out / "tool-config.json"
    wanted = json.dumps({tool: config}, sort_keys=True) + "\n" if config else None
    found = cfg.read_text(encoding="utf-8") if cfg.exists() else None
    if (out / "checkpoints").exists() and found != wanted:
        # bench_full resumes from checkpoints, so a changed operating point would
        # silently keep the old one's spans.
        raise SystemExit(f"{out}: checkpoints come from another operating point; delete the directory to rerun")
    out.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(SCRIPTS / "bench_full.py"), "--tools", tool, "--backend", backend,
            "--datasets", datasets, "--out-dir", str(out)]
    if wanted:
        cfg.write_text(wanted, encoding="utf-8")
        argv += ["--tool-config", str(cfg)]
    if keep_unmapped:
        argv.append("--keep-unmapped-labels")
    with (out / "bench.log").open("a", encoding="utf-8") as log:
        subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def link(src: Path, combined: Path, tool: str, name: str, datasets: str) -> None:
    """Expose `src`'s checkpoints of `tool` under `name` in `combined`."""
    combined.mkdir(parents=True, exist_ok=True)
    for ds in datasets.split(","):
        target = combined / f"{name}-{ds}.jsonl"
        target.unlink(missing_ok=True)
        target.symlink_to((src / "checkpoints" / f"{tool}-{ds}.jsonl").resolve())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", required=True)
    ap.add_argument("--tuning", type=Path, required=True, help="tune_operating_point.py --work dir")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--backend", default="cuda")
    ap.add_argument("--datasets", default=R2_SETS)
    ap.add_argument("--keep-unmapped-labels", action="store_true", help="forwarded to bench_full.py (AB-1)")
    args = ap.parse_args()

    combined = args.work / "checkpoints"
    for tool in args.tools.split(","):
        op = json.loads((args.tuning / tool / "operating-point.json").read_text(encoding="utf-8"))
        config = op["operating_point"]["config"]
        bench(tool, {}, args.work / tool / "default", args.backend, args.datasets, args.keep_unmapped_labels)
        link(args.work / tool / "default", combined, tool, f"{tool}{DEFAULT_SUFFIX}", args.datasets)
        if config:
            bench(tool, config, args.work / tool / "tuned", args.backend, args.datasets, args.keep_unmapped_labels)
            link(args.work / tool / "tuned", combined, tool, tool, args.datasets)
        else:
            link(args.work / tool / "default", combined, tool, tool, args.datasets)
        print(f"[report] {tool}: done ({'tuned' if config else 'default'} operating point)", flush=True)


if __name__ == "__main__":
    main()
