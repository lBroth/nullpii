#!/usr/bin/env python3
"""Per-tool failure analysis on bench outputs.

Reads `{out_dir}/checkpoints/{tool}-{dataset}.jsonl` (per-sample predicted
spans) + reloads the dataset's gold spans, computes match (IoU >= 0.5,
same label), and reports:

- **FN by label** — gold spans the tool missed entirely. Shows top-N
  surface forms (the actual text the model failed to detect).
- **FP by label** — predicted spans that matched no gold span. Shows
  top-N surface forms of false positives.

Use to identify regex patterns worth adding (consistently-missed
formats with distinctive prefix/structure). Skip patterns that look
context-dependent (full-words, generic alphanumeric) to avoid hacky
regex with high FP risk.

CLI:
  python failure_analysis.py \\
    --out-dir packages/eval/results/mac-overnight-20260430-v2 \\
    --tool gliner-onnx-pii-fp32+regex-big \\
    --dataset nullpii-bench \\
    --top 20

  # Or all tools across all datasets in the out-dir:
  python failure_analysis.py \\
    --out-dir packages/eval/results/mac-overnight-20260430-v2 \\
    --all-tools --all-datasets --top 10 \\
    > failure_report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))

from nullpii_eval import public_datasets  # noqa: E402
from nullpii_eval.datasets import Sample, Span  # noqa: E402


@dataclass(frozen=True, slots=True)
class _DatasetLoader:
    key: str
    loader: Callable[[int | None], list[Sample]]
    default_n: int | None


def _load_nullpii_bench(n: int | None) -> list[Sample]:
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["subset"] not in ("bundled", "long-prompts"):
                continue
            spans = tuple(
                Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"]
            )
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def _isotonic(loc: str, row_offset: int = 0) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(
        public_datasets._load_isotonic(n, lang=loc, row_offset=row_offset).samples,
    )


def _ai4privacy(offset: int = 0) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(public_datasets._load_ai4privacy(n, offset=offset).samples)


def _wikiann(lang: str) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(public_datasets._load_wikiann(n, lang=lang).samples)


_AI4_HELDOUT_OFFSET = 100_000
_ISOTONIC_HELDOUT_ROW_OFFSET = 200_000

DATASETS: dict[str, _DatasetLoader] = {
    d.key: d for d in [
        _DatasetLoader("nullpii-bench", _load_nullpii_bench, None),
        _DatasetLoader("ai4privacy-heldout", _ai4privacy(offset=_AI4_HELDOUT_OFFSET), 5_000),
        _DatasetLoader("ai4privacy-300k", _ai4privacy(), 5_000),
        _DatasetLoader("ai4privacy-400k", lambda n: list(public_datasets._load_ai4privacy_400k(n).samples), 5_000),
        _DatasetLoader("isotonic-en", _isotonic("en"), 5_000),
        _DatasetLoader("isotonic-de", _isotonic("de"), 5_000),
        _DatasetLoader("isotonic-fr", _isotonic("fr"), 5_000),
        _DatasetLoader("isotonic-it", _isotonic("it"), 5_000),
        _DatasetLoader("isotonic-en-heldout", _isotonic("en", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET), 5_000),
        _DatasetLoader("isotonic-de-heldout", _isotonic("de", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET), 5_000),
        _DatasetLoader("isotonic-fr-heldout", _isotonic("fr", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET), 5_000),
        _DatasetLoader("isotonic-it-heldout", _isotonic("it", row_offset=_ISOTONIC_HELDOUT_ROW_OFFSET), 5_000),
        _DatasetLoader("isotonic-en-traindist", _isotonic("en"), 5_000),
        _DatasetLoader("ai4privacy-traindist", _ai4privacy(), 5_000),
        _DatasetLoader("wikiann-es", _wikiann("es"), 5_000),
        _DatasetLoader("wikiann-zh", _wikiann("zh"), 5_000),
        _DatasetLoader("wikiann-ja", _wikiann("ja"), 5_000),
    ]
}


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def analyse(
    *,
    out_dir: Path,
    tool: str,
    dataset_key: str,
    top: int = 20,
    cap: int | None = 2_000,
) -> dict:
    """Returns a dict report for (tool, dataset) — FN/FP surface-form
    histograms, label totals, top-N entries."""
    pred_path = out_dir / "checkpoints" / f"{tool}-{dataset_key}.jsonl"
    if not pred_path.exists():
        return {"error": f"no predictions at {pred_path}"}

    if dataset_key not in DATASETS:
        return {"error": f"unknown dataset: {dataset_key}"}
    spec = DATASETS[dataset_key]
    samples = spec.loader(cap if spec.default_n is None or cap < spec.default_n else spec.default_n)

    fn_per_label: dict[str, Counter[str]] = defaultdict(Counter)
    fp_per_label: dict[str, Counter[str]] = defaultdict(Counter)
    label_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0},
    )

    with pred_path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            idx = row["idx"]
            if idx >= len(samples):
                continue
            sample = samples[idx]
            preds_raw = row["spans"]
            # checkpoint span format: (start, end, label) tuples
            preds = [(int(s[0]), int(s[1]), str(s[2])) for s in preds_raw]
            golds = [(g.start, g.end, g.label) for g in sample.spans]

            matched_g = [False] * len(golds)
            matched_p = [False] * len(preds)
            for pi, p in enumerate(preds):
                for gi, g in enumerate(golds):
                    if matched_g[gi]:
                        continue
                    if g[2] != p[2]:
                        continue
                    if _iou((p[0], p[1]), (g[0], g[1])) >= 0.5:
                        matched_g[gi] = True
                        matched_p[pi] = True
                        label_totals[p[2]]["tp"] += 1
                        break

            for gi, g in enumerate(golds):
                if not matched_g[gi]:
                    surface = sample.text[g[0]:g[1]]
                    fn_per_label[g[2]][surface] += 1
                    label_totals[g[2]]["fn"] += 1

            for pi, p in enumerate(preds):
                if not matched_p[pi]:
                    surface = sample.text[p[0]:p[1]]
                    fp_per_label[p[2]][surface] += 1
                    label_totals[p[2]]["fp"] += 1

    return {
        "tool": tool,
        "dataset": dataset_key,
        "samples": len(samples),
        "label_totals": dict(label_totals),
        "fn_top": {lbl: cnt.most_common(top) for lbl, cnt in fn_per_label.items()},
        "fp_top": {lbl: cnt.most_common(top) for lbl, cnt in fp_per_label.items()},
    }


def render_md(report: dict) -> str:
    if "error" in report:
        return f"### {report.get('tool', '?')} / {report.get('dataset', '?')}\n\n_Error_: {report['error']}\n"
    lines = []
    lines.append(f"### {report['tool']} / {report['dataset']} (n={report['samples']})\n")
    lt = report["label_totals"]
    if lt:
        lines.append("| label | TP | FP | FN | recall | precision |")
        lines.append("| ----- | -: | -: | -: | -----: | --------: |")
        for lbl in sorted(lt):
            t = lt[lbl]
            r = t["tp"] / (t["tp"] + t["fn"]) if (t["tp"] + t["fn"]) else 0.0
            p = t["tp"] / (t["tp"] + t["fp"]) if (t["tp"] + t["fp"]) else 0.0
            lines.append(f"| {lbl} | {t['tp']} | {t['fp']} | {t['fn']} | {r:.3f} | {p:.3f} |")
        lines.append("")
    if report["fn_top"]:
        lines.append("**Top FN (gold spans missed)**\n")
        for lbl, items in sorted(report["fn_top"].items()):
            if not items:
                continue
            lines.append(f"- `{lbl}`")
            for surf, n in items:
                shown = surf if len(surf) <= 60 else surf[:57] + "..."
                lines.append(f"  - `{shown}` × {n}")
        lines.append("")
    if report["fp_top"]:
        lines.append("**Top FP (predicted spans not in gold)**\n")
        for lbl, items in sorted(report["fp_top"].items()):
            if not items:
                continue
            lines.append(f"- `{lbl}`")
            for surf, n in items:
                shown = surf if len(surf) <= 60 else surf[:57] + "..."
                lines.append(f"  - `{shown}` × {n}")
        lines.append("")
    return "\n".join(lines)


def list_tools_and_datasets(out_dir: Path) -> tuple[list[str], list[str]]:
    ckpt = out_dir / "checkpoints"
    if not ckpt.is_dir():
        return [], []
    tools: set[str] = set()
    datasets: set[str] = set()
    for p in ckpt.glob("*.jsonl"):
        # Filename: {tool}-{dataset}.jsonl. Greedy split on last '-'
        # would break tool names with dashes, so match against known
        # dataset keys.
        stem = p.stem
        for ds_key in DATASETS:
            if stem.endswith(f"-{ds_key}"):
                tool = stem[: -(len(ds_key) + 1)]
                tools.add(tool)
                datasets.add(ds_key)
                break
    return sorted(tools), sorted(datasets)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--tool", default="")
    ap.add_argument("--dataset", default="")
    ap.add_argument("--all-tools", action="store_true")
    ap.add_argument("--all-datasets", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--cap", type=int, default=2000)
    args = ap.parse_args()

    if args.all_tools or args.all_datasets:
        tools, datasets = list_tools_and_datasets(args.out_dir)
        if args.tool:
            tools = [args.tool]
        if args.dataset:
            datasets = [args.dataset]
        if not tools or not datasets:
            print("# failure analysis\n\n_No checkpoints found in out-dir._", flush=True)
            return
        for tool in tools:
            for ds in datasets:
                report = analyse(
                    out_dir=args.out_dir, tool=tool, dataset_key=ds,
                    top=args.top, cap=args.cap,
                )
                print(render_md(report), flush=True)
                print("\n---\n", flush=True)
    else:
        if not args.tool or not args.dataset:
            ap.error("provide --tool + --dataset (or --all-tools/--all-datasets)")
        report = analyse(
            out_dir=args.out_dir, tool=args.tool, dataset_key=args.dataset,
            top=args.top, cap=args.cap,
        )
        print(render_md(report), flush=True)


if __name__ == "__main__":
    main()
