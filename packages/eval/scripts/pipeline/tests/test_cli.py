# SPDX-License-Identifier: Apache-2.0
"""The entry point: the steps get what they ask for, refuse what they
cannot do, and `compare`'s verdict is the process's exit code."""
import json
import os
import sys
from pathlib import Path

import pytest

from pipeline import capture, compare, frozen, recipe, settings
from pipeline.tests.outputs import DEFAULT, run

sys.path.insert(0, str(settings.SCRIPTS))
import bench_pipeline  # noqa: E402


@pytest.fixture
def children(monkeypatch):
    """Every child process the step would run, recorded instead."""
    calls: list[list[str]] = []

    def record(args, cwd=settings.EVAL):
        calls.append([str(a) for a in args])
        return ""
    monkeypatch.setattr(capture, "run", record)
    monkeypatch.setattr(capture, "piimb_texts", lambda sentences, out: calls.append(["piimb_texts", str(sentences)]))
    monkeypatch.setattr(frozen, "verify", lambda root: frozen.Frozen(root))
    return calls


def _score_capture(calls):
    return [c for c in calls if str(settings.SCORE_CAPTURE) in c]


def test_a_resumed_piimb_capture_keeps_what_it_wrote(tmp_path, children):
    bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path / "w"), "--dist", str(tmp_path),
                         "--group", "piimb", "--preset", "everything", "--resume"])
    [call] = _score_capture(children)
    assert call[call.index("--out") + 1] == str(tmp_path / "w" / "spans" / "piimb-everything.jsonl")
    assert call[-2:] == ["--resume", "1"]


def test_a_fresh_piimb_capture_writes_anew(tmp_path, children):
    bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path / "w"), "--dist", str(tmp_path),
                         "--group", "piimb"])
    [call] = _score_capture(children)
    assert "--resume" not in call
    assert json.loads(call[call.index("--config") + 1]) == settings.PRESETS["default"]


def _value(call, flag):
    return call[call.index(flag) + 1]


def test_the_captures_read_the_sets_from_the_checked_copy(tmp_path, children):
    f = frozen.Frozen(tmp_path / "frozen")
    for group in ("piimb", "recognizers"):
        bench_pipeline.main(["capture", "--frozen", str(f.root), "--work", str(tmp_path / "w"), "--dist", str(tmp_path),
                             "--group", group])
    assert ["piimb_texts", str(f.piimb_sentences)] in children
    recognizers = [c for c in children if str(settings.RECOGNIZER_SPANS) in c]
    assert [_value(c, "--gold") for c in recognizers] == [str(f.dataset("ab1", g)) for g in settings.AB1_GOLD.values()]


def test_score_hands_the_scorers_the_checked_copys_sets(tmp_path, children):
    f = frozen.Frozen(tmp_path / "frozen")
    bench_pipeline.main(["score", "--frozen", str(f.root), "--work", str(tmp_path / "w")])
    gold = [_value(c, "--gold") for c in children if "--gold" in c]
    assert gold == ([str(f.dataset("ab1", g)) for g in settings.AB1_GOLD.values()] * 2
                    + [str(f.dataset("ab1", settings.AB1_GOLD[k])) for k in settings.AB1_KIND_SPLITS])
    split = [c for c in children if str(settings.KIND_SPLIT) in c]
    assert [_value(c, "--kind") for c in split] == list(settings.AB1_KIND_SPLITS.values())
    piimb = [c for c in children if str(settings.PIIMB_SCORE) in c]
    assert [_value(c, "--data") for c in piimb] == [str(f.piimb_sentences)] * len(settings.PRESETS)
    assert all(_value(c, "--leave-out") == settings.PIIMB_TRAINING_FAMILY_TASK for c in piimb)
    assert not any(str(settings.RESULTS) in arg for c in children for arg in c)


@pytest.mark.parametrize("flag", [["--resume"], ["--preset", "everything"]])
def test_the_recognizer_capture_refuses_what_it_cannot_honour(tmp_path, children, flag):
    with pytest.raises(SystemExit, match="takes neither --preset nor --resume"):
        bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path), "--dist", str(tmp_path),
                             "--group", "recognizers", *flag])
    assert children == []


def test_every_path_is_made_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = bench_pipeline.parser().parse_args(["score", "--frozen", "F", "--work", "W"])
    assert args.frozen == tmp_path.resolve() / "F" and args.work == tmp_path.resolve() / "W"


def test_compare_exits_with_its_verdict(tmp_path):
    before = run(tmp_path, "before")
    worse = run(tmp_path, "worse", lambda f: f["ab1/scores-ab1-a.json"][DEFAULT].update(keep_rate=0.5))
    report = tmp_path / "report.md"
    assert bench_pipeline.main(["compare", "--new", str(before), "--reference", str(before)]) == compare.EXIT_UNCHANGED
    assert bench_pipeline.main(["compare", "--new", str(worse), "--reference", str(before),
                                "--report", str(report)]) == compare.EXIT_WORSE
    assert report.read_text().startswith("**1 worse**")


def test_compare_refuses_a_missing_or_mistyped_run(tmp_path):
    a = run(tmp_path, "a")
    with pytest.raises(compare.CompareError, match="is not a directory"):
        bench_pipeline.main(["compare", "--new", str(tmp_path / "none"), "--reference", str(a)])
    with pytest.raises(compare.CompareError, match="is not a directory"):
        bench_pipeline.main(["compare", "--new", str(a), "--reference", str(tmp_path / "none")])
    # The work directory instead of its out/: no output where it should be.
    with pytest.raises(compare.CompareError, match="missing"):
        bench_pipeline.main(["compare", "--new", str(tmp_path), "--reference", str(a)])


def test_a_local_copy_is_said_to_be_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(frozen, "verify", lambda root: frozen.Frozen(root))
    monkeypatch.setattr(frozen, "install_datasets", lambda f: None)
    bench_pipeline.main(["fetch", "--frozen", str(tmp_path)])
    said = capsys.readouterr().out
    assert "a local copy, not downloaded now" in said and settings.FROZEN_MANIFEST_SHA256[:12] in said


@pytest.fixture
def published(tmp_path, monkeypatch):
    """A made-up published-bench and frozen copy for `reference`."""
    bench = tmp_path / "published-bench"
    for rel in compare.expected_files():
        if rel.startswith(("ab1/", "piimb/")) and rel not in settings.PUBLISHED_ABSENT:
            (bench / rel).parent.mkdir(parents=True, exist_ok=True)
            (bench / rel).write_text(json.dumps({"published": rel}))
    root = tmp_path / "frozen"
    f = frozen.Frozen(root)
    f.r3_published.mkdir(parents=True)
    for r3 in (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS):
        (f.r3_published / f"{r3.name}.json").write_text(json.dumps({"published": r3.name}))
    for v in (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS):
        (f.r3_published / f"{v.name}.log").write_text(f"verdict {v.name}\n")
    monkeypatch.setattr(settings, "PUBLISHED", bench)
    monkeypatch.setattr(frozen, "verify", lambda r: frozen.Frozen(r))
    return root


def _laid(ref: Path) -> set[str]:
    return {str(p.relative_to(ref)) for p in ref.rglob("*") if p.is_file()}


def test_reference_lays_out_the_published_outputs(tmp_path, published):
    ref = tmp_path / "ref"
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(ref)])
    expected = set(compare.expected_files()) - settings.PUBLISHED_ABSENT | set(compare.published_dropped_files())
    assert _laid(ref) == expected | {bench_pipeline.REFERENCE_MARKER}
    assert json.loads((ref / "piimb" / "piimb-everything.json").read_text()) == {"published": "piimb/piimb-everything.json"}
    assert (ref / "r3" / "verdict-en.txt").read_text() == "verdict verdict-en\n"
    marker = json.loads((ref / bench_pipeline.REFERENCE_MARKER).read_text())
    assert set(marker["files"]) == expected
    # Again into the same place is fine: it is a previous reference.
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(ref)])
    assert _laid(ref) == expected | {bench_pipeline.REFERENCE_MARKER}


def test_a_previous_reference_is_replaced_and_nothing_else_is_removed(tmp_path, published):
    ref = tmp_path / "ref"
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(ref)])
    (ref / "notes.md").write_text("the owner's")
    # A file of the previous reference that is not the published one now.
    (ref / "ab1" / "scores-ab1-a.json").unlink()
    (ref / "ab1" / "scores-ab1-a.json").write_text("an older reference's")
    # A file an older reference wrote that a reference no longer writes.
    marker = json.loads((ref / bench_pipeline.REFERENCE_MARKER).read_text())
    (ref / "r3" / "char-r3-old.json").write_text("{}")
    marker["files"].append("r3/char-r3-old.json")
    (ref / bench_pipeline.REFERENCE_MARKER).write_text(json.dumps(marker))
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(ref)])
    assert json.loads((ref / "ab1" / "scores-ab1-a.json").read_text()) == {"published": "ab1/scores-ab1-a.json"}
    assert not (ref / "r3" / "char-r3-old.json").exists()
    assert (ref / "notes.md").read_text() == "the owner's"


def test_reference_refuses_a_directory_that_is_no_reference(tmp_path, published):
    out = tmp_path / "w" / "out"
    (out / "ab1").mkdir(parents=True)
    (out / "ab1" / "scores-ab1-a.json").write_text("a run's own scores")
    (out / "elsewhere.txt").write_text("kept")
    with pytest.raises(SystemExit, match="not empty and holds no REFERENCE.json"):
        bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(out)])
    assert (out / "ab1" / "scores-ab1-a.json").read_text() == "a run's own scores"
    # With --force the files a reference writes are replaced; nothing else.
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(out), "--force"])
    assert json.loads((out / "ab1" / "scores-ab1-a.json").read_text()) == {"published": "ab1/scores-ab1-a.json"}
    assert (out / "elsewhere.txt").read_text() == "kept"


def test_reference_paths_may_be_relative(tmp_path, published, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bench_pipeline.main(["reference", "--frozen", published.name, "--out", "ref"])
    link = tmp_path / "ref" / "r3" / "char-r3.json"
    assert Path(os.readlink(link)).is_absolute()
    monkeypatch.chdir("/")
    assert json.loads(link.read_text()) == {"published": "char-r3"}


@pytest.mark.parametrize("where", ["published-bench", "frozen", "frozen/predictions", "."])
def test_reference_refuses_to_write_over_the_published_outputs_or_the_frozen_copy(tmp_path, published, where):
    with pytest.raises(SystemExit, match="overlaps"):
        bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(tmp_path / where)])
    assert not (tmp_path / "published-bench" / "ab1" / "scores-ab1-a.json").is_symlink()


def test_capture_run_raises_when_the_child_fails(tmp_path):
    with pytest.raises(RuntimeError, match="exited with 3"):
        capture.run([sys.executable, "-c", "raise SystemExit(3)"], cwd=Path(tmp_path))


@pytest.mark.parametrize("preset, round_trips", [("default", True), ("everything", False)])
def test_only_the_default_capture_runs_the_round_trip(tmp_path, children, monkeypatch, preset, round_trips):
    from pipeline import texts
    monkeypatch.setattr(texts, "write", lambda keys, out: 0)
    ran = []
    monkeypatch.setattr(capture, "roundtrip", lambda dist, t, p: ran.append(p) or {"docs": 1})
    bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path / "w"), "--dist", str(tmp_path),
                         "--group", "ab1", "--preset", preset])
    assert ran == (["default"] if round_trips else [])
    assert (tmp_path / "w" / "out" / compare.ROUNDTRIP_FILE).is_file() == round_trips


def test_the_round_trip_result_is_the_last_line_printed(monkeypatch):
    monkeypatch.setattr(capture, "run", lambda args, cwd=settings.EVAL: 'progress 1/2\n\n{"docs": 2, "masked": 1}\n')
    assert capture.roundtrip(Path("dist"), Path("texts.jsonl"), "default") == {"docs": 2, "masked": 1}


def test_the_piimb_texts_are_written_whole(tmp_path, monkeypatch):
    def export(args, cwd=settings.EVAL):
        Path(args[args.index("--out") + 1]).write_text("rows\n")
        return ""
    monkeypatch.setattr(capture, "run", export)
    out = tmp_path / "texts" / "piimb.jsonl"
    capture.piimb_texts(tmp_path / "sentences.jsonl", out)
    assert out.read_text() == "rows\n"
    assert [p.name for p in out.parent.iterdir()] == ["piimb.jsonl"]


@pytest.mark.parametrize("step", ["reference", "reproduce"])
def test_the_published_run_steps_refuse_a_published_bench_that_holds_a_run(tmp_path, published, step):
    (settings.PUBLISHED / "OUTPUTS.json").write_text(json.dumps({"names": "run", "files": []}))
    args = ["--out", str(tmp_path / "ref")] if step == "reference" else ["--work", str(tmp_path / "w")]
    with pytest.raises(SystemExit, match="holds a run of the pipeline"):
        bench_pipeline.main([step, "--frozen", str(published), *args])
