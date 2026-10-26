# SPDX-License-Identifier: Apache-2.0
"""Shape classes of gold spans nullpii misses on the tuning set.

Prints counts by label and coarse shape only (length bucket, character
classes, a known-format prefix family) -- never span values.
"""
import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))
import bench_full  # noqa: E402
from char_metrics import load_predictions  # noqa: E402

DATASETS = ["ai4privacy-300k-heldout", "isotonic-en-heldout", "isotonic-de-heldout", "isotonic-fr-heldout", "isotonic-it-heldout", "claude-code-traces-tuning"]
LABELS = {"secret", "account_number", "private_driver_license", "private_phone", "private_person"}
PREFIXES = ["AKIA", "ASIA", "ghp_", "gho_", "github_pat_", "glpat-", "sk-ant-", "sk-proj-", "sk-", "xoxb-", "xoxp-", "AIza", "eyJ", "-----BEGIN", "SG.", "npm_", "hf_", "pk_", "rk_", "whsec_", "postgres", "mysql", "mongodb", "redis"]

def shape(v):
    fam = next((p for p in PREFIXES if v.startswith(p)), "")
    cls = "".join(c for c, rx in [("d", r"\d"), ("U", r"[A-Z]"), ("l", r"[a-z]"), ("s", r"[^A-Za-z0-9\s]"), ("w", r"\s")] if re.search(rx, v))
    n = len(v)
    lb = "<=6" if n <= 6 else "7-12" if n <= 12 else "13-24" if n <= 24 else "25-48" if n <= 48 else ">48"
    return f"{fam or '-'}|{cls}|{lb}"

def main() -> None:
    results = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent.parent / "results/ab-loop/tuning-compare"
    tool = sys.argv[2] if len(sys.argv) > 2 else "nullpii-T4d"
    for ds in DATASETS:
        spec = next(s for s in bench_full.DATASET_CONFIGS if s.key == ds)
        preds = load_predictions(results, tool, ds)
        samples = spec.loader(len(preds))
        tot = collections.Counter()
        miss = collections.Counter()
        shapes = collections.defaultdict(collections.Counter)
        for smp, pr in zip(samples, preds):
            cov = bytearray(len(smp.text))
            for a, b in pr:
                cov[a:b] = b"\x01" * (b - a)
            for g in smp.spans:
                if g.label not in LABELS:
                    continue
                n = g.end - g.start
                hit = sum(cov[g.start:g.end])
                tot[g.label] += 1
                if hit < n:
                    kind = "missed" if hit == 0 else "partial"
                    miss[(g.label, kind)] += 1
                    shapes[g.label][shape(smp.text[g.start:g.end])] += 1
        print(f"\n== {ds}")
        for lab in sorted(tot):
            m = miss[(lab, "missed")]
            p = miss[(lab, "partial")]
            print(f"  {lab:24s} spans {tot[lab]:5d}  missed {m:4d}  partial {p:4d}  top shapes {shapes[lab].most_common(5)}")


if __name__ == "__main__":
    main()
