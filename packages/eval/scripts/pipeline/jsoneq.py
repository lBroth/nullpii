# SPDX-License-Identifier: Apache-2.0
"""Where two parsed JSON values differ, path by path."""
from __future__ import annotations

# Scores are recomputed from the same inputs by the same code, so they
# match to the last bit; this absorbs float formatting only.
FLOAT_TOLERANCE = 1e-12


def differences(a: object, b: object, path: str = "") -> list[str]:
    """Every path at which `a` and `b` differ: a key or an item one of them
    lacks, a type, or a value (floats within FLOAT_TOLERANCE are equal)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return _dict_differences(a, b, path)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path or '/'}: {len(a)} items against {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    if _is_number(a) and _is_number(b) and (isinstance(a, float) or isinstance(b, float)):
        return [] if abs(a - b) <= FLOAT_TOLERANCE else [f"{path or '/'}: {a!r} against {b!r}"]
    return [] if a == b and type(a) is type(b) else [f"{path or '/'}: {a!r} against {b!r}"]


def _dict_differences(a: dict, b: dict, path: str) -> list[str]:
    out: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in b:
            out.append(f"{path}/{key}: only in the first")
        elif key not in a:
            out.append(f"{path}/{key}: only in the second")
        else:
            out += differences(a[key], b[key], f"{path}/{key}")
    return out


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
