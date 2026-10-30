# SPDX-License-Identifier: Apache-2.0
"""Score a tool on PIIMB (piimb/pii-masking-benchmark, `sentences` subset).

PIIMB ranks PII maskers by label-agnostic character-level F2, micro-averaged
within each task, then averaged over its six tasks. This module reproduces
`piimb.metrics.compute_masking_metrics` (v0.3.0) exactly, so a score here
sits on the published leaderboard (piimb/pii-masking-benchmark-results).

  python piimb_score.py export --data test_sentences.jsonl --out texts.jsonl
  python piimb_score.py score --data test_sentences.jsonl --pred spans.jsonl [--leaderboard dir] [--leave-out task]

`export` writes `score_capture.mjs` input (dataset = task, idx per task in
file order); `score` reads its `--out` spans. With `--leave-out`, the
report also gives the average and the leaderboard place without that task
(a task from the tool's own training family). The dataset is CC-BY-NC-4.0:
evaluation only, never redistributed or trained on.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

TASKS = ["ai4privacy-en", "ai4privacy-multi", "gretel", "mapa-eur-lex", "nemotron-pii", "privy"]


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(i for i in intervals if i[1] > i[0]):
        if out and a <= out[-1][1]:  # overlapping or consecutive, as PIIMB merges
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def length(intervals: list[tuple[int, int]]) -> int:
    return sum(b - a for a, b in intervals)


def intersection(x: list[tuple[int, int]], y: list[tuple[int, int]]) -> int:
    i = j = total = 0
    while i < len(x) and j < len(y):
        lo, hi = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        total += max(0, hi - lo)
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return total


def f_beta(p: float, r: float, beta: float) -> float:
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r) if p + r > 0 else 0.0


def read_rows(path: Path) -> dict[str, list[dict]]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by_task[row["task_name"]].append(row)
    return by_task


def export(data: Path, out: Path) -> None:
    with out.open("w", encoding="utf-8") as f:
        for task, rows in read_rows(data).items():
            for i, row in enumerate(rows):
                f.write(json.dumps({"dataset": task, "idx": i, "text": row["text"]}, ensure_ascii=False) + "\n")


def score(data: Path, pred: Path) -> dict[str, dict[str, float]]:
    preds: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for line in pred.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        preds[(row["dataset"], row["idx"])] = [(int(s[0]), int(s[1])) for s in row["spans"]]
    out = {}
    for task, rows in read_rows(data).items():
        tp = pp = tt = text = 0
        for i, row in enumerate(rows):
            if (task, i) not in preds:
                raise ValueError(f"{task}:{i} has no prediction; the run is incomplete")
            gold = merge([(e["start"], e["end"]) for e in row["entities"]])
            got = merge(preds[(task, i)])
            tt += length(gold)
            pp += length(got)
            tp += intersection(got, gold)
            text += len(row["text"])
        p = tp / pp if pp else 0.0
        r = tp / tt if tt else 0.0
        out[task] = {"precision": p, "recall": r, "f2": f_beta(p, r, 2), "fpr": (pp - tp) / (text - tt)}
    return out


def leaderboard(directory: Path) -> list[tuple[float, str, dict[str, float]]]:
    """Every model of the leaderboard snapshot in `directory`. A model
    without a score for each task is an error, never left out: leaving it
    out would move every place."""
    rows = []
    for model in sorted(p for p in directory.iterdir() if p.is_dir()):
        try:
            f2 = {t: json.loads((model / f"{t}.json").read_text())["scores"]["test"][0]["f2"] for t in TASKS}
        except (OSError, KeyError, IndexError, ValueError) as e:
            raise SystemExit(f"leaderboard model {model.name} has no F2 for every task: {e}") from e
        rows.append((sum(f2.values()) / len(TASKS), model.name, f2))
    return sorted(rows, reverse=True)


def place(avg: float, others: list[float]) -> dict[str, int]:
    """The place of `avg` among `others` (1 is first), and how many are
    ranked, itself included."""
    return {"rank": 1 + sum(1 for a in others if a > avg), "of": len(others) + 1}


def without(ours: dict[str, dict[str, float]], board: list, task: str) -> dict:
    """The average F2 over every task but `task`, and its place among the
    leaderboard's rows averaged the same way."""
    if task not in TASKS:
        raise SystemExit(f"--leave-out {task}: not a PIIMB task ({', '.join(TASKS)})")
    rest = [t for t in TASKS if t != task]
    avg = sum(ours[t]["f2"] for t in rest) / len(rest)
    others = [sum(f2[t] for t in rest) / len(rest) for _, _, f2 in board]
    return {"task": task, "avg_f2": avg, "leaderboard": place(avg, others)}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--data", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--data", type=Path, required=True)
    s.add_argument("--pred", type=Path, required=True)
    s.add_argument("--name", default="nullpii")
    s.add_argument("--leaderboard", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("--leave-out", help="also report the average and place without this task (needs --leaderboard)")
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.data, args.out)
        return
    if args.leave_out and not args.leaderboard:
        raise SystemExit("--leave-out needs --leaderboard")
    ours = score(args.data, args.pred)
    avg = sum(ours[t]["f2"] for t in TASKS) / len(TASKS)
    board = leaderboard(args.leaderboard) if args.leaderboard else []
    if args.out:
        report = {"name": args.name, "avg_f2": avg, "tasks": ours}
        if args.leaderboard:
            # The tool's place among the leaderboard's rows by average F2.
            report["leaderboard"] = place(avg, [a for a, _, _ in board])
            # And on each task, by that task's F2.
            report["task_ranks"] = {t: place(ours[t]["f2"], [f2[t] for _, _, f2 in board]) for t in TASKS}
        if args.leave_out:
            report["without"] = without(ours, board, args.leave_out)
        args.out.write_text(json.dumps(report, indent=1) + "\n")
    board.append((avg, f">>> {args.name}", {t: ours[t]["f2"] for t in TASKS}))
    board.sort(reverse=True)
    print(f"{'model':58s} avgF2  " + "  ".join(f"{t[:10]:10s}" for t in TASKS))
    for rank, (a, name, f2) in enumerate(board, 1):
        print(f"{rank:2d} {name[:55]:55s} {a:.3f}  " + "  ".join(f"{f2[t]:.3f}     " for t in TASKS))
    print("\n" + "\n".join(f"{t}: P {m['precision']:.3f} R {m['recall']:.3f} F2 {m['f2']:.3f}" for t, m in ours.items()))


if __name__ == "__main__":
    main()
