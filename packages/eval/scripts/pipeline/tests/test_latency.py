# SPDX-License-Identifier: Apache-2.0
"""The published latency: a harness file is kept as aggregates with no
local path, latency.json is refused when it does not hold what the docs
read, and every latency block, the chart included, says what it holds."""
import copy
import json

import pytest

import bench_pipeline
from pipeline import blocks_latency, docs, latency, render, settings
from pipeline.latency import LatencyError
from pipeline.tests import render_outputs as ro

SIZES = latency.SIZES
SECRETS_ONLY = ["account_number", "private_person", "private_url"]


def _sizes(a, b, c):
    return dict(zip(SIZES, (a, b, c), strict=True))


def _run(label, backend, rounds, options=None, plan=None):
    """A run as latency.json keeps it: `rounds` per size, each round's median."""
    plan = plan or ("full" if backend == "cuda" else "short")
    calls = _sizes(2, 1, 1) if plan == "full" else _sizes(1, 1, 3)
    by_size = {s: {"p50": sorted(r)[len(r) // 2], "p95": max(r) * 1.2, "roundP50s": r, "callsPerRound": calls[s]}
               for s, r in zip(SIZES, rounds, strict=True)}
    return {"label": label, "at": "2026-10-30T18:00:00.000Z", "plan": plan, "node": "v24.15.0",
            "model": settings.PUBLISHED_MODEL, "config": {"backend": backend, **(options or {})}, "bySize": by_size}


ALL = {"disabledCategories": []}
PART = {"disabledCategories": SECRETS_ONLY}


def _data():
    tools = {"gpu": {"ettin-68m": _sizes(11, 157, 544), "rizzo-pii": _sizes(27, 494, 1715),
                     "openmed-large": _sizes(80, 1209, 5126)},
             "cpu": {"presidio": _sizes(35, 511, 2209), "gliner-onnx-pii-fp32": _sizes(1300, 15549, 55069),
                     "openmed-large": _sizes(1228, 14291, 22324)}}
    runs = [
        _run("gpu-default-a", "cuda", [[30.0, 31.0, 32.0], [440.0, 450.0, 460.0], [1600.0, 1610.0, 1620.0]]),
        _run("gpu-default-b", "cuda", [[33.0, 34.0, 35.0], [470.0, 480.0, 600.0], [1630.0, 1640.0, 1650.0]]),
        _run("gpu-all", "cuda", [[35.0] * 3, [500.0] * 3, [1750.0] * 3], ALL),
        _run("gpu-secrets", "cuda", [[55.0] * 3, [900.0] * 3, [3150.0] * 3], PART),
        _run("cpu-default-a", "cpu", [[380.0], [6800.0], [24000.0]]),
        _run("cpu-default-b", "cpu", [[390.0], [6900.0], [24500.0]]),
        _run("cpu-all", "cpu", [[430.0], [7600.0], [27000.0]], ALL),
        _run("cpu-secrets", "cpu", [[700.0], [12240.0], [42000.0]], PART),
    ]
    return {
        "about": "test",
        "machines": {"pc": {"os": "Linux", "gpu": "A Test GPU", "cpu": "A Test CPU"}},
        "plans": {"full": {"texts": _sizes(2, 1, 1), "rounds": 3}, "short": {"texts": _sizes(1, 1, 3), "rounds": 1}},
        "tables": {"gpu": {"machine": "pc", "backend": "cuda", "plan": "full"},
                   "cpu": {"machine": "pc", "backend": "cpu", "plan": "short"}},
        "tools": {"date": "2026-10-21", "timer": "competitor_latency.py", "corpus_commit": "5130a64", "rows": tools},
        "nullpii": {"date": "2026-10-30", "commit": "6f44a03", "version": "0.5.4", "timer": "harness.mjs latency",
                    "corpus_commit": "5130a64", "onnxruntime_node": "1.30.0", "runs": runs},
    }


def _lat(edit=None):
    data = _data()
    if edit:
        edit(data)
    return latency.check(data)


# Harness files ------------------------------------------------------------------------

# Where the harness ran: a local path that must not reach latency.json.
LOCAL_ROOT = "/srv/build"

HARNESS = {
    "mode": "latency", "plan": "short",
    "bySize": {s: {"p50": 1.5, "p95": 2.0, "msPer1k": 0.7, "spreadPct": 0, "roundP50s": [1.5], "callsPerRound": 6}
               for s in SIZES},
    "label": "r15-new-cpu-all", "dist": f"{LOCAL_ROOT}/nullpii/dist",
    "config": json.dumps({"modelDir": f"{LOCAL_ROOT}/.cache/nullpii/models/lBroth/nullpii/5dd3c79", "backend": "cpu",
                          "disabledCategories": []}),
    "node": "v24.15.0", "at": "2026-10-30T18:42:09.994Z",
}


def test_a_harness_file_is_kept_as_aggregates_without_any_local_path():
    run = latency.harness_run(copy.deepcopy(HARNESS))
    assert run == {"label": "r15-new-cpu-all", "at": "2026-10-30T18:42:09.994Z", "plan": "short", "node": "v24.15.0",
                   "model": "lBroth/nullpii@5dd3c79", "config": {"backend": "cpu", "disabledCategories": []},
                   "bySize": {s: {"p50": 1.5, "p95": 2.0, "roundP50s": [1.5], "callsPerRound": 6} for s in SIZES}}
    assert LOCAL_ROOT not in json.dumps(run)
    assert latency.config_of(run) == "everything"


def test_a_file_that_is_no_latency_run_or_names_no_model_is_refused():
    with pytest.raises(LatencyError, match="not a latency run"):
        latency.harness_run({**HARNESS, "mode": "score"})
    with pytest.raises(LatencyError, match="no modelDir"):
        latency.harness_run({**HARNESS, "config": json.dumps({"backend": "cpu"})})


def test_the_cli_prints_the_run_as_latency_json_keeps_it(tmp_path, capsys):
    harness = tmp_path / "h.json"
    harness.write_text(json.dumps(HARNESS))
    assert bench_pipeline.main(["latency-run", "--harness", str(harness)]) == 0
    assert json.loads(capsys.readouterr().out) == latency.harness_run(copy.deepcopy(HARNESS))


@pytest.mark.parametrize("options, config", [
    ({}, "default"),
    ({"disabledCategories": []}, "everything"),
    ({"disabledCategories": SECRETS_ONLY}, latency.PARTIAL),
])
def test_a_run_is_read_as_the_configuration_its_options_are(options, config):
    assert latency.config_of({"config": {"backend": "cpu", **options}}) == config


@pytest.mark.parametrize("options", [
    {"disabledCategories": ["secret"]},
    {"disabledCategories": SECRETS_ONLY, "threshold": 0.3},
    {"threshold": 0.3},
])
def test_options_of_no_published_configuration_are_refused(options):
    with pytest.raises(LatencyError, match="no configuration"):
        latency.config_of({"label": "x", "config": {"backend": "cpu", **options}})


# latency.json ---------------------------------------------------------------------------

def test_the_tracked_file_loads_and_holds_no_local_path_and_no_text():
    raw = latency.LATENCY.read_text()
    assert not any(s in raw for s in ("/home/", "/Users/", "dist", "modelDir"))
    lat = latency.load()
    for table in latency.TABLES:
        for preset in settings.PRESETS:
            assert lat.runs(table, preset)


def test_nullpiis_value_is_the_median_of_every_round_median_of_its_runs():
    lat = _lat()
    # Rounds of both default runs: 440, 450, 460, 470, 480, 490.
    assert lat.nullpii("gpu", "default")["30000"] == 465.0
    assert lat.nullpii("cpu", "everything") == _sizes(430.0, 7600.0, 27000.0)


def _drop_everything_on_cpu(data):
    data["nullpii"]["runs"] = [r for r in data["nullpii"]["runs"] if r["label"] != "cpu-all"]


def _bad_size_order(data):
    data["tools"]["rows"]["gpu"]["ettin-68m"] = {"30000": 157, "2000": 11, "100000": 544}


def _another_plans_calls(data):
    data["nullpii"]["runs"][0]["bySize"]["2000"]["callsPerRound"] = 60


def _missing_round(data):
    data["nullpii"]["runs"][0]["bySize"]["30000"]["roundP50s"].pop()


def _zero_time(data):
    data["tools"]["rows"]["cpu"]["presidio"]["2000"] = 0


def _nan_time(data):
    data["nullpii"]["runs"][1]["bySize"]["100000"]["roundP50s"][0] = float("nan")


def _unknown_backend(data):
    data["nullpii"]["runs"][0]["config"]["backend"] = "mps"


def _wrong_plan(data):
    data["nullpii"]["runs"][4]["plan"] = "full"


def _extra_field(data):
    data["nullpii"]["runs"][0]["dist"] = f"{LOCAL_ROOT}/dist"


def _no_tools(data):
    data["tools"]["rows"]["gpu"] = {}


@pytest.mark.parametrize("edit, match", [
    (_drop_everything_on_cpu, "no run of nullpii in everything on cpu"),
    (_bad_size_order, "the sizes must be"),
    (_another_plans_calls, "was not timed on plan full"),
    (_missing_round, "was not timed on plan full"),
    (_zero_time, "not a positive time"),
    (_nan_time, "not a positive time"),
    (_unknown_backend, "times no table"),
    (_wrong_plan, "the table's is short"),
    (_extra_field, "its fields must be"),
    (_no_tools, "no other tool"),
])
def test_a_file_that_does_not_hold_what_the_docs_read_is_refused(edit, match):
    with pytest.raises(LatencyError, match=match):
        _lat(edit)


# The blocks -----------------------------------------------------------------------------

def test_the_table_sorts_by_30k_bolds_each_columns_fastest_and_names_nullpiis_rows():
    assert blocks_latency.table(_lat(), "gpu").split("\n") == [
        "| Tool | 2k | 30k | 100k |",
        "|---|---:|---:|---:|",
        "| ettin-68m | **11** | **157** | **544** |",
        "| **nullpii** (agent default) | 32 | 465 | 1,625 |",
        "| rizzo-pii | 27 | 494 | 1,715 |",
        "| **nullpii** (every category masked) | 35 | 500 | 1,750 |",
        "| OpenMed PII Large | 80 | 1,209 | 5,126 |",
    ]


def test_a_faster_nullpii_row_moves_up_and_takes_the_bold():
    def faster(data):
        data["nullpii"]["runs"][2]["bySize"]["30000"]["roundP50s"] = [100.0] * 3
    lines = blocks_latency.table(_lat(faster), "gpu").split("\n")
    assert lines[2] == "| **nullpii** (every category masked) | 35 | **100** | 1,750 |"
    assert lines[3] == "| ettin-68m | **11** | 157 | **544** |"


def test_the_alternative_text_names_the_extremes_and_nullpiis_values_from_the_data():
    alt = blocks_latency.fig_alt(_lat())
    assert alt.startswith("![GPU latency at 30,000 characters, median milliseconds per call: from ettin-68m at 157 to"
                          " OpenMed PII Large at 1,209; nullpii 465 in its agent default and 500 with every"
                          " category masked.")
    assert blocks_latency.chart_rows(_lat())[0] == ("ettin-68m", 157)


def test_the_partial_presets_cost_is_stated_from_its_run_against_the_default():
    text = blocks_latency.method(_lat())
    assert ("nullpii took 900 ms at 30,000 characters on GPU and 12,240 ms on CPU, 1.9 and 1.8 times its agent"
            " default's (465 ms and 6,850 ms).") in text

    def slower(data):
        data["nullpii"]["runs"][3]["bySize"]["30000"]["roundP50s"] = [1395.0] * 3
    assert "1,395 ms at 30,000 characters on GPU and 12,240 ms on CPU, 3.0 and 1.8 times" in blocks_latency.method(
        _lat(slower))


def test_a_configuration_timed_a_different_number_of_times_per_table_is_refused():
    def one_cpu_default(data):
        data["nullpii"]["runs"] = [r for r in data["nullpii"]["runs"] if r["label"] != "cpu-default-b"]
    with pytest.raises(LatencyError, match="different number of runs per table"):
        blocks_latency.method(_lat(one_cpu_default))


def test_the_method_says_when_on_which_build_and_how_each_row_was_timed():
    text = blocks_latency.method(_lat())
    assert "timed on 30 October 2026 with the build of `main` at 6f44a03 (after release 0.5.4)" in text
    assert "In each table it was timed in two runs of the agent default and one run of every category masked" in text
    assert "timed on 21 October 2026 on the same machine" in text
    assert "on GPU, 2, 1 and 1 texts per size, three rounds" in text
    assert "On CPU, 1, 1 and 3 texts per size, timed once" in text


def test_the_cpu_notes_are_refused_when_the_tools_they_name_change():
    def gpu_presidio(data):
        data["tools"]["rows"]["gpu"]["presidio"] = _sizes(1, 2, 3)
    with pytest.raises(LatencyError, match="the CPU notes name"):
        blocks_latency.readme_tables(_lat(gpu_presidio))


def test_the_readme_tables_and_intro_give_machine_plan_and_dates():
    lat = _lat()
    tables = blocks_latency.readme_tables(lat)
    assert "**GPU** (Linux, A Test GPU; 2, 1 and 1 texts per size, three rounds)." in tables
    assert "**CPU** (Linux, A Test CPU, every tool on CPU; 1, 1 and 3 texts per size, timed once," in tables
    assert "its 100k figure, from three texts, is rough" in tables
    assert "gliner_multi_pii (ONNX) runs on CPU only, and Presidio has no GPU path" in tables
    intro = blocks_latency.readme_intro(lat)
    assert "timed on 30 October 2026 with the build of `main` at 6f44a03" in intro
    assert "every other tool was timed on 21 October 2026" in intro


def test_the_glance_rows_and_the_limit_come_from_the_data():
    lat = _lat()
    assert blocks_latency.glance(lat).split("\n")[0] == (
        "| Latency on GPU (A Test GPU), 30,000 characters, timed by hand on `main` at 6f44a03 | 465 ms in its agent"
        " default; 500 ms with every category masked |")
    assert "nullpii on 30 October 2026, the other tools on 21 October 2026" in blocks_latency.limit(lat)


# Rendering ------------------------------------------------------------------------------

def test_a_change_to_latency_json_is_a_difference_render_check_lists(tmp_path, monkeypatch):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    data = json.loads(latency.LATENCY.read_text())
    data["tools"]["rows"]["gpu"]["ettin-68m"]["30000"] = 99
    moved = tmp_path / "latency.json"
    moved.write_text(json.dumps(data))
    monkeypatch.setattr(latency, "LATENCY", moved)
    diffs = {str(d) for d in render.check(run, published, root)}
    assert diffs == {f"{docs.README} <!-- fig-latency -->: differs", f"{docs.README} <!-- latency -->: differs",
                     f"{docs.METHOD} <!-- fig-latency -->: differs", f"{docs.FIGURES}/latency-gpu.svg: differs"}


def test_a_run_of_the_pipeline_leaves_the_latency_file_and_its_regions_as_they_are(tmp_path):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    (published / "latency").mkdir(parents=True)
    (published / "latency" / "latency.json").write_text("kept")
    render.render(run, published, root)
    assert (published / "latency" / "latency.json").read_text() == "kept"
    readme = (root / docs.README).read_text()
    assert render._body(readme, "latency") == blocks_latency.readme_tables(latency.load()) + "\n"


@pytest.mark.parametrize("ms, words", [(24268.0, "24 seconds"), (9960.0, "10 seconds"), (1634.2, "1.6 seconds"),
                                       (9940.0, "9.9 seconds")])
def test_a_time_in_seconds_keeps_one_decimal_below_ten(ms, words):
    assert blocks_latency.seconds(ms) == words


def test_the_readmes_long_input_expectation_is_the_agent_defaults_100k_time():
    # The default's rounds at 100k: GPU 1,600 to 1,650 (median 1,625), CPU 24,000 and 24,500.
    assert blocks_latency.long_inputs(_lat()) == (
        "Expect about 24 seconds per 100,000 characters on CPU and about 1.6 seconds on GPU (the agent default, on the"
        " machine of the [latency tables](#latency)).")

    def slower(data):
        for run in data["nullpii"]["runs"]:
            if run["label"].startswith("cpu-default"):
                run["bySize"]["100000"]["roundP50s"] = [31000.0]
    assert "about 31 seconds per 100,000 characters on CPU" in blocks_latency.long_inputs(_lat(slower))


def test_the_long_input_bullet_is_rendered_and_moves_with_the_data(tmp_path, monkeypatch):
    run, root, published = ro.write_run(tmp_path / "run"), ro.docs_root(tmp_path), tmp_path / "pb"
    render.render(run, published, root)
    readme = (root / docs.README).read_text()
    assert blocks_latency.long_inputs(latency.load()) in render._body(readme, "doesnt-do")
    data = json.loads(latency.LATENCY.read_text())
    for r in data["nullpii"]["runs"]:
        if r["config"] == {"backend": "cpu"}:
            r["bySize"]["100000"]["roundP50s"] = [50000.0]
    moved = tmp_path / "latency.json"
    moved.write_text(json.dumps(data))
    monkeypatch.setattr(latency, "LATENCY", moved)
    assert f"{docs.README} <!-- doesnt-do -->: differs" in {str(d) for d in render.check(run, published, root)}
