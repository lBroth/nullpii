#!/usr/bin/env python
"""Merge each per-domain LoRA adapter into base GLiNER and export to ONNX.

For each adapter under `packages/eval/v10-weights/adapters/<profile>/`:
  1. Load base `urchade/gliner_multi_pii-v1` (PyTorch)
  2. Apply LoRA via peft
  3. `model.merge_and_unload()` → merged weights in base
  4. `model.export_to_onnx()` → `model.onnx` in output dir

Outputs to `packages/eval/results/release/v10-onnx-merged/<profile>/`.

Run:
    python packages/eval/scripts/release/export_merged_lora_onnx.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_PROFILES = ["devops", "legal", "medical", "narrative", "enterprise"]


def export_one(profile: str, adapters_root: Path, out_root: Path, opset: int,
               quantize: bool = True) -> None:
    from gliner import GLiNER
    from peft import PeftModel

    # Adapter weights live directly under <adapters_root>/<profile>/.
    # (Older path was <adapters_root>/<profile>/adapter/; we no longer
    # ship the training-history checkpoint subdirs.)
    adapter_dir = adapters_root / profile
    if not adapter_dir.exists():
        print(f"[skip] {profile}: adapter not found at {adapter_dir}", flush=True)
        return

    out_dir = out_root / profile
    out_dir.mkdir(parents=True, exist_ok=True)
    final_onnx = out_dir / "model.onnx"
    final_q4 = out_dir / "model_q4.onnx"
    if final_onnx.exists() and (not quantize or final_q4.exists()):
        print(f"[skip] {profile}: already exported", flush=True)
        return

    print(f"\n[merge] {profile}: loading base gliner_multi_pii-v1", flush=True)
    base = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1", local_files_only=False)

    print(f"[merge] {profile}: loading + merging LoRA from {adapter_dir}", flush=True)
    inner = base.model.token_rep_layer.bert_layer.model
    peft_model = PeftModel.from_pretrained(inner, str(adapter_dir))
    merged_inner = peft_model.merge_and_unload()
    base.model.token_rep_layer.bert_layer.model = merged_inner

    if not final_onnx.exists():
        print(f"[merge] {profile}: exporting merged ONNX → {out_dir}", flush=True)
        base.export_to_onnx(save_dir=str(out_dir), opset=opset)
        print(f"[merge] {profile}: FP32 export done — {final_onnx}", flush=True)

    final_int8 = out_dir / "model_int8.onnx"
    if quantize and not final_int8.exists():
        # Dynamic INT8 quantization — same scheme as
        # `onnx-community/gliner_multi_pii-v1/onnx/model_int8.onnx`
        # (~333 MB vs Q4's 853 MB). Q4 only quantizes MatMul nodes, so
        # GLiNER's RNN + prompt_rep_layer + head stay FP32 → minimal
        # shrink. Dynamic INT8 covers everything → ~3.3× smaller.
        print(f"[merge] {profile}: int8 dynamic quantizing FP32 → {final_int8}", flush=True)
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(
            model_input=str(final_onnx),
            model_output=str(final_int8),
            weight_type=QuantType.QInt8,
        )
        print(f"[merge] {profile}: int8 done — {final_int8}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--adapters-root", type=Path,
                    default=Path("packages/eval/v10-weights/adapters"))
    ap.add_argument("--out-root", type=Path,
                    default=Path("packages/eval/results/release/v10-onnx-merged"))
    ap.add_argument("--profiles", nargs="+", default=DEFAULT_PROFILES,
                    help="Adapter profiles to merge (default: all 5)")
    ap.add_argument("--opset", type=int, default=19)
    ap.add_argument("--no-quantize", action="store_true",
                    help="Skip INT8 dynamic quantization (FP32 only)")
    args = ap.parse_args()

    args.out_root.mkdir(parents=True, exist_ok=True)
    quantize = not args.no_quantize
    for profile in args.profiles:
        try:
            export_one(profile, args.adapters_root, args.out_root, args.opset,
                       quantize=quantize)
        except Exception as e:
            print(f"[FAIL] {profile}: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            continue


if __name__ == "__main__":
    main()
