#!/usr/bin/env python3
"""Generate per-class precision/recall/F1 markdown tables from a bench
run's `confusion.json`.

Reads:
  --in-dir/{matrix.json,confusion.json}  produced by `bench_full.py
                                          --confusion` (per-cell
                                          per-label TP/FP/FN counts)

Writes:
  --out (default: --in-dir/per_class.md)  3-section markdown report:
     1. Per-tool aggregate (TP/FP/FN summed across all datasets)
        with precision/recall/F1 per label.
     2. Per-tool × dataset detail (compact table per tool, rows =
        labels, cols = datasets).
     3. Worst-recall ranking: (tool, label, dataset) tuples with
        recall < `--low-recall-threshold` (default 0.50). Surfaces
        weakest classes per profile for the model-card "known
        failure modes" section + DPIA buyer-facing per-class
        residual-risk table (GDPR Art. 35 + EU AI Act Art. 53).

Example:
    python packages/eval/scripts/confusion_report.py \\
      --in-dir packages/eval/results/bench-release-local
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp > 0 else 0.0
    r = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return p, r, f1


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    sep = ["---:" if h.startswith("[N]") else "---" for h in headers]
    headers = [h.removeprefix("[N]") for h in headers]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _aggregate_per_tool(confusion: dict) -> dict[str, dict[str, dict[str, int]]]:
    """{tool: {label: {tp, fp, fn}}} aggregated across datasets."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for ds, tools in confusion.items():
        if not isinstance(tools, dict):
            continue
        for tool, labels in tools.items():
            if not isinstance(labels, dict):
                continue
            tool_agg = out.setdefault(tool, {})
            for label, counts in labels.items():
                if not isinstance(counts, dict):
                    continue
                lbl = tool_agg.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})
                lbl["tp"] += int(counts.get("tp", 0))
                lbl["fp"] += int(counts.get("fp", 0))
                lbl["fn"] += int(counts.get("fn", 0))
    return out


def _section_aggregate(confusion: dict) -> str:
    agg = _aggregate_per_tool(confusion)
    if not agg:
        return "## Per-tool aggregate (no data)\n"
    parts = ["## Per-tool aggregate", ""]
    parts.append(
        "Counts summed across all datasets in the bench. P / R / F1 are micro-averaged.",
    )
    parts.append("")
    for tool in sorted(agg):
        parts.append(f"### `{tool}`")
        parts.append("")
        rows: list[list[str]] = []
        # Add a totals row at the bottom.
        total_tp = total_fp = total_fn = 0
        for label in sorted(agg[tool]):
            counts = agg[tool][label]
            tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
            p, r, f1 = _prf(tp, fp, fn)
            rows.append([
                f"`{label}`",
                f"{p:.3f}", f"{r:.3f}", f"{f1:.3f}",
                f"{tp}", f"{fp}", f"{fn}",
            ])
            total_tp += tp
            total_fp += fp
            total_fn += fn
        p_t, r_t, f1_t = _prf(total_tp, total_fp, total_fn)
        rows.append([
            "**total (micro)**",
            f"**{p_t:.3f}**", f"**{r_t:.3f}**", f"**{f1_t:.3f}**",
            f"**{total_tp}**", f"**{total_fp}**", f"**{total_fn}**",
        ])
        parts.append(_md_table(
            ["label", "[N]P", "[N]R", "[N]F1", "[N]TP", "[N]FP", "[N]FN"],
            rows,
        ))
        parts.append("")
    return "\n".join(parts)


def _section_detail(confusion: dict) -> str:
    """Per-tool table with rows = labels, cols = datasets, cells = F1."""
    # Discover label / dataset / tool universe.
    tools: set[str] = set()
    datasets: set[str] = set()
    labels: set[str] = set()
    for ds, tool_map in confusion.items():
        if not isinstance(tool_map, dict):
            continue
        datasets.add(ds)
        for tool, label_map in tool_map.items():
            if not isinstance(label_map, dict):
                continue
            tools.add(tool)
            labels.update(label_map.keys())
    if not tools:
        return "## Per-tool × dataset F1 detail (no data)\n"
    parts = ["## Per-tool × dataset F1 detail", ""]
    parts.append(
        "Per-label F1 score per dataset. Empty cells = label not present "
        "in that dataset's gold annotations or no predictions emitted.",
    )
    parts.append("")
    for tool in sorted(tools):
        parts.append(f"### `{tool}`")
        parts.append("")
        ds_sorted = sorted(datasets)
        label_sorted = sorted(labels)
        headers = ["label"] + [f"[N]{d}" for d in ds_sorted]
        rows: list[list[str]] = []
        for label in label_sorted:
            row = [f"`{label}`"]
            for ds in ds_sorted:
                cell = (
                    confusion.get(ds, {})
                    .get(tool, {})
                    .get(label)
                )
                if not isinstance(cell, dict):
                    row.append("")
                    continue
                tp, fp, fn = cell.get("tp", 0), cell.get("fp", 0), cell.get("fn", 0)
                if tp + fp + fn == 0:
                    row.append("")
                    continue
                _, _, f1 = _prf(tp, fp, fn)
                row.append(f"{f1:.3f}")
            rows.append(row)
        parts.append(_md_table(headers, rows))
        parts.append("")
    return "\n".join(parts)


def _section_worst(confusion: dict, threshold: float) -> str:
    """Rows: (tool, label, dataset) with recall < threshold and TP+FN > 5."""
    rows: list[tuple[float, str, str, str, int, int, int]] = []
    for ds, tool_map in confusion.items():
        if not isinstance(tool_map, dict):
            continue
        for tool, label_map in tool_map.items():
            if not isinstance(label_map, dict):
                continue
            for label, counts in label_map.items():
                if not isinstance(counts, dict):
                    continue
                tp = int(counts.get("tp", 0))
                fp = int(counts.get("fp", 0))
                fn = int(counts.get("fn", 0))
                if tp + fn < 5:
                    continue
                _, r, _ = _prf(tp, fp, fn)
                if r < threshold:
                    rows.append((r, tool, label, ds, tp, fp, fn))
    rows.sort(key=lambda x: x[0])
    parts = [
        f"## Worst-recall ranking (recall < {threshold:.2f}, gold support ≥ 5)",
        "",
        "Cells where the model misses ≥ half the gold spans for that "
        "(tool, label, dataset) — primary input for the model-card "
        "\"known failure modes\" section + DPIA per-class residual-risk "
        "table.",
        "",
    ]
    if not rows:
        parts.append(f"_No cells below recall threshold {threshold:.2f}._")
        return "\n".join(parts)
    md_rows = [
        [
            f"**{r:.3f}**",
            f"`{tool}`",
            f"`{label}`",
            f"`{ds}`",
            f"{tp}", f"{fp}", f"{fn}",
        ]
        for r, tool, label, ds, tp, fp, fn in rows
    ]
    parts.append(_md_table(
        ["[N]Recall", "Tool", "Label", "Dataset", "[N]TP", "[N]FP", "[N]FN"],
        md_rows,
    ))
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, required=True,
                    help="bench output dir containing confusion.json")
    ap.add_argument("--out", type=Path, default=None,
                    help="output markdown path (default: --in-dir/per_class.md)")
    ap.add_argument("--low-recall-threshold", type=float, default=0.50,
                    help="cells with recall < this surface in the worst-recall ranking")
    args = ap.parse_args()

    conf_path = args.in_dir / "confusion.json"
    if not conf_path.exists():
        raise SystemExit(
            f"missing {conf_path} — re-run bench_full.py with --confusion",
        )
    confusion = json.loads(conf_path.read_text())

    out_path = args.out or (args.in_dir / "per_class.md")
    parts = [
        f"# Per-class confusion report — `{args.in_dir.name}`",
        "",
        f"Generated from `{conf_path}`. IoU ≥ 0.5, micro-averaged P/R/F1.",
        "",
        _section_aggregate(confusion),
        _section_detail(confusion),
        _section_worst(confusion, args.low_recall_threshold),
        "",
    ]
    out_path.write_text("\n".join(parts))
    print(f"[per_class] wrote {out_path}")


if __name__ == "__main__":
    main()
