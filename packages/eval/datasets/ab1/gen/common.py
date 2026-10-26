# SPDX-License-Identifier: Apache-2.0
"""Shared constants, paths, seeds and RNG helpers for the AB-1 component A build."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
LISTS = ROOT / "lists"
DATA = ROOT / "data"

CANARY = "AB1-CANARY-6f3a1c9e-nullpii-agentbench-2026-10-23"

# Master seed of the whole build. Every random choice derives from it.
MASTER_SEED = 20261023

SWE_DATASET = "nebius/SWE-rebench-openhands-trajectories"
SWE_REVISION = "35455389ab51bf5e2306bfd436ef72d0f98bf882"
FB_DATASET = "OpenHands/openhands-feedback"
FB_REVISION = "facf45600d625510b98222ec584a8c9ac59272a2"

# Phase-A real non-English pools (cache/real/), selected by gen/real/wildchat_select.py and
# gen/real/gh_fetch.py; see README.md for the licences.
WILDCHAT_DATASET = "allenai/WildChat-1M"
WILDCHAT_REVISION = "7d6490e462285cf85d91eabea0f9a954fbddcd1f"
GH_ISSUES_DATASET = "github-issues"
GH_ISSUES_REVISION = "2026-10-24"  # the day gen/real/gh_fetch.py ran (the fetch date)
REAL_LANGS = ("it", "de", "fr", "es")

GITLEAKS_TAG = "v8.30.1"
GITLEAKS_COMMIT = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"

HF_CACHE = CACHE / "hf"
SWE_PARQUET = (HF_CACHE / "datasets--nebius--SWE-rebench-openhands-trajectories" / "snapshots"
               / SWE_REVISION / "trajectories.parquet")
FB_PARQUET = (HF_CACHE / "datasets--OpenHands--openhands-feedback" / "snapshots"
              / FB_REVISION / "data" / "train-00000-of-00001.parquet")

LANGS = ["en", "it", "de", "fr", "es"]
KINDS = ["prompt", "file", "shell", "log", "tool_json", "ticket"]

# Document counts per kind (SPEC.md: shares of 1,200; each kind split 1/6 dev, 5/6 test).
KIND_TOTAL = {"prompt": 240, "file": 240, "shell": 240, "log": 180, "tool_json": 120, "ticket": 180}
MULTILINGUAL_KINDS = ("prompt", "ticket")

EXCERPT_MIN = 300
EXCERPT_MAX = 6000

CLEAN_SHARE = 0.20
ENCODED_SHARE = 0.05


def derive_seed(*parts: object) -> int:
    """Stable 64-bit seed from the master seed and any labels."""
    h = hashlib.sha256(json.dumps([MASTER_SEED, *map(str, parts)]).encode()).hexdigest()
    return int(h[:16], 16)


def rng_for(*parts: object) -> random.Random:
    return random.Random(derive_seed(*parts))


def read_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def read_tsv(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        rows.append(line.split("\t"))
    return rows
