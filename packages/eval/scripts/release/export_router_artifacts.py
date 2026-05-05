#!/usr/bin/env python
"""Export distiluse encoder to ONNX + prototypes npz → JSON.

Outputs:
  - `release/v10-router/distiluse.onnx` (encoder + tokenizer)
  - `release/v10-router/distiluse-tokenizer.json`
  - `release/v10-router/distiluse-spm.model`
  - `release/v10-router/router-embeddings.json` (prototypes + domain order)

Run:
    python packages/eval/scripts/release/export_router_artifacts.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def export_distiluse(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = out_dir / "distiluse.onnx"
    tok_path = out_dir / "distiluse-tokenizer.json"
    if onnx_path.exists() and tok_path.exists():
        print(f"[skip] distiluse already exported", flush=True)
        return

    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    model_id = "sentence-transformers/distiluse-base-multilingual-cased-v2"
    print(f"[distiluse] loading {model_id}", flush=True)
    # Force CPU — torch.export.export tracer fails on MPS device
    # propagation for embedding ops.
    st = SentenceTransformer(model_id, device="cpu")
    transformer = st[0].auto_model.cpu()
    transformer.eval()

    # Tokenizer (saved to load via @anush008/tokenizers in TS).
    tok = AutoTokenizer.from_pretrained(model_id)
    tok.save_pretrained(str(out_dir))
    # Rename main tokenizer.json to a distiluse-specific name to avoid
    # collision when both GLiNER + distiluse tokenizers live in the same
    # cache dir.
    src = out_dir / "tokenizer.json"
    if src.exists():
        src.rename(tok_path)
    print(f"[distiluse] tokenizer → {tok_path}", flush=True)

    # ONNX export via legacy torchscript path (`dynamo=False`) — the
    # newer torch.export-based path fails MPS device propagation on
    # embedding ops. Inputs: input_ids, attention_mask. Output:
    # last_hidden_state.
    print(f"[distiluse] exporting ONNX → {onnx_path}", flush=True)
    dummy_input_ids = torch.zeros(1, 16, dtype=torch.long)
    dummy_attention_mask = torch.ones(1, 16, dtype=torch.long)
    torch.onnx.export(
        transformer,
        (dummy_input_ids, dummy_attention_mask),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "last_hidden_state": {0: "batch", 1: "seq"},
        },
        opset_version=19,
        do_constant_folding=True,
        dynamo=False,
    )
    print(f"[distiluse] done — {onnx_path}", flush=True)


def export_prototypes(npz_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "router-embeddings.json"
    if out_path.exists():
        print(f"[skip] prototypes already exported", flush=True)
        return

    print(f"[prototypes] loading {npz_path}", flush=True)
    npz = np.load(str(npz_path), allow_pickle=True)
    print(f"[prototypes] keys: {list(npz.keys())}", flush=True)

    # Schema (per `EmbeddingDomainRouter`):
    #   prototypes: (N_domains, D) float32, unit-norm
    #   domains: list[str] of length N_domains
    #   gate_margin (per-domain optional, e.g. enterprise = 0.10)
    payload: dict = {}
    if "prototypes" in npz:
        payload["prototypes"] = npz["prototypes"].astype(np.float32).tolist()
    if "domains" in npz:
        domains_raw = npz["domains"]
        if domains_raw.ndim == 0:
            payload["domains"] = list(domains_raw.item())
        else:
            payload["domains"] = [str(x) for x in domains_raw.tolist()]
    if "gates" in npz:
        gates_raw = npz["gates"]
        if gates_raw.ndim == 0:
            try:
                payload["gates"] = dict(gates_raw.item())
            except Exception:
                payload["gates"] = gates_raw.tolist()
        else:
            payload["gates"] = gates_raw.tolist()
    # Default enterprise gate (0.10) if not in npz.
    if "gates" not in payload and "domains" in payload and "enterprise" in payload["domains"]:
        payload["gates"] = {"enterprise": 0.10}
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[prototypes] wrote {out_path} (domains={payload.get('domains')})", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--prototypes", type=Path,
                    default=Path("packages/eval/v10-weights/router/router-embeddings.npz"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("packages/eval/results/release/v10-router"))
    args = ap.parse_args()

    export_distiluse(args.out_dir)
    export_prototypes(args.prototypes, args.out_dir)


if __name__ == "__main__":
    main()
