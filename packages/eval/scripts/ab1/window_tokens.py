# SPDX-License-Identifier: Apache-2.0
"""AB-1: subword length of the GLiNER windows the adapter builds, per model and set.

Counts and document indices only, never text.

  python window_tokens.py <gold dir> <hf hub dir>
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

from transformers import AutoTokenizer

WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")
SETS = {"ab1-a": "ab1-test.jsonl", "ab1-b1": "b1.jsonl", "ab1-b2": "b2.jsonl"}
# tool: (hub dir, max words per window as the adapter uses it, overlap = max_width)
MODELS = {
    "gliner-pii-large-v1": ("models--knowledgator--gliner-pii-large-v1.0", 768, 100),
    "gliner-stream-pii": ("models--knowledgator--gliner-stream-pii-v1.0", 2048, 12),
    "nemotron-pii-raw": ("models--nvidia--gliner-PII", 384, 12),
    "gliner-onnx-pii-fp32": ("models--onnx-community--gliner_multi_pii-v1", 384, 12),
}
EDGES = (1024, 2048, 4096, 8192)


def windows(words: list[str], max_words: int, overlap: int) -> list[list[str]]:
    if len(words) <= max_words:
        return [words]
    stride = max_words - overlap
    out = []
    for i in range(0, len(words), stride):
        out.append(words[i:i + max_words])
        if i + max_words >= len(words):
            break
    return out


def main() -> None:
    gold, hub = Path(sys.argv[1]), Path(sys.argv[2])
    texts = {k: [json.loads(l)["text"] for l in open(gold / f, encoding="utf-8") if l.strip()] for k, f in SETS.items()}
    for tool, (repo, max_words, overlap) in MODELS.items():
        snap = sorted(glob.glob(str(hub / repo / "snapshots" / "*")))[0]
        tok = AutoTokenizer.from_pretrained(snap)
        for key, docs in texts.items():
            n_win, longest, over = 0, (0, -1), {e: set() for e in EDGES}
            over_win = {e: 0 for e in EDGES}
            for i, t in enumerate(docs):
                for w in windows([m.group() for m in WORD.finditer(t)], max_words, overlap):
                    if not w:
                        continue
                    n = len(tok(w, is_split_into_words=True, add_special_tokens=False)["input_ids"])
                    n_win += 1
                    longest = max(longest, (n, i))
                    for e in EDGES:
                        if n > e:
                            over[e].add(i)
                            over_win[e] += 1
            print(json.dumps({"tool": tool, "set": key, "windows": n_win, "longest_tokens": longest[0], "longest_doc": longest[1],
                              "windows_over": over_win, "docs_over": {e: sorted(s)[:12] if len(s) <= 12 else len(s) for e, s in over.items()}}), flush=True)


if __name__ == "__main__":
    main()
