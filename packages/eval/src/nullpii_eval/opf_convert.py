# SPDX-License-Identifier: Apache-2.0
"""Convert a transformers-format `openai/privacy-filter` fine-tune to the
native `opf` checkpoint layout, so the official `opf` runtime (constrained
Viterbi decoder, windowing, whitespace trim) can serve it unchanged.

Fine-tunes trained with `opf train` are often published only in the
transformers layout (`OpenAIPrivacyFilterForTokenClassification`), while
`opf` reads its own layout (`original/` in `openai/privacy-filter`). The
two differ only by tensor names and by q/k/v being one fused matrix:
`verify_against_base` checks that claim tensor-for-tensor on the base
model, which ships both layouts, before any fine-tune is converted.

The output config is what `opf train` itself writes (`_train/runner.py`):
the base opf config plus `param_dtype`, `num_labels`, `category_version`,
`span_class_names` and `ner_class_names`, taken from the fine-tune's
`opf_metadata` block.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

BASE_REPO = "openai/privacy-filter"
BASE_REVISION = "7ffa9a043d54d1be65afb281eddf0ffbe629385b"
_BASE_OPF_SUBDIR = "original"
_WEIGHTS_FILE = "model.safetensors"
_CONFIG_FILE = "config.json"
_CALIBRATION_FILE = "viterbi_calibration.json"
_HF_LAYER_PREFIX = "model.layers."
# HF tensors that map one-to-one onto an opf tensor, per layer.
_LAYER_RENAMES = {
    "input_layernorm.weight": "attn.norm.scale",
    "self_attn.o_proj.weight": "attn.out.weight",
    "self_attn.o_proj.bias": "attn.out.bias",
    "post_attention_layernorm.weight": "mlp.norm.scale",
    "mlp.router.weight": "mlp.gate.weight",
    "mlp.router.bias": "mlp.gate.bias",
    "mlp.experts.gate_up_proj": "mlp.swiglu.weight",
    "mlp.experts.gate_up_proj_bias": "mlp.swiglu.bias",
    "mlp.experts.down_proj": "mlp.out.weight",
    "mlp.experts.down_proj_bias": "mlp.out.bias",
}
_GLOBAL_RENAMES = {
    "model.embed_tokens.weight": "embedding.weight",
    "model.norm.weight": "norm.scale",
    "score.weight": "unembedding.weight",
}
# opf's unembedding has no bias; the HF head does. Conversion is exact
# only when that bias is zero, which `opf train` output always is.
_HF_ONLY_ZERO = "score.bias"
_FUSED_QKV = ("q_proj", "k_proj", "v_proj")
# Attention sinks: opf's softmax works in base 2, transformers' in base e,
# so the HF export stores opf_sinks * ln(2) (checked bit-exact in that
# direction). The inverse division is exact to 1 float32 ulp, not bitwise,
# hence the tolerance used for this tensor only.
_HF_SINKS = "self_attn.sinks"
_OPF_SINKS = "attn.sinks"
_SINKS_RTOL = 1e-6
_OPF_TRAIN_FIELDS = ("category_version", "span_class_names", "ner_class_names")
_SAFETENSORS_DTYPES = {"BF16": "bfloat16", "F32": "float32", "F16": "float16"}


def hf_to_opf_tensors(hf_path: Path) -> dict:
    """Map a transformers privacy-filter state dict onto opf names."""
    import torch
    from safetensors import safe_open

    out: dict = {}
    with safe_open(str(hf_path), "pt") as f:
        keys = set(f.keys())
        bias = f.get_tensor(_HF_ONLY_ZERO)
        if torch.count_nonzero(bias).item() != 0:
            raise ValueError(f"{hf_path}: {_HF_ONLY_ZERO} is non-zero; opf has no head bias")
        for hf_name, opf_name in _GLOBAL_RENAMES.items():
            out[opf_name] = f.get_tensor(hf_name)
        for layer in _layer_indices(keys):
            out.update(_convert_layer(f, layer))
    per_layer = len(_LAYER_RENAMES) + 1 + 2 * len(_FUSED_QKV)
    expected = len(_GLOBAL_RENAMES) + 1 + len(_layer_indices(keys)) * per_layer
    if len(keys) != expected:
        raise ValueError(f"{hf_path}: {len(keys)} tensors, expected {expected}; unknown layout")
    return out


def _layer_indices(keys: set[str]) -> list[int]:
    return sorted({int(k[len(_HF_LAYER_PREFIX):].split(".", 1)[0]) for k in keys if k.startswith(_HF_LAYER_PREFIX)})


def _convert_layer(f, layer: int) -> dict:
    import math

    import torch

    hf = f"{_HF_LAYER_PREFIX}{layer}."
    opf = f"block.{layer}."
    out = {opf + dst: f.get_tensor(hf + src) for src, dst in _LAYER_RENAMES.items()}
    # opf keeps sinks in float32 whatever the export dtype (bf16 here).
    out[opf + _OPF_SINKS] = f.get_tensor(hf + _HF_SINKS).float() / math.log(2)
    for kind in ("weight", "bias"):
        parts = [f.get_tensor(f"{hf}self_attn.{p}.{kind}") for p in _FUSED_QKV]
        out[f"{opf}attn.qkv.{kind}"] = torch.cat(parts, dim=0)
    return out


def verify_against_base(base_dir: Path) -> int:
    """Convert the base model's HF layout and require bit-equality with its
    own opf layout (1-ulp tolerance on the attention sinks only). Returns
    the number of tensors checked."""
    import torch
    from safetensors import safe_open

    converted = hf_to_opf_tensors(base_dir / _WEIGHTS_FILE)
    with safe_open(str(base_dir / _BASE_OPF_SUBDIR / _WEIGHTS_FILE), "pt") as f:
        reference = set(f.keys())
        if reference != set(converted):
            raise ValueError(f"tensor names differ: {sorted(reference ^ set(converted))[:5]}")
        for name in sorted(reference):
            ref = f.get_tensor(name)
            got = converted[name]
            if name.endswith(_OPF_SINKS):
                same = torch.allclose(ref, got, rtol=_SINKS_RTOL, atol=0.0)
            else:
                same = torch.equal(ref, got)
            if ref.dtype != got.dtype or not same:
                raise ValueError(f"conversion mismatch on {name}")
    return len(reference)


def check_same_architecture(tensors: dict, base_dir: Path) -> None:
    """A fine-tune must match the base tensor-for-tensor in name, dtype and
    shape; only the label head may change its output width."""
    from safetensors import safe_open

    with safe_open(str(base_dir / _BASE_OPF_SUBDIR / _WEIGHTS_FILE), "pt") as f:
        if set(f.keys()) != set(tensors):
            raise ValueError("fine-tune tensor names differ from the base opf layout")
        for name in f.keys():
            ref = f.get_slice(name)
            got = tensors[name]
            same_shape = list(got.shape) == ref.get_shape()
            is_head = name == _GLOBAL_RENAMES["score.weight"]
            head_ok = is_head and list(got.shape[1:]) == ref.get_shape()[1:]
            same_dtype = str(got.dtype).removeprefix("torch.") == _SAFETENSORS_DTYPES[ref.get_dtype()]
            if not (same_shape or head_ok) or not same_dtype:
                raise ValueError(f"fine-tune tensor {name} differs from the base in shape or dtype")


def opf_config_for(hf_config: dict, base_opf_config: dict) -> dict:
    """Rebuild the config `opf train` writes for a fine-tune of the base."""
    meta = hf_config.get("opf_metadata")
    if not isinstance(meta, dict):
        raise ValueError("fine-tune config has no opf_metadata block; not an opf fine-tune")
    if meta.get("encoding") != base_opf_config.get("encoding"):
        raise ValueError("fine-tune tokenizer encoding differs from the base")
    out = dict(base_opf_config)
    out["num_labels"] = len(meta["ner_class_names"])
    for field in _OPF_TRAIN_FIELDS:
        out[field] = meta[field]
    if int(hf_config["num_labels"]) != out["num_labels"]:
        raise ValueError("num_labels disagrees with opf_metadata.ner_class_names")
    return out


def ensure_opf_checkpoint(repo_id: str, revision: str, cache_root: Path) -> Path:
    """Return an opf checkpoint dir for `repo_id@revision`, converting once.

    The base model is verified first, so a layout change upstream fails
    loudly instead of producing a silently wrong model.
    """
    from huggingface_hub import snapshot_download

    target = cache_root / f"{repo_id.replace('/', '--')}--{revision}"
    if (target / _WEIGHTS_FILE).is_file() and (target / _CONFIG_FILE).is_file():
        return target
    from safetensors.torch import save_file

    base_dir = Path(snapshot_download(BASE_REPO, revision=BASE_REVISION))
    verify_against_base(base_dir)
    fine_dir = Path(snapshot_download(repo_id, revision=revision))
    hf_config = json.loads((fine_dir / _CONFIG_FILE).read_text(encoding="utf-8"))
    base_config = json.loads((base_dir / _BASE_OPF_SUBDIR / _CONFIG_FILE).read_text(encoding="utf-8"))
    tensors = hf_to_opf_tensors(fine_dir / _WEIGHTS_FILE)
    check_same_architecture(tensors, base_dir)
    staging = target.with_name(target.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    save_file({k: v.contiguous() for k, v in tensors.items()}, str(staging / _WEIGHTS_FILE))
    config = opf_config_for(hf_config, base_config)
    (staging / _CONFIG_FILE).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The base calibration is the all-zero operating point (no transition
    # bias); copying it keeps the decoder identical to the base row's.
    shutil.copy(base_dir / _BASE_OPF_SUBDIR / _CALIBRATION_FILE, staging / _CALIBRATION_FILE)
    staging.rename(target)
    return target
