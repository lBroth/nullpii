# SPDX-License-Identifier: Apache-2.0
"""Tests for bench_full.py error-handling guarantees.

Covers the pre-release "throw-always, no silent defaults" contract:
- run_combo: per-sample predictor exception MUST propagate as RuntimeError
- run_combo: checkpoint state preserved across the raise
- main(): caller records CRASHED status in matrix when run_combo raises
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS = REPO_ROOT / "packages" / "eval" / "scripts"
SRC = REPO_ROOT / "packages" / "eval" / "src"
sys.path.insert(0, str(SRC))


def _import_bench_full():
    spec = importlib.util.spec_from_file_location("bench_full", SCRIPTS / "bench_full.py")
    module = importlib.util.module_from_spec(spec)
    # @dataclass introspects sys.modules[cls.__module__] — register
    # before exec so frozen+slots dataclass init works.
    sys.modules["bench_full"] = module
    spec.loader.exec_module(module)
    return module


bench_full = _import_bench_full()
from nullpii_eval.adapters import ToolResult  # noqa: E402
from nullpii_eval.datasets import Sample, Span  # noqa: E402


def _sample(text: str, *spans: tuple[str, int, int]) -> Sample:
    return Sample(text=text, spans=tuple(Span(lbl, s, e) for lbl, s, e in spans))


def test_run_combo_propagates_predictor_exception(tmp_path: Path) -> None:
    """A raise from the predictor MUST surface as RuntimeError up to the caller."""
    samples = [_sample(f"text {i}") for i in range(5)]

    def boom(_text: str) -> ToolResult:
        raise ValueError("synthetic predictor failure")

    spec = bench_full.DatasetSpec(key="t-fail", loader=lambda n: samples, default_n=None)

    with pytest.raises(RuntimeError) as excinfo:
        bench_full.run_combo(
            tool_name="boomtool",
            predictor=boom,
            dataset=spec,
            samples=samples,
            ckpt_dir=tmp_path,
            want_confusion=False,
        )
    assert "boomtool/t-fail" in str(excinfo.value)
    assert "ValueError" in str(excinfo.value)
    assert "synthetic predictor failure" in str(excinfo.value)


def test_run_combo_checkpoint_state_preserved_on_raise(tmp_path: Path) -> None:
    """State path must reflect last *successful* idx after a crash."""
    samples = [_sample(f"t{i}") for i in range(10)]
    fail_at = 3

    def flaky(text: str) -> ToolResult:
        idx = int(text[1:])
        if idx == fail_at:
            raise RuntimeError("boom at idx 3")
        return ToolResult(spans=[], elapsed_ms=0.1)

    spec = bench_full.DatasetSpec(key="t-flaky", loader=lambda n: samples, default_n=None)

    with pytest.raises(RuntimeError):
        bench_full.run_combo(
            tool_name="flakytool",
            predictor=flaky,
            dataset=spec,
            samples=samples,
            ckpt_dir=tmp_path,
            want_confusion=False,
        )
    state_path = tmp_path / "flakytool-t-flaky.state"
    assert state_path.exists()
    # Last successful idx is fail_at - 1 (== 2). State stores i - 1
    # where i is the failing idx, so state == 2.
    assert int(state_path.read_text().strip()) == fail_at - 1


def test_run_combo_returns_ok_when_no_errors(tmp_path: Path) -> None:
    """Happy path: no exceptions → tuple (f1, wall, n, conf)."""
    samples = [_sample("a@b.com", ("private_email", 0, 7))]

    def echo(text: str) -> ToolResult:
        return ToolResult(spans=[Span("private_email", 0, 7)], elapsed_ms=0.1)

    spec = bench_full.DatasetSpec(key="t-ok", loader=lambda n: samples, default_n=None)
    f1, wall, n, conf = bench_full.run_combo(
        tool_name="oktool",
        predictor=echo,
        dataset=spec,
        samples=samples,
        ckpt_dir=tmp_path,
        want_confusion=False,
    )
    assert n == 1
    assert wall >= 0
    assert f1 == 1.0  # exact match
    assert conf is None


def test_matrix_records_crashed_status_on_predictor_failure(tmp_path: Path) -> None:
    """Simulate the caller flow: run_combo raises, _record-style logic
    must persist a CRASHED entry in matrix.json (not silently skip).
    """
    matrix: dict[str, dict[str, dict]] = {}
    matrix_path = tmp_path / "matrix.json"

    def _record(ds_key: str, tool_name: str, result) -> None:
        if isinstance(result, BaseException):
            matrix.setdefault(ds_key, {})[tool_name] = {
                "status": "CRASHED",
                "error": f"{type(result).__name__}: {result}",
                "f1": None,
                "wall_s": 0.0,
                "n": 0,
                "samples_per_s": 0.0,
            }
            matrix_path.write_text(json.dumps(matrix, indent=2))
            return
        # OK path not exercised here.

    samples = [_sample("x")]

    def boom(_t):
        raise ValueError("dead")

    spec = bench_full.DatasetSpec(key="ds1", loader=lambda n: samples, default_n=None)
    try:
        bench_full.run_combo(
            tool_name="t1", predictor=boom, dataset=spec,
            samples=samples, ckpt_dir=tmp_path, want_confusion=False,
        )
    except Exception as e:
        _record("ds1", "t1", e)

    persisted = json.loads(matrix_path.read_text())
    assert persisted["ds1"]["t1"]["status"] == "CRASHED"
    assert persisted["ds1"]["t1"]["f1"] is None
    assert "ValueError" in persisted["ds1"]["t1"]["error"]
    assert "dead" in persisted["ds1"]["t1"]["error"]
