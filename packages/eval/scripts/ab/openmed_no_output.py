# SPDX-License-Identifier: Apache-2.0
"""OpenMed's R3 texts with no output, per row and dataset.

openmed.deidentify returns no text for a refusal (`suspicious_content`, ...)
or the package's own sweep-invariant failure; the adapter scores those as no
spans and logs `code=<code>, chars=<len>` in input order, never the text.
Each logged failure is matched to the next document, in idx order, whose
length is `chars` and whose checkpoint row has no span. Prints counts per
dataset and code, and writes {dataset: [idx]} per row and for their union.

  python3 openmed_no_output.py <r3-texts.jsonl> <r3-report dir> <out dir>
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

texts_path, report, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
lengths: dict[str, list[int]] = defaultdict(list)
with texts_path.open(encoding="utf-8") as f:
    for line in f:
        row = json.loads(line)
        lengths[row["dataset"]].append(len(row["text"]))

DATASET = re.compile(r"=== DATASET (\S+) ===")
FAILED = re.compile(r"deidentify returned no text \(code=(\w+), chars=(\d+)\)")
union: dict[str, set[int]] = defaultdict(set)
for tool in ("openmed-small", "openmed-large"):
    for variant in ("default", "tuned"):
        row_name = tool if variant == "tuned" else f"{tool}@default"
        failures: dict[str, list[tuple[str, int]]] = defaultdict(list)
        dataset = None
        for line in (report / tool / variant / "bench.log").read_text(encoding="utf-8").splitlines():
            if m := DATASET.search(line):
                dataset = m.group(1)
            elif m := FAILED.search(line):
                failures[dataset].append((m.group(1), int(m.group(2))))
        excluded: dict[str, list[int]] = {}
        for ds, items in failures.items():
            ckpt = report / "checkpoints" / f"{row_name}-{ds}.jsonl"
            empty = set()
            with ckpt.open(encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    if not r["spans"]:
                        empty.add(r["idx"])
            idxs, at = [], 0
            for code, chars in items:
                while at < len(lengths[ds]) and not (lengths[ds][at] == chars and at in empty):
                    at += 1
                if at == len(lengths[ds]):
                    raise SystemExit(f"{row_name} {ds}: no match for code={code} chars={chars}")
                idxs.append(at)
                at += 1
            excluded[ds] = idxs
            union[ds].update(idxs)
            codes = Counter(code for code, _ in items)
            print(f"{row_name:22s} {ds:26s} {len(items):5d} of {len(lengths[ds]):5d}  {dict(codes)}")
        (out / f"{row_name}.json").write_text(json.dumps(excluded) + "\n")
(out / "openmed-union.json").write_text(json.dumps({d: sorted(v) for d, v in union.items()}) + "\n")
print("union:", {d: len(v) for d, v in union.items()})
