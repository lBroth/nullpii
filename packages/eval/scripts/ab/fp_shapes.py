# SPDX-License-Identifier: Apache-2.0
"""Shape classes of predicted spans that cover no gold character (false
positives) on one tuning dataset, by predicted label, for two tools.

Prints counts and coarse shapes only (length bucket, character classes, a
known-format prefix family), never span values.

  python fp_shapes.py <results dir> <dataset> <tool A> <tool B>
"""
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))
import bench_full  # noqa: E402
from miss_shapes import shape  # noqa: E402

TOP_SHAPES = 6


def load_labelled(results: Path, tool: str, dataset: str) -> list[list[tuple[int, int, str]]]:
    by_idx: dict[int, list] = {}
    path = results / "checkpoints" / f"{tool}-{dataset}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_idx[int(row["idx"])] = row["spans"]
    return [[(int(s[0]), int(s[1]), str(s[2])) for s in by_idx[i]] for i in range(len(by_idx))]


def false_positives(results: Path, dataset: str, tool: str):
    spec = next(s for s in bench_full.DATASET_CONFIGS if s.key == dataset)
    preds = load_labelled(results, tool, dataset)
    samples = spec.loader(len(preds))
    chars: collections.Counter = collections.Counter()
    shapes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for smp, pr in zip(samples, preds):
        gold = bytearray(len(smp.text))
        for g in smp.spans:
            gold[g.start:g.end] = b"\x01" * (g.end - g.start)
        for a, b, label in pr:
            if any(gold[a:b]):
                continue
            chars[label] += b - a
            shapes[label][shape(smp.text[a:b])] += 1
    return chars, shapes


def main() -> None:
    results, dataset, tools = Path(sys.argv[1]), sys.argv[2], sys.argv[3:5]
    for tool in tools:
        chars, shapes = false_positives(results, dataset, tool)
        print(f"\n== {tool} on {dataset}: false-positive chars {sum(chars.values())}")
        for label, n in chars.most_common():
            print(f"  {label:24s} chars {n:7d}  spans {sum(shapes[label].values()):5d}  top shapes {shapes[label].most_common(TOP_SHAPES)}")


if __name__ == "__main__":
    main()
