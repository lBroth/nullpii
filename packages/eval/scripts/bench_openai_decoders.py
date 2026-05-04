"""Bench openai/privacy-filter with HF naive aggregation vs Python BIOES decoder.

Both paths run on the same loaded model; only the decoder differs. F1
computed via partial-match IoU >= 0.5. CPU-friendly (Mac M-series).

Output: matrix.json with one row per dataset, columns
{openai-pipeline, openai-bioes}.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "eval" / "scripts" / "train"))

from nullpii_eval import metrics, public_datasets  # noqa: E402
from nullpii_eval.datasets import Span as MetricSpan  # noqa: E402
from qualitative_compare import _strip_bioes  # noqa: E402

_OK = {"ACCOUNT_NUMBER", "PRIVATE_ADDRESS", "PRIVATE_DATE", "PRIVATE_EMAIL",
       "PRIVATE_PERSON", "PRIVATE_PHONE", "PRIVATE_URL", "SECRET"}


def predict_pipeline(pipe, text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for e in pipe(text):
        lab = _strip_bioes(str(e.get("entity_group") or "").upper())
        if lab not in _OK:
            continue
        out.append((lab.lower(), int(e.get("start", 0)), int(e.get("end", 0))))
    return out


def predict_bioes(model, tok, text: str, device: str) -> list[tuple[str, int, int]]:
    import torch
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              truncation=True, max_length=4096)
    offsets = enc.pop("offset_mapping").squeeze(0).tolist()
    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**enc).logits.argmax(dim=-1).squeeze(0).tolist()
    id2lab = model.config.id2label

    out: list[tuple[str, int, int]] = []
    cur_label: str | None = None
    cur_start: int | None = None
    cur_end: int | None = None

    def _close():
        nonlocal cur_label, cur_start, cur_end
        if cur_label is not None and cur_start is not None and cur_end is not None and cur_end > cur_start:
            out.append((cur_label.lower(), cur_start, cur_end))
        cur_label = cur_start = cur_end = None

    for tok_id, (st, en) in zip(logits, offsets):
        if st == en == 0:
            _close()
            continue
        lab = id2lab[tok_id]
        if lab == "O":
            _close()
            continue
        prefix, _, cat = lab.partition("-")
        if prefix == "S":
            _close()
            out.append((cat.lower(), st, en))
        elif prefix == "B":
            _close()
            cur_label, cur_start, cur_end = cat, st, en
        elif prefix in ("I", "E"):
            if cur_label == cat:
                cur_end = en
                if prefix == "E":
                    _close()
            else:
                _close()
    _close()
    return out


def to_metric(spans):
    return [MetricSpan(label=l, start=s, end=e) for l, s, e in spans]


def f1(samples, predict_fn) -> tuple[dict, float]:
    t0 = time.perf_counter()
    truths = [list(s.spans) for s in samples]
    preds = [to_metric(predict_fn(s.text)) for s in samples]
    cells = metrics.evaluate(preds, truths, policy="partial", iou_threshold=0.5)
    tp = sum(c.tp for c in cells.values())
    fp = sum(c.fp for c in cells.values())
    fn = sum(c.fn for c in cells.values())
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return ({"f1": 2 * p * r / (p + r) if (p + r) else 0.0,
             "precision": p, "recall": r,
             "n": len(samples)},
            time.perf_counter() - t0)


def _load_nullpii_bench(n: int | None) -> list:
    from nullpii_eval.datasets import Sample, Span
    path = ROOT / "packages" / "eval" / "datasets" / "nullpii-bench.jsonl"
    out: list = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["subset"] not in ("bundled", "long-prompts"):
                continue
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cap", type=int, default=200)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    print(f"[bench] device={args.device} cap={args.cap}")

    print("[load] openai/privacy-filter (HF pipeline + raw model)…")
    from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
    pipe = pipeline(
        task="token-classification",
        model="openai/privacy-filter",
        aggregation_strategy="simple",
        device=0 if args.device == "cuda" else -1,
        trust_remote_code=True,
    )
    tok = AutoTokenizer.from_pretrained("openai/privacy-filter", trust_remote_code=True)
    model = AutoModelForTokenClassification.from_pretrained(
        "openai/privacy-filter", trust_remote_code=True,
    ).to(args.device).eval()
    print()

    DATASETS = [
        ("nullpii-bench", lambda: _load_nullpii_bench(None)),
        ("ai4privacy-300k",
         lambda: list(public_datasets.load("ai4privacy/pii-masking-300k", max_samples=args.cap).samples)),
        ("isotonic-en",
         lambda: list(public_datasets.load("isotonic/pii-masking-200k", max_samples=args.cap, locale="en").samples)),
        ("isotonic-de",
         lambda: list(public_datasets.load("isotonic/pii-masking-200k", max_samples=args.cap, locale="de").samples)),
        ("isotonic-fr",
         lambda: list(public_datasets.load("isotonic/pii-masking-200k", max_samples=args.cap, locale="fr").samples)),
        ("isotonic-it",
         lambda: list(public_datasets.load("isotonic/pii-masking-200k", max_samples=args.cap, locale="it").samples)),
    ]

    matrix: dict = {}
    for name, loader in DATASETS:
        samples = loader()
        if not samples:
            continue
        print(f"[ds] {name} (n={len(samples)})")

        r_pipe, t_pipe = f1(samples, lambda t: predict_pipeline(pipe, t))
        print(f"  pipeline (HF naive)  F1={r_pipe['f1']:.3f} P={r_pipe['precision']:.3f} R={r_pipe['recall']:.3f} ({t_pipe:.1f}s)")

        r_bioes, t_bioes = f1(samples, lambda t: predict_bioes(model, tok, t, args.device))
        print(f"  bioes (Python)       F1={r_bioes['f1']:.3f} P={r_bioes['precision']:.3f} R={r_bioes['recall']:.3f} ({t_bioes:.1f}s)")

        delta = r_bioes["f1"] - r_pipe["f1"]
        print(f"  Δ                    {delta:+.3f}")
        print()

        matrix[name] = {
            "openai-pipeline": {**r_pipe, "wall_s": t_pipe},
            "openai-bioes": {**r_bioes, "wall_s": t_bioes},
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(matrix, indent=2))
    print(f"[bench] wrote {args.out}")


if __name__ == "__main__":
    main()
