# SPDX-License-Identifier: Apache-2.0
"""Character-level redaction metrics with paired bootstrap CIs (PROTOCOL.md).

Label-agnostic by design: for redaction, a PII character is protected if
*any* predicted span covers it, whatever label the tool gave it. This is
the quantity a user cares about (what reaches the model unmasked), and it
removes label-mapping asymmetries between tools.

  char-recall    = covered gold chars / gold chars        (1 - leak rate)
  char-precision = covered gold chars / predicted chars   (1 - over-masking)
  char-F2        = recall-weighted F-beta, beta = 2

Reads the per-document predictions `bench_full.py` writes
(`<results>/checkpoints/<tool>-<dataset>.jsonl`) and reloads gold through
the same loaders, so no model is re-run.

  python char_metrics.py --results <dir> --datasets a,b --baseline nullpii --out m.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "src"))

import bench_full  # noqa: E402

BETA = 2.0
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
CI_LOW_PCT = 2.5
CI_HIGH_PCT = 97.5


def _covered(spans: list[tuple[int, int]], length: int) -> np.ndarray:
    mask = np.zeros(length, dtype=bool)
    for start, end in spans:
        mask[max(0, start) : min(length, end)] = True
    return mask


def doc_counts(text_len: int, gold: list[tuple[int, int]], pred: list[tuple[int, int]]) -> tuple[int, int, int]:
    """(gold chars, predicted chars, overlap chars) for one document."""
    g = _covered(gold, text_len)
    p = _covered(pred, text_len)
    return int(g.sum()), int(p.sum()), int((g & p).sum())


def scores(gold: np.ndarray, pred: np.ndarray, hit: np.ndarray) -> dict[str, float]:
    recall = hit.sum() / gold.sum() if gold.sum() else 0.0
    precision = hit.sum() / pred.sum() if pred.sum() else 0.0
    b2 = BETA * BETA
    denom = b2 * precision + recall
    f2 = (1 + b2) * precision * recall / denom if denom else 0.0
    return {"recall": float(recall), "precision": float(precision), "f2": float(f2)}


def _bootstrap_f2(gold: np.ndarray, pred: np.ndarray, hit: np.ndarray, idx: np.ndarray) -> np.ndarray:
    g, p, h = gold[idx].sum(axis=1), pred[idx].sum(axis=1), hit[idx].sum(axis=1)
    rec = np.divide(h, g, out=np.zeros_like(h, dtype=float), where=g > 0)
    prec = np.divide(h, p, out=np.zeros_like(h, dtype=float), where=p > 0)
    b2 = BETA * BETA
    denom = b2 * prec + rec
    return np.divide((1 + b2) * prec * rec, denom, out=np.zeros_like(rec), where=denom > 0)


def _bootstrap_recall(gold: np.ndarray, hit: np.ndarray, idx: np.ndarray) -> np.ndarray:
    g, h = gold[idx].sum(axis=1), hit[idx].sum(axis=1)
    return np.divide(h, g, out=np.zeros_like(h, dtype=float), where=g > 0)


def load_predictions(results: Path, tool: str, dataset: str) -> list[list[tuple[int, int]]]:
    """Per-document predictions, by idx. A bench run resumed after an
    interruption can append rows for indices it had already written; the
    later row wins (it is the completed run's). Missing indices raise."""
    path = results / "checkpoints" / f"{tool}-{dataset}.jsonl"
    by_idx: dict[int, list] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_idx[int(row["idx"])] = row["spans"]
    if sorted(by_idx) != list(range(len(by_idx))):
        raise ValueError(f"{path}: idx sequence has gaps; the run did not complete")
    return [[(int(s[0]), int(s[1])) for s in by_idx[i]] for i in range(len(by_idx))]


def tools_with_checkpoints(results: Path, dataset: str) -> list[str]:
    suffix = f"-{dataset}.jsonl"
    return sorted(p.name[: -len(suffix)] for p in (results / "checkpoints").glob(f"*{suffix}"))


def dataset_arrays(results: Path, dataset: str, tools: list[str]) -> tuple[np.ndarray, dict[str, tuple]]:
    spec = next((s for s in bench_full.DATASET_CONFIGS if s.key == dataset), None)
    if spec is None:
        raise ValueError(f"unknown dataset {dataset!r}")
    preds = {t: load_predictions(results, t, dataset) for t in tools}
    n = len(next(iter(preds.values())))
    if any(len(v) != n for v in preds.values()):
        raise ValueError(f"{dataset}: tools have different document counts")
    samples = spec.loader(n)
    if len(samples) != n:
        raise ValueError(f"{dataset}: loader returned {len(samples)} docs, checkpoints have {n}")
    gold_spans = [[(s.start, s.end) for s in smp.spans] for smp in samples]
    per_tool = {}
    per_label = {}
    for tool, tool_preds in preds.items():
        counts = np.array(
            [doc_counts(len(smp.text), g, p) for smp, g, p in zip(samples, gold_spans, tool_preds, strict=True)],
        )
        per_tool[tool] = (counts[:, 0], counts[:, 1], counts[:, 2])
        per_label[tool] = per_label_recall(samples, tool_preds)
    return np.arange(n), per_tool, per_label


def per_label_recall(samples: list, tool_preds: list[list[tuple[int, int]]]) -> dict[str, dict[str, float]]:
    """Char-recall of each gold label: which kinds of PII leak. Coverage is
    still label-agnostic: a gold person covered by a predicted address counts."""
    gold_chars: dict[str, int] = {}
    hit_chars: dict[str, int] = {}
    for smp, preds in zip(samples, tool_preds, strict=True):
        mask = _covered(preds, len(smp.text))
        for s in smp.spans:
            seg = mask[max(0, s.start) : min(len(smp.text), s.end)]
            gold_chars[s.label] = gold_chars.get(s.label, 0) + int(seg.size)
            hit_chars[s.label] = hit_chars.get(s.label, 0) + int(seg.sum())
    return {
        label: {"recall": hit_chars[label] / total, "gold_chars": total}
        for label, total in sorted(gold_chars.items())
        if total > 0
    }


def compare(
    per_tool: dict[str, tuple], baseline: str, n: int, rng: np.random.Generator
) -> tuple[dict, dict[str, np.ndarray]]:
    """Point scores per tool, plus the bootstrap samples of baseline - tool
    char-F2 so the caller can build a macro CI across datasets."""
    idx = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
    base_f2 = _bootstrap_f2(*per_tool[baseline], idx)
    base_rec = _bootstrap_recall(per_tool[baseline][0], per_tool[baseline][2], idx)
    out = {}
    diffs: dict[str, np.ndarray] = {}
    for tool, arrays in per_tool.items():
        entry = scores(*arrays)
        entry["leak_rate"] = 1 - entry["recall"]
        entry["over_masking"] = 1 - entry["precision"]
        entry["docs"] = n
        if tool != baseline:
            d_f2 = base_f2 - _bootstrap_f2(*arrays, idx)
            d_rec = base_rec - _bootstrap_recall(arrays[0], arrays[2], idx)
            entry["baseline_minus_tool_f2_ci"] = _ci(d_f2)
            entry["baseline_minus_tool_recall_ci"] = _ci(d_rec)
            diffs[tool] = d_f2
        out[tool] = entry
    return out, diffs


def macro_summary(report: dict, diffs: dict[str, list[np.ndarray]], baseline: str) -> dict:
    """Unweighted mean char-F2 over datasets; CI from per-dataset bootstrap
    samples averaged index-wise (each dataset resampled independently)."""
    datasets = [d for d in report if not d.startswith("_")]
    tools = report[datasets[0]].keys()
    out = {}
    for tool in tools:
        entry = {"f2": float(np.mean([report[d][tool]["f2"] for d in datasets]))}
        if tool != baseline:
            entry["baseline_minus_tool_f2_ci"] = _ci(np.mean(np.stack(diffs[tool]), axis=0))
        out[tool] = entry
    return out


def _ci(samples: np.ndarray) -> list[float]:
    return [float(np.percentile(samples, CI_LOW_PCT)), float(np.percentile(samples, CI_HIGH_PCT))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--datasets", required=True)
    parser.add_argument("--baseline", default="nullpii")
    parser.add_argument("--tools", default="", help="comma list; default = every tool with checkpoints")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    report: dict[str, dict] = {}
    all_diffs: dict[str, list[np.ndarray]] = {}
    for dataset in args.datasets.split(","):
        tools = args.tools.split(",") if args.tools else tools_with_checkpoints(args.results, dataset)
        if args.baseline not in tools:
            raise ValueError(f"{dataset}: baseline {args.baseline!r} has no checkpoint")
        idx, per_tool, per_label = dataset_arrays(args.results, dataset, tools)
        report[dataset], diffs = compare(per_tool, args.baseline, len(idx), rng)
        for tool, d in diffs.items():
            all_diffs.setdefault(tool, []).append(d)
        for tool, labels in per_label.items():
            report[dataset][tool]["per_label_recall"] = labels
        row = {t: round(v["f2"], 4) for t, v in report[dataset].items()}
        print(f"{dataset}: char-F2 {row}", flush=True)

    report["_macro"] = macro_summary(report, all_diffs, args.baseline)
    for tool, entry in report["_macro"].items():
        print(f"macro {tool}: char-F2 {entry['f2']:.4f} baseline-minus-tool CI {entry.get('baseline_minus_tool_f2_ci')}")

    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
