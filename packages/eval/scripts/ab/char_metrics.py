# SPDX-License-Identifier: Apache-2.0
"""Character-level redaction metrics with paired bootstrap CIs (METHOD.md).

Label-agnostic by design: for redaction, a PII character is protected if
*any* predicted span covers it, whatever label the tool gave it. This is
the quantity a user cares about (what reaches the model unmasked), and it
removes label-mapping asymmetries between tools.

  char-recall    = covered gold chars / gold chars        (1 - leak rate)
  char-precision = covered gold chars / predicted chars   (1 - over-masking)
  char-F2        = recall-weighted F-beta, beta = 2 (the gate)
  char-F1, F0.5  = reported next to it (PROTOCOL rule change 9), since F2
                   rewards over-masking

Reads the per-document predictions `bench_full.py` writes
(`<results>/checkpoints/<tool>-<dataset>.jsonl`) and reloads gold through
the same loaders, so no model is re-run. `--mask-all` adds a pseudo-tool
that masks every character, the floor any detector should clear.

`--language en` keeps only the documents whose loader records that language
(R3's English-only macro, rule change 10); a dataset with none is skipped.

Sensitivity analyses, never the gate: `--cluster-rows` resamples every R3
set by its rows' cluster ids (source document or conversation), not only
the sets the analysis clusters; `--exclude <file.json>` ({dataset: [idx]})
drops those documents for every tool, so a comparison stays paired.

  python char_metrics.py --results <dir> --datasets a,b --baseline nullpii --out m.json [--mask-all]
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
# F-beta variants reported per tool: key -> beta. "f2" is the gate.
F_BETAS = {"f2": 2.0, "f1": 1.0, "f05": 0.5}
MASK_ALL = "mask-all"
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
CI_LOW_PCT = 2.5
CI_HIGH_PCT = 97.5


def _covered(spans: list[tuple[int, int]], length: int) -> np.ndarray:
    mask = np.zeros(length, dtype=bool)
    for start, end in spans:
        mask[max(0, start) : min(length, end)] = True
    return mask


def doc_counts(
    text_len: int,
    gold: list[tuple[int, int]],
    pred: list[tuple[int, int]],
    ignore: tuple[tuple[int, int], ...] = (),
) -> tuple[int, int, int]:
    """(gold chars, predicted chars, overlap chars) for one document.
    Predicted characters inside an ignore region that are not gold are not
    counted, so masking out-of-scope text costs no precision."""
    g = _covered(gold, text_len)
    p = _covered(pred, text_len) & ~(_covered(list(ignore), text_len) & ~g)
    return int(g.sum()), int(p.sum()), int((g & p).sum())


def _fbeta(precision: float, recall: float, beta: float) -> float:
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1 + b2) * precision * recall / denom if denom else 0.0


def scores(gold: np.ndarray, pred: np.ndarray, hit: np.ndarray) -> dict[str, float]:
    recall = hit.sum() / gold.sum() if gold.sum() else 0.0
    precision = hit.sum() / pred.sum() if pred.sum() else 0.0
    out = {"recall": float(recall), "precision": float(precision)}
    out.update({key: float(_fbeta(precision, recall, beta)) for key, beta in F_BETAS.items()})
    return out


def _bootstrap_fbeta(
    gold: np.ndarray, pred: np.ndarray, hit: np.ndarray, idx: np.ndarray, beta: float = BETA
) -> np.ndarray:
    g, p, h = gold[idx].sum(axis=1), pred[idx].sum(axis=1), hit[idx].sum(axis=1)
    rec = np.divide(h, g, out=np.zeros_like(h, dtype=float), where=g > 0)
    prec = np.divide(h, p, out=np.zeros_like(h, dtype=float), where=p > 0)
    b2 = beta * beta
    denom = b2 * prec + rec
    return np.divide((1 + b2) * prec * rec, denom, out=np.zeros_like(rec), where=denom > 0)


def _bootstrap_f2(gold: np.ndarray, pred: np.ndarray, hit: np.ndarray, idx: np.ndarray) -> np.ndarray:
    return _bootstrap_fbeta(gold, pred, hit, idx, BETA)


def _bootstrap_recall(gold: np.ndarray, hit: np.ndarray, idx: np.ndarray) -> np.ndarray:
    g, h = gold[idx].sum(axis=1), hit[idx].sum(axis=1)
    return np.divide(h, g, out=np.zeros_like(h, dtype=float), where=g > 0)


def _bootstrap_precision(pred: np.ndarray, hit: np.ndarray, idx: np.ndarray) -> np.ndarray:
    p, h = pred[idx].sum(axis=1), hit[idx].sum(axis=1)
    return np.divide(h, p, out=np.zeros_like(h, dtype=float), where=p > 0)


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


def dataset_arrays(
    results: Path,
    dataset: str,
    tools: list[str],
    mask_all: bool = False,
    language: str | None = None,
    exclude: frozenset[int] = frozenset(),
) -> tuple[np.ndarray, dict[str, tuple], dict[str, dict]]:
    """Per-tool count arrays over the dataset's documents, or over those in
    `language`, less the positions in `exclude`. The first value holds the
    kept documents' positions."""
    spec = next((s for s in bench_full.DATASET_CONFIGS if s.key == dataset), None)
    if spec is None:
        raise ValueError(f"unknown dataset {dataset!r}")
    preds = {t: load_predictions(results, t, dataset) for t in tools}
    n = len(next(iter(preds.values())))
    if any(len(v) != n for v in preds.values()):
        raise ValueError(f"{dataset}: tools have different document counts")
    # The full set bench_full runs by default, not the first n: a run that
    # crashed part-way leaves a short checkpoint, which must not be scored as
    # if it were the dataset.
    samples = spec.loader(spec.default_n)
    if len(samples) != n:
        raise ValueError(f"{dataset}: checkpoints have {n} docs, the dataset has {len(samples)}: incomplete run")
    kept = [
        i
        for i, smp in enumerate(samples)
        if (language is None or smp.language == language) and i not in exclude
    ]
    if not kept:
        return np.array([], dtype=np.int64), {}, {}
    samples = [samples[i] for i in kept]
    preds = {t: [p[i] for i in kept] for t, p in preds.items()}
    gold_spans = [[(s.start, s.end) for s in smp.spans] for smp in samples]
    if mask_all:
        preds[MASK_ALL] = [[(0, len(smp.text))] for smp in samples]
    per_tool = {}
    per_label = {}
    for tool, tool_preds in preds.items():
        counts = np.array(
            [
                doc_counts(len(smp.text), g, p, smp.ignore)
                for smp, g, p in zip(samples, gold_spans, tool_preds, strict=True)
            ],
        )
        per_tool[tool] = (counts[:, 0], counts[:, 1], counts[:, 2])
        per_label[tool] = label_counts(samples, tool_preds)
    return np.array(kept, dtype=np.int64), per_tool, per_label


def by_cluster(per_tool: dict[str, tuple], per_label: dict[str, dict], clusters: list[str]) -> tuple[dict, dict, int]:
    """Sum per-document counts within each cluster, so the bootstrap draws
    clusters instead of documents (rule change 9, item 5). Point scores do
    not change: every count is a character total."""
    keys = {c: i for i, c in enumerate(sorted(set(clusters)))}
    inv = np.array([keys[c] for c in clusters])

    def agg(a: np.ndarray) -> np.ndarray:
        return np.bincount(inv, weights=a, minlength=len(keys)).astype(np.int64)

    tools = {t: tuple(agg(a) for a in arrays) for t, arrays in per_tool.items()}
    labels = {t: {lab: (agg(g), agg(h)) for lab, (g, h) in counts.items()} for t, counts in per_label.items()}
    return tools, labels, len(keys)


def label_counts(samples: list, tool_preds: list[list[tuple[int, int]]]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per gold label: gold characters and covered characters, per document.
    Coverage is label-agnostic: a gold person covered by a predicted address
    counts."""
    n = len(samples)
    gold: dict[str, np.ndarray] = {}
    hit: dict[str, np.ndarray] = {}
    for i, (smp, preds) in enumerate(zip(samples, tool_preds, strict=True)):
        mask = _covered(preds, len(smp.text))
        for s in smp.spans:
            seg = mask[max(0, s.start) : min(len(smp.text), s.end)]
            gold.setdefault(s.label, np.zeros(n, dtype=np.int64))[i] += seg.size
            hit.setdefault(s.label, np.zeros(n, dtype=np.int64))[i] += int(seg.sum())
    return {label: (gold[label], hit[label]) for label in sorted(gold) if gold[label].sum() > 0}


def per_label_recall(
    counts: dict[str, tuple[np.ndarray, np.ndarray]],
    base_counts: dict[str, tuple[np.ndarray, np.ndarray]] | None,
    idx: np.ndarray,
) -> dict[str, dict]:
    """Char-recall of each gold label (which kinds of PII leak), and, against
    a baseline, the paired-bootstrap CI of baseline minus tool recall on the
    same resampled documents as the dataset-level CIs. PROTOCOL T3 gates on
    it: a label must not lose recall significantly."""
    out: dict[str, dict] = {}
    for label, (g, h) in counts.items():
        entry: dict = {"recall": float(h.sum() / g.sum()), "gold_chars": int(g.sum())}
        if base_counts is not None:
            if label not in base_counts:
                raise ValueError(f"label {label!r} has gold for the tool but not for the baseline")
            bg, bh = base_counts[label]
            entry["baseline_minus_tool_recall_ci"] = _ci(_bootstrap_recall(bg, bh, idx) - _bootstrap_recall(g, h, idx))
        out[label] = entry
    return out


def compare(
    per_tool: dict[str, tuple],
    per_label: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]],
    baseline: str,
    n: int,
    rng: np.random.Generator,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Point scores per tool, per-label recall with paired CIs, and the
    bootstrap samples of baseline - tool char-F2 so the caller can build a
    macro CI across datasets."""
    idx = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
    base_f = {key: _bootstrap_fbeta(*per_tool[baseline], idx, beta) for key, beta in F_BETAS.items()}
    base_rec = _bootstrap_recall(per_tool[baseline][0], per_tool[baseline][2], idx)
    base_prec = _bootstrap_precision(per_tool[baseline][1], per_tool[baseline][2], idx)
    out = {}
    diffs: dict[str, dict[str, np.ndarray]] = {}
    for tool, arrays in per_tool.items():
        entry = scores(*arrays)
        entry["leak_rate"] = 1 - entry["recall"]
        entry["over_masking"] = 1 - entry["precision"]
        entry["docs"] = n
        if tool != baseline:
            d_f = {key: base_f[key] - _bootstrap_fbeta(*arrays, idx, beta) for key, beta in F_BETAS.items()}
            d_rec = base_rec - _bootstrap_recall(arrays[0], arrays[2], idx)
            for key in F_BETAS:
                entry[f"baseline_minus_tool_{key}_ci"] = _ci(d_f[key])
            entry["baseline_minus_tool_recall_ci"] = _ci(d_rec)
            entry["baseline_minus_tool_precision_ci"] = _ci(base_prec - _bootstrap_precision(arrays[1], arrays[2], idx))
            diffs[tool] = d_f
        entry["per_label_recall"] = per_label_recall(
            per_label[tool], None if tool == baseline else per_label[baseline], idx
        )
        out[tool] = entry
    return out, diffs


def macro_summary(report: dict, diffs: dict[str, list[dict[str, np.ndarray]]], baseline: str) -> dict:
    """Unweighted mean of each F-beta over datasets; CI from per-dataset
    bootstrap samples averaged index-wise (each dataset resampled
    independently). `f2_lodo` gives the lowest and highest macro char-F2 left
    after dropping one dataset, so one dataset cannot carry the result."""
    datasets = [d for d in report if not d.startswith("_")]
    tools = report[datasets[0]].keys()
    out = {}
    for tool in tools:
        entry: dict = {key: float(np.mean([report[d][tool][key] for d in datasets])) for key in F_BETAS}
        if len(datasets) > 1:
            lodo = [np.mean([report[d][tool]["f2"] for d in datasets if d != left]) for left in datasets]
            entry["f2_lodo"] = [float(min(lodo)), float(max(lodo))]
        if tool != baseline:
            for key in F_BETAS:
                entry[f"baseline_minus_tool_{key}_ci"] = _ci(np.mean(np.stack([d[key] for d in diffs[tool]]), axis=0))
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
    parser.add_argument("--mask-all", action="store_true", help=f"add the '{MASK_ALL}' floor as a pseudo-tool")
    parser.add_argument("--language", help="score only documents in this language (ISO 639-1)")
    parser.add_argument(
        "--cluster-rows", action="store_true", help="sensitivity: resample every R3 set by its rows' cluster ids"
    )
    parser.add_argument("--exclude", type=Path, help="sensitivity: JSON {dataset: [idx]} dropped for every tool")
    args = parser.parse_args()
    excluded = {d: frozenset(v) for d, v in json.loads(args.exclude.read_text()).items()} if args.exclude else {}

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    report: dict[str, dict] = {}
    all_diffs: dict[str, list[np.ndarray]] = {}
    for dataset in args.datasets.split(","):
        tools = args.tools.split(",") if args.tools else tools_with_checkpoints(args.results, dataset)
        if args.baseline not in tools:
            raise ValueError(f"{dataset}: baseline {args.baseline!r} has no checkpoint")
        kept, per_tool, per_label = dataset_arrays(
            args.results, dataset, tools, args.mask_all, args.language, excluded.get(dataset, frozenset())
        )
        if not len(kept):
            print(f"{dataset}: no document in {args.language!r}, skipped", flush=True)
            continue
        docs, units = len(kept), len(kept)
        cluster_ids = bench_full.DATASET_CLUSTERS.get(dataset)
        if cluster_ids is None and args.cluster_rows:
            cluster_ids = bench_full.R3_ROW_CLUSTERS.get(dataset)
        if cluster_ids is not None:
            every = cluster_ids(int(kept[-1]) + 1)
            per_tool, per_label, units = by_cluster(per_tool, per_label, [every[i] for i in kept])
        report[dataset], diffs = compare(per_tool, per_label, args.baseline, units, rng)
        if cluster_ids is not None:
            for entry in report[dataset].values():
                entry["docs"], entry["bootstrap_clusters"] = docs, units
        for tool, d in diffs.items():
            all_diffs.setdefault(tool, []).append(d)
        row = {t: round(v["f2"], 4) for t, v in report[dataset].items()}
        print(f"{dataset}: char-F2 {row}", flush=True)

    report["_macro"] = macro_summary(report, all_diffs, args.baseline)
    for tool, entry in report["_macro"].items():
        print(f"macro {tool}: char-F2 {entry['f2']:.4f} baseline-minus-tool CI {entry.get('baseline_minus_tool_f2_ci')}")

    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
