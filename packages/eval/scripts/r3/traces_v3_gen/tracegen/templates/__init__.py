# SPDX-License-Identifier: Apache-2.0
"""Template registry. Each template is a function (d: Doc) -> None that
emits one transcript through d.user / d.agent / d.tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DOC_TYPES = ("file", "shell", "git", "trace", "log", "http", "ticket")


@dataclass(frozen=True)
class Template:
    tid: str
    style: str
    types: tuple
    fn: Callable


REGISTRY: dict[str, Template] = {}


def template(tid: str, style: str, *types: str):
    for t in types:
        if t not in DOC_TYPES:
            raise ValueError(f"unknown doc type {t}")

    def deco(fn: Callable) -> Callable:
        if tid in REGISTRY:
            raise ValueError(f"duplicate template id {tid}")
        REGISTRY[tid] = Template(tid, style, tuple(types), fn)
        return fn

    return deco


def load_all() -> dict[str, Template]:
    import importlib
    import pkgutil

    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if m.name.startswith("t_"):
            importlib.import_module(f"{__name__}.{m.name}")
    return REGISTRY
