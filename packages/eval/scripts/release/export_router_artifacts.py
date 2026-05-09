#!/usr/bin/env python
"""Export distiluse encoder to ONNX + prototypes npz → JSON.

Outputs:
  - `release/router/distiluse.onnx` (encoder + tokenizer)
  - `release/router/distiluse-tokenizer.json`
  - `release/router/distiluse-spm.model`
  - `release/router/router-embeddings.json` (prototypes + domain order)

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
    from torch import nn
    from transformers import AutoTokenizer

    model_id = "sentence-transformers/distiluse-base-multilingual-cased-v2"
    print(f"[distiluse] loading {model_id}", flush=True)
    # Force CPU — torch.export.export tracer fails on MPS device
    # propagation for embedding ops.
    st = SentenceTransformer(model_id, device="cpu")

    class FullDistiluseV2(nn.Module):
        """Full sentence-transformers distiluse-v2 pipeline as a single
        ONNX module: Transformer → mask-weighted mean pool → Dense
        (768→512) → Tanh → L2-normalise. Output: `[batch, 512]`
        sentence embedding ready for cosine routing.

        Earlier exports shipped only the bare `Transformer` and skipped
        the `Pooling` + `Dense` + `Tanh` modules, leaving the TS
        encoder to mean-pool 768-dim hidden states and compare against
        512-dim prototypes (different vector spaces). That bug rolled
        every input into the same mediocre cosine score and routed
        most traffic to whichever prototype happened to align with the
        first 512 hidden dims — typically `legal`.
        """

        def __init__(self, st_model: SentenceTransformer):
            super().__init__()
            self.transformer = st_model[0].auto_model
            self.dense = st_model[2].linear
            self.activation = st_model[2].activation_function

        def forward(self, input_ids, attention_mask):
            out = self.transformer(input_ids=input_ids, attention_mask=attention_mask)
            last = out.last_hidden_state  # [B, S, 768]
            mask = attention_mask.unsqueeze(-1).float()
            pooled = (last * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            proj = self.activation(self.dense(pooled))  # [B, 512]
            return proj / proj.norm(dim=-1, keepdim=True).clamp(min=1e-9)

    transformer = FullDistiluseV2(st).cpu()
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

    # Export the full pipeline (Transformer + Pooling + Dense + Tanh +
    # L2 norm) as a single ONNX graph so the TS runtime only feeds
    # `input_ids` + `attention_mask` and reads back a unit-norm
    # 512-dim sentence embedding.
    print(f"[distiluse] exporting ONNX → {onnx_path}", flush=True)
    dummy_input_ids = torch.zeros(1, 16, dtype=torch.long)
    dummy_attention_mask = torch.ones(1, 16, dtype=torch.long)
    torch.onnx.export(
        transformer,
        (dummy_input_ids, dummy_attention_mask),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["sentence_embedding"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "sentence_embedding": {0: "batch"},
        },
        opset_version=19,
        do_constant_folding=True,
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
    # npz uses "labels" key; JSON schema uses "domains"
    domain_key = "domains" if "domains" in npz else "labels"
    if domain_key in npz:
        domains_raw = npz[domain_key]
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
                    default=Path("packages/eval/weights/router/router-embeddings.npz"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("packages/eval/results/release/router"))
    args = ap.parse_args()

    export_distiluse(args.out_dir)
    export_prototypes(args.prototypes, args.out_dir)


if __name__ == "__main__":
    main()
