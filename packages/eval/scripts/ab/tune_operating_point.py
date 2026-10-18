# SPDX-License-Identifier: Apache-2.0
"""Tune one competitor's operating point on the tuning set (PROTOCOL rule
change 9, item 3: every tool that emits a confidence gets the tuning
nullpii got).

1. Grid: one real `bench_full.py` run per candidate config (`--grid`), plus
   the tool's default (`{}`). Each is scored by macro char-F2 on the tuning
   set. The grid is the tool's own recall knob: GLiNER and Presidio run at a
   low score floor, a token classifier lowers its `O` logit (`o_bias`), opf
   moves its Viterbi transition biases.
2. Cut: if the best grid run carries scores and `--cut-base` is given,
   `threshold_sim.py` screens a global, then a per-label, score threshold on
   that run.
3. Confirm: a real run with the best grid config plus the screened cut.

The operating point is the confirmed config if it beats the default on
macro char-F2, else the default. Everything lands under `--work/<tool>/`;
runs resume from their checkpoints. Only the tuning set is read.

  python tune_operating_point.py --tool nemotron-pii-raw --grid '[{"threshold": 0.05}]' \\
      --cut-base 0.3 --datasets isotonic-en-heldout,... --work results/ab-loop/r9-tuning
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

AB = Path(__file__).resolve().parent
SCRIPTS = AB.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "src"))
sys.path.insert(0, str(AB))

from char_metrics import dataset_arrays, scores  # noqa: E402

TUNING_SETS = (
    "isotonic-en-heldout,isotonic-de-heldout,isotonic-fr-heldout,isotonic-it-heldout,"
    "ai4privacy-300k-heldout,claude-code-traces-tuning"
)


def slug(config: dict) -> str:
    """A stable directory name for one config."""
    if not config:
        return "default"
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]


def run(tool: str, config: dict, out: Path, args: argparse.Namespace) -> float:
    """One real bench run of `tool` under `config` on the tuning set; returns
    its macro char-F2."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    argv = [sys.executable, str(SCRIPTS / "bench_full.py"), "--tools", tool, "--backend", args.backend,
            "--datasets", args.datasets, "--out-dir", str(out)]
    if config:
        cfg = out / "tool-config.json"
        cfg.write_text(json.dumps({tool: config}, sort_keys=True) + "\n", encoding="utf-8")
        argv += ["--tool-config", str(cfg)]
    with (out / "bench.log").open("a", encoding="utf-8") as log:
        subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return macro_f2(out, tool, args.datasets.split(","))


def macro_f2(results: Path, tool: str, datasets: list[str]) -> float:
    per_ds = []
    for ds in datasets:
        _, per_tool, _ = dataset_arrays(results, ds, [tool])
        per_ds.append(scores(*per_tool[tool])["f2"])
    return float(np.mean(per_ds))


def has_scores(results: Path, tool: str, dataset: str) -> bool:
    with (results / "checkpoints" / f"{tool}-{dataset}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            spans = json.loads(line)["spans"]
            if spans:
                return len(spans[0]) == 4
    return False


def screen_cut(results: Path, tool: str, args: argparse.Namespace) -> dict:
    sim_out = results / "threshold-sim.json"
    subprocess.run(
        [sys.executable, str(AB / "threshold_sim.py"), "--checkpoints", str(results / "checkpoints"),
         "--tool", tool, "--datasets", args.datasets, "--base", str(args.cut_base), "--global-sweep",
         "--out", str(sim_out)],
        check=True, stdin=subprocess.DEVNULL,
    )
    return json.loads(sim_out.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--grid", required=True, help="JSON list of builder-override configs to try")
    ap.add_argument("--cut-base", type=float, help="the tool's default score threshold; enables the per-label cut")
    ap.add_argument("--datasets", default=TUNING_SETS)
    ap.add_argument("--backend", default="cuda")
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()

    root = args.work / args.tool
    candidates = [{}] + [c for c in json.loads(args.grid) if c]
    grid = {}
    for config in candidates:
        f2 = run(args.tool, config, root / slug(config), args)
        grid[slug(config)] = {"config": config, "macro_f2": f2}
        print(f"[{args.tool}] {slug(config)} {json.dumps(config, sort_keys=True)}: macro char-F2 {f2:.4f}", flush=True)
    default_f2 = grid["default"]["macro_f2"]
    best_slug = max((s for s in grid if s != "default"), key=lambda s: grid[s]["macro_f2"], default="default")
    best = grid[best_slug]["config"]
    summary: dict = {"tool": args.tool, "datasets": args.datasets, "default_macro_f2": default_f2, "grid": grid}

    first = args.datasets.split(",")[0]
    if args.cut_base is not None and has_scores(root / best_slug, args.tool, first):
        sim = screen_cut(root / best_slug, args.tool, args)
        summary["screen"] = {"from": best_slug, "start": sim["base"]["macro_f2"], "best": sim["best"]["macro_f2"]}
        best = {**best, "label_cut": sim["label_cut"]}

    if best != grid[best_slug]["config"]:
        confirmed_f2 = run(args.tool, best, root / f"confirm-{slug(best)}", args)
    else:
        confirmed_f2 = grid[best_slug]["macro_f2"]
    summary["confirmed"] = {"config": best, "macro_f2": confirmed_f2}
    chosen = best if confirmed_f2 > default_f2 else {}
    summary["operating_point"] = {"config": chosen, "macro_f2": max(confirmed_f2, default_f2)}
    (root / "operating-point.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{args.tool}] default {default_f2:.4f}, confirmed {confirmed_f2:.4f}; operating point "
          f"{'tuned' if chosen else 'default'}", flush=True)


if __name__ == "__main__":
    main()
