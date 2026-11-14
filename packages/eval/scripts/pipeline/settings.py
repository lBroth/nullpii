# SPDX-License-Identifier: Apache-2.0
"""What the pipeline runs on: where the frozen inputs live, which nullpii
configurations it measures, and the scripts it drives."""
from __future__ import annotations

import json
from pathlib import Path

EVAL = Path(__file__).resolve().parents[2]
SCRIPTS = EVAL / "scripts"
# Where bench_full.py's loaders read the frozen sets from (`fetch` links
# them there; the loaders check each set's SHA-256).
RESULTS = EVAL / "results"
PUBLISHED = EVAL / "published-bench"

# The frozen datasets, every tool's predictions of the published 0.5 run
# and that run's scoring outputs, private (it holds real secrets and data
# that may not be passed on). Revision d6300af added `published-0.5/` to
# eadb7b38 and changed nothing else but the manifest.
FROZEN_REPO = "lBroth/nullpii-bench-private"
FROZEN_REVISION = "d6300af293aa49b25e62209c5206faccc6191ce8"
MANIFEST = "MANIFEST.json"
# The SHA-256 of MANIFEST.json at FROZEN_REVISION. A copy is checked
# against its manifest, so pinning the manifest binds every file of the
# copy to the pinned revision, wherever the copy came from.
FROZEN_MANIFEST_SHA256 = "7b12cd16747756834c0a6dbdff1a0dcec6cda67d107f17dfcd6596c951d3cf1e"
# Files of the frozen repository that the manifest does not list.
UNLISTED = frozenset({MANIFEST, "README.md", ".gitattributes"})
# The published 0.5 run's AB-1 and PIIMB outputs, as `score` lays its own
# out (`ab1/`, `piimb/`), in the frozen copy: `reproduce` checks the frozen
# predictions give them, and `reference` lays them out for a first
# `compare`. They were in published-bench/ until a run of the pipeline
# took their place there.
PUBLISHED_RUN_OUTPUTS = "published-0.5"
# The folder huggingface_hub keeps its download metadata in, inside the
# copy: not a frozen file.
DOWNLOAD_METADATA = (".cache", "huggingface")

# The configurations nullpii is published in: what a user gets without
# configuring anything, and every category masked.
PRESETS: dict[str, dict] = {
    "default": {},
    "everything": {"disabledCategories": []},
}
NULLPII_PREFIX = "nullpii"


def tool_name(preset: str) -> str:
    """The checkpoint tool name of nullpii in `preset`."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}: one of {', '.join(PRESETS)}")
    return f"{NULLPII_PREFIX}-{preset}"


def preset_config(preset: str) -> str:
    """The engine options of `preset`, as score_capture.mjs takes them."""
    tool_name(preset)
    return json.dumps(PRESETS[preset], separators=(",", ":"))


BASELINE = tool_name("default")
OTHER_NULLPII = tuple(tool_name(p) for p in PRESETS if tool_name(p) != BASELINE)

# AB-1: the dataset key each scorer takes, and its frozen gold file.
AB1_GOLD = {"ab1-a": "ab1-test.jsonl", "ab1-b1": "b1.jsonl", "ab1-b2": "b2.jsonl"}
# AB-1: the gold kind each set's secrets are split by (`kind_split.py`):
# B1 inherits CredData's categories, and CredData counts UUIDs as
# credentials, which AB-1's specification lists as text to keep.
AB1_KIND_SPLITS = {"ab1-b1": "UUID"}
# R3: the gated sets the comparisons are made on, and the reported ones.
R3_GATED = ("r3-redact", "r3-tonic-human", "r3-piilo", "r3-eu-clinical", "r3-traces-v3")
R3_REPORTED = ("r3-redactionbench", "r3-mama-deid-val", "r3-traces-v3-nodistract")
R3_PREFIX = "r3-"
PIIMB_SENTENCES = "test_sentences.jsonl"
# PIIMB's six tasks, the `dataset` of each PIIMB row nullpii writes.
PIIMB_TASKS = frozenset({"ai4privacy-en", "ai4privacy-multi", "gretel", "mapa-eur-lex", "nemotron-pii", "privy"})
# Every label a nullpii span can carry: PII_LABELS of src/types/labels.ts
# but its 'O' (a test checks the two agree). A capture whose spans carry
# another label is refused before it is uploaded.
SPAN_LABELS = frozenset({
    "account_number", "private_address", "private_date", "private_demographic", "private_driver_license",
    "private_email", "private_geolocation", "private_ip", "private_mac", "private_occupation", "private_organization",
    "private_passport", "private_person", "private_phone", "private_sensitive", "private_title", "private_url",
    "private_vehicle_id", "secret",
})


def set_names() -> frozenset[str]:
    """Every name a capture's rows may give their set: AB-1's and R3's
    sets, PIIMB's tasks."""
    return frozenset({*AB1_GOLD, *R3_GATED, *R3_REPORTED, *PIIMB_TASKS})

# Bonferroni over the 15 other tools at a 5% family-wise level, written to
# four decimals as the published run passed it (99.6667).
BONFERRONI_COMPARISONS = 15
FAMILY_ALPHA = 0.05
BONFERRONI_DECIMALS = 4


def bonferroni_level() -> float:
    """The confidence level, in percent, of the Bonferroni-corrected CIs."""
    return round(100 * (1 - FAMILY_ALPHA / BONFERRONI_COMPARISONS), BONFERRONI_DECIMALS)


# What the published 0.5 run measured: nullpii 0.5's release build with the
# weights the library still pins, on CUDA. A run of the pipeline records
# its own (MEASURED.json); its captures run on the CPU.
PUBLISHED_MODEL = "lBroth/nullpii@5dd3c7991483c3b1bccb68beba53890d24cbd2d3"
PUBLISHED_MEASURED = {"nullpii": "0.5", "model": PUBLISHED_MODEL, "backend": "cuda"}
CAPTURE_BACKEND = "cpu"

# The names nullpii's rows had in the published run, which `reproduce`
# scores again to check that the scorers still give the published numbers.
PUBLISHED_AB1_BASELINE = "nullpii-H3b-cuda-agent"
PUBLISHED_R3_BASELINE = "nullpii-rel-cuda-core"
PUBLISHED_R3_OTHER_NULLPII = (
    "nullpii-rel-cuda-default",
    "nullpii-rel-cuda-default@core",
    "nullpii-H3b-A11-cuda-core",
    "nullpii-H3b-A11-cuda-default",
)
# The published run's reports on every category masked scored on core
# labels only (`nullpii-rel-cuda-default@core`), a configuration no longer
# measured: `reproduce` checks them, `score` does not write them.
PUBLISHED_R3_CORE_LABELS_BASELINE = "nullpii-rel-cuda-default@core"

# Comparing the first run with the published outputs, like for like only
# (owner, 2026-10-29: nullpii is published as `default` and `everything`
# from now on):
# - the published rows that are a configuration measured now, read under
#   its name: the 0.5 agent default on AB-1 is `default`, every category
#   masked on R3 (all its spans) is `everything`;
PUBLISHED_ALIASES = {
    PUBLISHED_AB1_BASELINE: tool_name("default"),
    "nullpii-rel-cuda-default": tool_name("everything"),
}
# - the published core regime (R3's headline row, and every category masked
#   scored on core labels only) is no longer published: its rows, the
#   intervals and verdicts against it, and its own reports are reported as
#   dropped, never as better or worse than anything measured now;
PUBLISHED_CORE_REGIME = frozenset({PUBLISHED_R3_BASELINE, PUBLISHED_R3_CORE_LABELS_BASELINE})
# - earlier rows the published run scored but the docs never printed.
PUBLISHED_UNPRINTED = frozenset({"nullpii-H3b-A11-cuda-core", "nullpii-H3b-A11-cuda-default"})
# The R3 verdicts were published against the core regime's row.
PUBLISHED_VERDICT_BASELINE = PUBLISHED_R3_BASELINE
# PIIMB was published with every category masked only, so a reference of
# the published outputs has no PIIMB report of the default.
PIIMB_PUBLISHED_PRESET = "everything"
PUBLISHED_ABSENT = frozenset({f"piimb/piimb-{p}.json" for p in PRESETS if p != PIIMB_PUBLISHED_PRESET})
# The PIIMB task from nullpii's own training family: the docs also give the
# average and the place without it.
PIIMB_TRAINING_FAMILY_TASK = "nemotron-pii"

NODE = "node"
SCORE_CAPTURE = SCRIPTS / "ab" / "score_capture.mjs"
RECOGNIZER_SPANS = SCRIPTS / "ab1" / "recognizer_spans.mjs"
ROUNDTRIP = SCRIPTS / "ab1" / "roundtrip.mjs"
AGENT_METRICS = SCRIPTS / "ab1" / "agent_metrics.py"
SECRET_COVERAGE = SCRIPTS / "ab1" / "secret_coverage.py"
KIND_SPLIT = SCRIPTS / "ab1" / "kind_split.py"
CHAR_METRICS = SCRIPTS / "ab" / "char_metrics.py"
R2_VERDICT = SCRIPTS / "ab" / "r2_verdict.py"
PIIMB_SCORE = SCRIPTS / "ab" / "piimb_score.py"
