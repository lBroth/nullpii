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

# The frozen datasets and every tool's predictions of the published 0.5
# run, private (it holds real secrets and data that may not be passed on).
FROZEN_REPO = "lBroth/nullpii-bench-private"
FROZEN_REVISION = "eadb7b382e3bad85cf8f7b54ca24c1f19642b95f"
MANIFEST = "MANIFEST.json"
# The SHA-256 of MANIFEST.json at FROZEN_REVISION. A copy is checked
# against its manifest, so pinning the manifest binds every file of the
# copy to the pinned revision, wherever the copy came from.
FROZEN_MANIFEST_SHA256 = "b53c4708bff6e1bc4e4265e014e93fc8876ca9ff585f464d191fb5d610cd424c"
# Files of the frozen repository that the manifest does not list.
UNLISTED = frozenset({MANIFEST, "README.md", ".gitattributes"})
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

# Bonferroni over the 15 other tools at a 5% family-wise level, written to
# four decimals as the published run passed it (99.6667).
BONFERRONI_COMPARISONS = 15
FAMILY_ALPHA = 0.05
BONFERRONI_DECIMALS = 4


def bonferroni_level() -> float:
    """The confidence level, in percent, of the Bonferroni-corrected CIs."""
    return round(100 * (1 - FAMILY_ALPHA / BONFERRONI_COMPARISONS), BONFERRONI_DECIMALS)


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
