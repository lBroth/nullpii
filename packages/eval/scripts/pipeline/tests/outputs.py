# SPDX-License-Identifier: Apache-2.0
"""A complete set of a run's outputs, small and made up, for the tests of
`compare` and the CLI: every file `score` writes, every preset's rows."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pipeline import compare, recipe, settings

DEFAULT, EVERYTHING = settings.tool_name("default"), settings.tool_name("everything")
# The published core row's per-set recalls on the gated sets: their mean
# is 0.95772, printed 0.958.
GATED_RECALLS = (0.97486, 0.98699, 0.96446, 0.96096, 0.90133)

Files = dict[str, dict | str]


def ab1_row(leak=0.0945, keep=0.8545, ci=None):
    return {
        "leak_rate": leak, "keep_rate": keep, "docs_with_leak": 0.27, "clean_docs_masked": 0.611,
        "outside_per_1k": 10.87, "encoded_leak_rate": None, "json_parse_rate": 0.912,
        "diff_consistent_rate": 1.0, "leak_by_category": {"email": [0.0, 536]}, "keep_by_kind": {"date": [0.9, 727]},
        "ci": ci or {"leak": [0.08, 0.1], "keep": [0.84, 0.87]},
    }


def against(leak_ci=(-0.3, -0.2), keep_ci=(0.1, 0.2), **row):
    """A row with paired intervals of the baseline minus it."""
    return ab1_row(ci={"baseline_minus_tool_leak": list(leak_ci), "baseline_minus_tool_keep": list(keep_ci)}, **row)


# A cell's paired intervals of the baseline minus a tool, per set: nullpii
# ahead on F2, F1 and F0.5, its recall higher and its precision lower (no
# S2 breach).
SET_CIS = {
    "baseline_minus_tool_f2_ci": [0.01, 0.05], "baseline_minus_tool_f1_ci": [0.01, 0.04],
    "baseline_minus_tool_f05_ci": [0.005, 0.03], "baseline_minus_tool_recall_ci": [0.02, 0.06],
    "baseline_minus_tool_precision_ci": [-0.1, -0.05],
}


def _r3_report(datasets: tuple[str, ...], baseline: str) -> dict:
    report: dict = {}
    for i, dataset in enumerate(datasets):
        recall = GATED_RECALLS[i % len(GATED_RECALLS)]
        report[dataset] = {
            DEFAULT: {"recall": recall, "precision": 0.49, "f2": 0.758},
            EVERYTHING: {"recall": 0.97, "precision": 0.4, "f2": 0.65, **SET_CIS},
            "rizzo-pii": {"recall": 0.9, "precision": 0.6, "f2": 0.8, **SET_CIS},
            "rizzo-pii@default": {"recall": 0.92, "precision": 0.58, "f2": 0.81, **SET_CIS},
        }
    ci = {"baseline_minus_tool_f2_ci": [0.1, 0.2], "baseline_minus_tool_f1_ci": [0.05, 0.1],
          "baseline_minus_tool_f05_ci": [-0.1, -0.05]}
    report["_macro"] = {
        DEFAULT: {"f2": 0.758, "f1": 0.62, "f05": 0.53, "f2_lodo": [0.725, 0.845]},
        EVERYTHING: {"f2": 0.653, "f1": 0.55, "f05": 0.45, "f2_lodo": [0.62, 0.7], **ci},
        "rizzo-pii": {"f2": 0.58, "f1": 0.5, "f05": 0.6, "f2_lodo": [0.5, 0.6], **ci},
        "rizzo-pii@default": {"f2": 0.77, "f1": 0.68, "f05": 0.63, "f2_lodo": [0.75, 0.8],
                              "baseline_minus_tool_f2_ci": [-0.02, -0.003], "baseline_minus_tool_f1_ci": [-0.1, -0.05],
                              "baseline_minus_tool_f05_ci": [-0.12, -0.08]},
        "mask-all": {"f2": 0.26, "f1": 0.2, "f05": 0.1, "f2_lodo": [0.2, 0.3], **ci},
    }
    if baseline != DEFAULT:
        report = json.loads(json.dumps(report).replace(f'"{DEFAULT}"', f'"{baseline}"'))
    return report


def split_row(leaked=268, leaked_other=222, items=294, other_items=1706):
    return {"leaked": leaked, "leaked_other": leaked_other, "leak": leaked / items, "leak_other": leaked_other / other_items}


def files(r3_baseline: str = DEFAULT) -> Files:
    out: Files = {}
    for key in settings.AB1_GOLD:
        out[compare.ab1_file("scores", key)] = {DEFAULT: ab1_row(), EVERYTHING: against(), "presidio": against()}
        out[compare.ab1_file("coverage", key)] = {
            "covered": 88, "uncovered": 497, "secrets": 585,
            "tools": {name: {"leak_covered": 0.11, "leak_uncovered": 0.05} for name in (DEFAULT, EVERYTHING, "presidio")},
        }
    for key, kind in settings.AB1_KIND_SPLITS.items():
        out[compare.ab1_file(compare.KIND_SPLIT, key)] = {
            "kind": kind, "items": 294, "other_items": 1706,
            "tools": {DEFAULT: split_row(), EVERYTHING: split_row(250, 200), "presidio": split_row(100, 900)},
        }
    out[compare.ROUNDTRIP_FILE] = {"docs": 16572, "masked": 13704, "roundtrip_failures": 0, "failing_idx": {}}
    for run in recipe.R3_RUNS:
        out[compare.r3_file(run.name)] = _r3_report(run.datasets, r3_baseline)
    for v in recipe.VERDICTS:
        out[compare.verdict_file(v.name)] = f"{v.name}: nullpii is ahead of every tool but rizzo-pii@default\n"
    for preset in settings.PRESETS:
        out[compare.piimb_file(preset)] = {
            "name": settings.tool_name(preset), "avg_f2": 0.851,
            "tasks": {"privy": {"f2": 0.713}}, "leaderboard": {"rank": 1, "of": 36},
            "task_ranks": {"privy": {"rank": 12, "of": 36}},
            "without": {"task": "nemotron-pii", "avg_f2": 0.831, "leaderboard": {"rank": 1, "of": 36}},
        }
    return out


def published() -> Files:
    """The published outputs as `reference` lays them out: the 0.5 agent
    default on AB-1, the core regime as R3's baseline with every category
    masked as `nullpii-rel-cuda-default`, an unprinted earlier row, the core
    regime's own reports, and no PIIMB report of the default."""
    out = files(r3_baseline=settings.PUBLISHED_R3_BASELINE)
    for key in settings.AB1_GOLD:
        scores = out[compare.ab1_file("scores", key)]
        scores[settings.PUBLISHED_AB1_BASELINE] = scores.pop(DEFAULT)
        scores[f"{settings.PUBLISHED_AB1_BASELINE}+agent"] = against()
        del scores[EVERYTHING]
        tools = out[compare.ab1_file("coverage", key)]["tools"]
        tools[settings.PUBLISHED_AB1_BASELINE] = tools.pop(DEFAULT)
        del tools[EVERYTHING]
    for key in settings.AB1_KIND_SPLITS:
        tools = out[compare.ab1_file(compare.KIND_SPLIT, key)]["tools"]
        tools[settings.PUBLISHED_AB1_BASELINE] = tools.pop(DEFAULT)
        del tools[EVERYTHING]
    renamed = json.loads(json.dumps({k: v for k, v in out.items() if k.startswith("r3/") and k.endswith(".json")})
                         .replace(f'"{EVERYTHING}"', '"nullpii-rel-cuda-default"'))
    for report in renamed.values():
        for rows in report.values():
            rows[next(iter(settings.PUBLISHED_UNPRINTED))] = dict(rows["rizzo-pii"])
    out |= renamed
    for rel in compare.published_dropped_files():
        out[rel] = "the core regime's\n" if rel.endswith(".txt") else {"_macro": {}}
    del out[compare.piimb_file("default")]
    return out


def write(root: Path, data: Files, edit: Callable[[Files], None] | None = None) -> Path:
    if edit:
        edit(data)
    for rel, value in data.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
    return root


def run(tmp_path: Path, name: str, edit: Callable[[Files], None] | None = None) -> Path:
    return write(tmp_path / name, files(), edit)
