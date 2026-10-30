# SPDX-License-Identifier: Apache-2.0
"""The texts nullpii runs on, as `{"dataset", "idx", "text"}` rows: the
frozen sets through bench_full.py's own loaders (which check each set's
SHA-256), so `idx` is the index every checkpoint and scorer uses."""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from pipeline import settings

Loader = Callable[[int | None], list]


def _bench_loaders() -> dict[str, Loader]:
    sys.path.insert(0, str(settings.SCRIPTS))
    import bench_full

    return {spec.key: spec.loader for spec in bench_full.DATASET_CONFIGS}


def rows(keys: Iterable[str], loaders: dict[str, Loader] | None = None) -> Iterator[dict]:
    """Every text of the datasets `keys`, in loader order."""
    loaders = _bench_loaders() if loaders is None else loaders
    for key in keys:
        if key not in loaders:
            raise KeyError(f"no dataset {key!r} in bench_full.py")
        for idx, sample in enumerate(loaders[key](None)):
            yield {"dataset": key, "idx": idx, "text": sample.text}


def write(keys: Iterable[str], out: Path, loaders: dict[str, Loader] | None = None) -> int:
    """Write the rows of `keys` to `out` as JSONL; returns how many. The
    file appears whole or not at all, so captures of several presets that
    write the same texts side by side never read a half-written one."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.name}.{os.getpid()}.partial")
    n = 0
    with partial.open("w", encoding="utf-8") as f:
        for row in rows(keys, loaders):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    os.replace(partial, out)
    return n
