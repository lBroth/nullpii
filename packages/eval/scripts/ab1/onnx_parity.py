# SPDX-License-Identifier: Apache-2.0
"""Does onnx-community's ONNX export answer like urchade/gliner_multi_pii-v1's PyTorch weights?

Same sampled texts, same windows (`_gliner_windows`), same labels and threshold as the
gliner-onnx-pii-fp32 competitor; the two models' raw entities are compared with each other,
never with the gold. Counts only.

  python onnx_parity.py <kit src> <gold dir> [n per set]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from gliner import GLiNER  # noqa: E402

from nullpii_eval import adapters as ad  # noqa: E402

SETS = {"ab1-a": "ab1-test.jsonl", "ab1-b1": "b1.jsonl", "ab1-b2": "b2.jsonl"}
ONNX = ("onnx-community/gliner_multi_pii-v1", "2e0397a7e8a250d76c37122232b3cbde42c8d629")
TORCH = ("urchade/gliner_multi_pii-v1", "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d")
THRESHOLD = 0.5
NEAR = 0.02  # an entity found by one model only, scoring within this of the threshold, is a near-threshold flip


def main() -> None:
    gold, n = Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 100
    onnx = GLiNER.from_pretrained(ONNX[0], revision=ONNX[1], load_onnx_model=True, onnx_model_file="onnx/model.onnx", local_files_only=True)
    torch_m = GLiNER.from_pretrained(TORCH[0], revision=TORCH[1], map_location="cuda", local_files_only=True)
    torch_m.eval()
    tok = onnx.data_processor.transformer_tokenizer
    tok_t = torch_m.data_processor.transformer_tokenizer
    labels = list(ad._URCHADE_LABELS)

    def count(pieces):
        return [len(ids) for ids in tok(pieces, add_special_tokens=False)["input_ids"]]

    total = {"windows": 0, "tokenizer_differs": 0, "entities_onnx": 0, "entities_torch": 0, "same": 0,
             "label_differs": 0, "only_onnx": 0, "only_torch": 0, "only_near_threshold": 0, "max_score_diff": 0.0}
    for key, f in SETS.items():
        rows = [json.loads(l)["text"] for l in open(gold / f, encoding="utf-8") if l.strip()]
        sample = random.Random(0).sample(range(len(rows)), min(n, len(rows)))
        c = {k: 0 for k in total} | {"max_score_diff": 0.0}
        for i in sample:
            chunks = [ch for _, ch in ad._gliner_windows(rows[i], 384, 12, count)]
            for ch in chunks:
                words = [m.group() for m in ad._GLINER_WORD.finditer(ch)]
                if words and tok(words, is_split_into_words=True)["input_ids"] != tok_t(words, is_split_into_words=True)["input_ids"]:
                    c["tokenizer_differs"] += 1
            eo = onnx.inference(chunks, labels, threshold=THRESHOLD, batch_size=1)
            et = torch_m.inference(chunks, labels, threshold=THRESHOLD, batch_size=1)
            for a, b in zip(eo, et, strict=True):
                c["windows"] += 1
                da = {(e["start"], e["end"]): e for e in a}
                db = {(e["start"], e["end"]): e for e in b}
                c["entities_onnx"] += len(da)
                c["entities_torch"] += len(db)
                for k in da.keys() & db.keys():
                    if da[k]["label"] != db[k]["label"]:
                        c["label_differs"] += 1
                    else:
                        c["same"] += 1
                    c["max_score_diff"] = max(c["max_score_diff"], abs(da[k]["score"] - db[k]["score"]))
                for side, d in (("only_onnx", da.keys() - db.keys()), ("only_torch", db.keys() - da.keys())):
                    src = da if side == "only_onnx" else db
                    c[side] += len(d)
                    c["only_near_threshold"] += sum(1 for k in d if src[k]["score"] < THRESHOLD + NEAR)
        print(json.dumps({"set": key, "docs": len(sample), **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in c.items()}}), flush=True)
        for k in total:
            total[k] = max(total[k], c[k]) if k == "max_score_diff" else total[k] + c[k]
    print(json.dumps({"set": "all", **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in total.items()}}))


if __name__ == "__main__":
    main()
