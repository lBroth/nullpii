# SPDX-License-Identifier: Apache-2.0
"""Check the token-capped `_gliner_windows` against the word-only one on AB-1's texts.

Every document whose old windows stay within the cap must get identical windows; every
window must fit the cap (a single unsplittable piece excepted); every word character must
be in some window. Counts and document indices only.

  python check_windows.py <kit src> <gold dir> <hf hub dir>
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from transformers import AutoTokenizer

sys.path.insert(0, sys.argv[1])
from nullpii_eval import adapters as ad  # noqa: E402

SETS = {"ab1-a": "ab1-test.jsonl", "ab1-b1": "b1.jsonl", "ab1-b2": "b2.jsonl"}
MODELS = {
    "gliner-pii-large-v1": ("models--knowledgator--gliner-pii-large-v1.0", 768, 100),
    "gliner-stream-pii": ("models--knowledgator--gliner-stream-pii-v1.0", 2048, 12),
    "nemotron-pii-raw": ("models--nvidia--gliner-PII", 384, 12),
    "gliner-onnx-pii-fp32": ("models--onnx-community--gliner_multi_pii-v1", 384, 12),
}


def old_windows(text, max_words, overlap):
    words = [(m.start(), m.end()) for m in ad._GLINER_WORD.finditer(text)]
    if len(words) <= max_words:
        return [(0, text)]
    stride = max_words - overlap
    out = []
    for i in range(0, len(words), stride):
        s, e = words[i][0], words[min(i + max_words, len(words)) - 1][1]
        out.append((s, text[s:e]))
        if i + max_words >= len(words):
            return out
    return out


def main() -> None:
    gold, hub = Path(sys.argv[2]), Path(sys.argv[3])
    texts = {k: [json.loads(l)["text"] for l in open(gold / f, encoding="utf-8") if l.strip()] for k, f in SETS.items()}
    fail = 0
    for tool, (repo, max_words, overlap) in MODELS.items():
        tok = AutoTokenizer.from_pretrained(sorted(glob.glob(str(hub / repo / "snapshots" / "*")))[0])

        def count(pieces):
            return [len(ids) for ids in tok(pieces, add_special_tokens=False)["input_ids"]]

        for key, docs in texts.items():
            changed, over_cap, uncovered, longest = [], 0, 0, 0
            for i, t in enumerate(docs):
                new = ad._gliner_windows(t, max_words, overlap, count)
                old = old_windows(t, max_words, overlap)
                old_max = max(sum(count([m.group() for m in ad._GLINER_WORD.finditer(c)]) or [0]) for _, c in old)
                if new != old:
                    changed.append(i)
                    if old_max <= ad._GLINER_WINDOW_TOKENS:
                        fail += 1
                        print(json.dumps({"FAIL": "changed below cap", "tool": tool, "set": key, "doc": i}))
                covered = [False] * len(t)
                for off, c in new:
                    n = sum(count([m.group() for m in ad._GLINER_WORD.finditer(c)]) or [0])
                    longest = max(longest, n)
                    if n > ad._GLINER_WINDOW_TOKENS and len(c) > 1:
                        over_cap += 1
                    if t[off:off + len(c)] != c:
                        fail += 1
                        print(json.dumps({"FAIL": "offset", "tool": tool, "set": key, "doc": i}))
                    for p in range(off, off + len(c)):
                        covered[p] = True
                uncovered += sum(1 for p, ch in enumerate(t) if not ch.isspace() and not covered[p])
            print(json.dumps({"tool": tool, "set": key, "docs_changed": len(changed), "changed": changed[:20],
                              "windows_over_cap": over_cap, "longest_tokens": longest, "uncovered_chars": uncovered}), flush=True)
            fail += over_cap + uncovered
    print("CHECK", "FAIL" if fail else "PASS", fail)


if __name__ == "__main__":
    main()
