#!/usr/bin/env python
"""Merge ONE unified LoRA adapter into base GLiNER and export to ONNX.

The v0.2 unified full-OSS model track collapses the 5 per-domain
adapters + cosine router into a single model.
This is the single-adapter counterpart of `export_merged_lora_onnx.py`:
no per-domain loop, no router artifacts.

  1. Load base `urchade/gliner_multi_pii-v1` (PyTorch)
  2. Apply the unified LoRA via peft
  3. `merge_and_unload()` → merged weights in base
  4. `export_to_onnx()` → `model.onnx`
  5. (optional) dynamic INT8 → `model_int8.onnx`

Run:
    python packages/eval/scripts/release/export_unified_onnx.py \\
        --adapter-dir packages/eval/results/train/unified-smoke/run/adapter \\
        --out-dir packages/eval/results/release/onnx-unified
"""
from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_ADAPTER = Path("packages/eval/results/train/unified/adapter")
DEFAULT_OUT = Path("packages/eval/results/release/onnx-unified")
BASE_MODEL = "urchade/gliner_multi_pii-v1"


def export_unified(adapter_dir: Path, out_dir: Path, opset: int, quantize: bool) -> Path:
    from gliner import GLiNER
    from peft import PeftModel

    if not (adapter_dir / "adapter_config.json").is_file():
        raise FileNotFoundError(f"no adapter_config.json under {adapter_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    final_onnx = out_dir / "model.onnx"

    print(f"[unified] loading base {BASE_MODEL}", flush=True)
    base = GLiNER.from_pretrained(BASE_MODEL, local_files_only=False)

    print(f"[unified] loading + merging LoRA from {adapter_dir}", flush=True)
    inner = base.model.token_rep_layer.bert_layer.model
    merged_inner = PeftModel.from_pretrained(inner, str(adapter_dir)).merge_and_unload()
    base.model.token_rep_layer.bert_layer.model = merged_inner

    print(f"[unified] exporting merged ONNX → {out_dir}", flush=True)
    base.export_to_onnx(save_dir=str(out_dir), opset=opset)
    print(f"[unified] FP32 export done — {final_onnx}", flush=True)

    if quantize:
        final_int8 = out_dir / "model_int8.onnx"
        print(f"[unified] int8 dynamic quantizing → {final_int8}", flush=True)
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(
            model_input=str(final_onnx),
            model_output=str(final_int8),
            weight_type=QuantType.QInt8,
        )
        print(f"[unified] int8 done — {final_int8}", flush=True)

    return final_onnx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER,
                    help="dir holding adapter_config.json + adapter_model.safetensors")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--opset", type=int, default=19)
    ap.add_argument("--no-quantize", action="store_true", help="FP32 only")
    args = ap.parse_args()

    export_unified(args.adapter_dir, args.out_dir, args.opset, quantize=not args.no_quantize)


if __name__ == "__main__":
    main()
