# SPDX-License-Identifier: Apache-2.0
"""Developer tool: render a few documents of given templates with a
development seed (never the release seed) and show tagged values inline.

usage: python devrun.py TEMPLATE_ID [TEMPLATE_ID ...] [--n N] [--show] [--mode MODE] [--lang LANG]
       python devrun.py --all [--n N]      (smoke-test every template in every mode/lang)
"""

from __future__ import annotations

import argparse
import sys

from tracegen.build import build_one
from tracegen.doc import Mode
from tracegen.templates import load_all

DEV_SEED = "dev-7"


def render_marked(bd) -> str:
    a = bd.assembled
    marks = [(s["start"], s["end"], "G:" + s["label"]) for s in a.spans]
    marks += [(r["start"], r["end"], "d:" + r["class"]) for r in a.regions]
    marks.sort()
    out, pos = [], 0
    for s, e, tag in marks:
        out.append(a.text[pos:s])
        out.append(f"⟪{tag}|{a.text[s:e]}⟫" if tag.startswith("G") else f"⟨{tag}|{a.text[s:e]}⟩")
        pos = e
    out.append(a.text[pos:])
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tids", nargs="*")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--mode", default=None)
    ap.add_argument("--lang", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    reg = load_all()
    tids = sorted(reg) if args.all else args.tids
    modes = [args.mode] if args.mode else [Mode.FULL, Mode.NO_SECRET, Mode.CLEAN]
    langs = [args.lang] if args.lang else ["en", "it", "de", "fr", "es"]
    bad = 0
    for tid in tids:
        tpl = reg[tid]
        lens = []
        golds = []
        for i in range(args.n):
            for mode in modes:
                for lang in langs:
                    try:
                        bd = build_one(tpl, f"dev-{i}", mode, lang, f"{DEV_SEED}:{tid}:{i}:{mode}:{lang}")
                    except Exception as e:  # report every failure, keep going
                        bad += 1
                        print(f"FAIL {tid} {mode} {lang} #{i}: {type(e).__name__}: {e}", file=sys.stderr)
                        continue
                    lens.append(len(bd.assembled.text))
                    golds.append(len(bd.assembled.spans))
                    if args.show:
                        print(f"===== {tid} mode={mode} lang={lang} #{i} len={len(bd.assembled.text)} "
                              f"gold={len(bd.assembled.spans)} distr={len(bd.assembled.regions)}")
                        print(render_marked(bd))
        if lens:
            print(f"{tid:32s} n={len(lens):3d} len min/med/max={min(lens)}/{sorted(lens)[len(lens)//2]}/{max(lens)} "
                  f"gold med={sorted(golds)[len(golds)//2]} max={max(golds)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
