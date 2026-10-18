# SPDX-License-Identifier: Apache-2.0
"""Shape classes of gold characters a baseline covers and a candidate misses.

  python regress_shapes.py <results> <baseline> <candidate> <dataset> <label>

Explains a per-label recall drop from `verdict.py`: how many characters
and spans regressed, whether whole spans or a head, tail or middle part
were lost, and the coarse shapes of the lost parts (`miss_shapes.shape`).
Prints counts only -- never span values.
"""
import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))
import bench_full  # noqa: E402
from char_metrics import load_predictions  # noqa: E402
from miss_shapes import shape  # noqa: E402

TOP_SHAPES = 12


def coverage(n: int, preds) -> bytearray:
    cov = bytearray(n)
    for a, b in preds:
        cov[a:b] = b"\1" * (b - a)
    return cov


def where(lost: list[int], start: int, end: int) -> str:
    if len(lost) == end - start:
        return "whole span"
    if lost[0] == start:
        return "head"
    if lost[-1] == end - 1:
        return "tail"
    return "middle"


def main() -> None:
    results, base, cand, dataset, label = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    spec = next(s for s in bench_full.DATASET_CONFIGS if s.key == dataset)
    pb, pc = load_predictions(results, base, dataset), load_predictions(results, cand, dataset)
    samples = spec.loader(len(pb))
    lost_chars = gained = docs = 0
    kinds, shapes = collections.Counter(), collections.Counter()
    for smp, b, c in zip(samples, pb, pc):
        cb, cc = coverage(len(smp.text), b), coverage(len(smp.text), c)
        hit = False
        for s in smp.spans:
            if s.label != label:
                continue
            gained += sum(1 for i in range(s.start, s.end) if cc[i] and not cb[i])
            lost = [i for i in range(s.start, s.end) if cb[i] and not cc[i]]
            if not lost:
                continue
            hit = True
            lost_chars += len(lost)
            kinds[where(lost, s.start, s.end)] += 1
            shapes[shape(smp.text[lost[0]:lost[-1] + 1])] += 1
        docs += hit
    print(f"{dataset} {label}: lost {lost_chars} chars in {docs} docs, gained {gained}")
    print(" where:", dict(kinds))
    for k, v in shapes.most_common(TOP_SHAPES):
        print(f"  {v:4d} {k}")


if __name__ == "__main__":
    main()
