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


# Two texts of each set the captures read, made up.
FAKE_SETS = {"ab1": tuple(settings.AB1_GOLD), "r3": (*settings.R3_GATED, *settings.R3_REPORTED),
             "piimb": ("ai4privacy-en", "privy")}


def _fake_texts(keys, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"dataset": k, "idx": i, "text": "abc" * (i + 1)} for k in keys for i in range(2)]
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


def _fake_node(args: list[str]) -> str:
    """What score_capture.mjs and roundtrip.mjs write and print, on the
    texts they are given: no span, every text."""
    texts = [json.loads(line) for line in Path(_value(args, "--texts")).read_text().splitlines() if line]
    if str(settings.ROUNDTRIP) in args:
        return json.dumps({"docs": len(texts), "masked": 0, "roundtrip_failures": 0, "failing_idx": {}}) + "\n"
    if "--checkpoints" in args:
        out_dir, tool = Path(_value(args, "--checkpoints")), _value(args, "--tool")
        for dataset in dict.fromkeys(t["dataset"] for t in texts):
            rows = [{"idx": t["idx"], "spans": []} for t in texts if t["dataset"] == dataset]
            (out_dir / f"{tool}-{dataset}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    elif "--out" in args:
        rows = [{"dataset": t["dataset"], "idx": t["idx"], "spans": []} for t in texts]
        Path(_value(args, "--out")).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return ""


@pytest.fixture
def children(monkeypatch):
    """Every child process the step would run, recorded instead; the
    captures' own children write what they would, on made-up texts."""
    from pipeline import texts
    calls: list[list[str]] = []

    def record(args, cwd=settings.EVAL):
        args = [str(a) for a in args]
        calls.append(args)
        if str(settings.SCORE_CAPTURE) in args or str(settings.ROUNDTRIP) in args:
            return _fake_node(args)
        if str(settings.RECOGNIZER_SPANS) in args:
            Path(_value(args, "--out")).write_text(json.dumps({"idx": 0, "spans": []}) + "\n")
        return ""

    def piimb_texts(sentences, out):
        calls.append(["piimb_texts", str(sentences)])
        _fake_texts(FAKE_SETS["piimb"], out)

    monkeypatch.setattr(capture, "run", record)
    monkeypatch.setattr(capture, "piimb_texts", piimb_texts)
    monkeypatch.setattr(texts, "write", _fake_texts)
    monkeypatch.setattr(frozen, "verify", lambda root, only=None: frozen.Frozen(root))
    return calls


def _score_capture(calls):
    return [c for c in calls if str(settings.SCORE_CAPTURE) in c]


def _capture(tmp_path, *args):
    bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path / "w"), "--dist", str(tmp_path),
                         *args])


def _part(tmp_path, name):
    return tmp_path / "w" / "parts" / name


def test_a_resumed_piimb_capture_keeps_what_it_wrote(tmp_path, children):
    _capture(tmp_path, "--group", "piimb", "--preset", "everything", "--resume")
    [call] = _score_capture(children)
    assert call[call.index("--out") + 1] == str(_part(tmp_path, "piimb-everything-1-of-1") / "piimb-everything.jsonl")
    assert call[-2:] == ["--resume", "1"]


def test_a_fresh_piimb_capture_writes_anew(tmp_path, children):
    _capture(tmp_path, "--group", "piimb")
    [call] = _score_capture(children)
    assert "--resume" not in call
    assert json.loads(call[call.index("--config") + 1]) == settings.PRESETS["default"]
    marker = json.loads((_part(tmp_path, "piimb-default-1-of-1") / "PART.json").read_text())
    assert marker["rows"] == marker["totals"] == {"ai4privacy-en": 2, "privy": 2}


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


def _capture_everything(tmp_path, shards: int = 1):
    """Every capture `score` needs, each group in `shards` parts."""
    for group, preset in bench_pipeline.CAPTURES:
        for k in range(1, shards + 1):
            _capture(tmp_path, "--group", group, "--preset", preset, "--shard", f"{k}/{shards}")
    _capture(tmp_path, "--group", "recognizers")


def test_score_hands_the_scorers_the_checked_copys_sets(tmp_path, children):
    f = frozen.Frozen(tmp_path / "frozen")
    _capture_everything(tmp_path)
    children.clear()
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


@pytest.mark.parametrize("shards", [1, 3])
def test_score_puts_the_parts_together_where_the_scorers_read_them(tmp_path, children, shards):
    _capture_everything(tmp_path, shards)
    bench_pipeline.main(["score", "--frozen", str(tmp_path / "frozen"), "--work", str(tmp_path / "w")])
    w = bench_pipeline.Work(tmp_path / "w")
    for preset in settings.PRESETS:
        for key in (*FAKE_SETS["ab1"], *FAKE_SETS["r3"]):
            rows = (w.checkpoints / f"{settings.tool_name(preset)}-{key}.jsonl").read_text().splitlines()
            assert [json.loads(r)["idx"] for r in rows] == [0, 1]
        spans = [json.loads(r) for r in w.piimb_spans(preset).read_text().splitlines()]
        assert [(r["dataset"], r["idx"]) for r in spans] == [(d, i) for d in FAKE_SETS["piimb"] for i in range(2)]
    assert json.loads(w.roundtrip.read_text())["docs"] == 2 * len(FAKE_SETS["ab1"])


def test_score_names_every_capture_that_is_missing(tmp_path, children):
    _capture(tmp_path, "--group", "ab1", "--preset", "default", "--shard", "1/2")
    _capture(tmp_path, "--group", "r3", "--preset", "default")
    with pytest.raises(SystemExit, match="ab1 default: shard 2 of 2 not captured"):
        bench_pipeline.main(["score", "--frozen", str(tmp_path), "--work", str(tmp_path / "w")])
    _capture(tmp_path, "--group", "ab1", "--preset", "default", "--shard", "2/2")
    with pytest.raises(SystemExit) as caught:
        bench_pipeline.main(["score", "--frozen", str(tmp_path), "--work", str(tmp_path / "w")])
    said = str(caught.value)
    assert "capture --group ab1 --preset everything" in said and "capture --group roundtrip --preset default" in said
    assert "capture --group r3 --preset default" not in said and "recognizers (ab1-a)" in said


def test_a_limited_capture_is_never_scored(tmp_path, children):
    _capture_everything(tmp_path)
    _capture(tmp_path, "--group", "r3", "--preset", "default", "--limit", "1")
    marker = json.loads((_part(tmp_path, "r3-default-1-of-1") / "PART.json").read_text())
    assert marker["limit"] == 1 and set(marker["rows"].values()) == {1}
    with pytest.raises(SystemExit, match="limited capture"):
        bench_pipeline.main(["score", "--frozen", str(tmp_path), "--work", str(tmp_path / "w")])
    # Its parts are refused too, wherever they are put together.
    (tmp_path / "w" / "LIMITED.json").unlink()
    with pytest.raises(SystemExit, match="r3 default: a limited capture"):
        bench_pipeline.main(["score", "--frozen", str(tmp_path), "--work", str(tmp_path / "w")])


def test_an_interrupted_capture_is_not_a_part(tmp_path, children, monkeypatch):
    def dies(args, cwd=settings.EVAL):
        raise RuntimeError("node … exited with 1")
    _capture(tmp_path, "--group", "r3", "--preset", "default")
    monkeypatch.setattr(capture, "run", dies)
    with pytest.raises(RuntimeError):
        _capture(tmp_path, "--group", "r3", "--preset", "default")
    assert not (_part(tmp_path, "r3-default-1-of-1") / "PART.json").exists()


def test_a_capture_that_misses_texts_is_refused(tmp_path, children, monkeypatch):
    def short(args, cwd=settings.EVAL):
        out = _fake_node([str(a) for a in args])
        for path in Path(_value([str(a) for a in args], "--checkpoints")).glob("*.jsonl"):
            path.write_text(path.read_text().splitlines()[0] + "\n")
        return out
    monkeypatch.setattr(capture, "run", short)
    with pytest.raises(Exception, match="1 rows of ab1-a captured for 2 texts"):
        _capture(tmp_path, "--group", "ab1", "--preset", "default")


@pytest.mark.parametrize("flag", [["--resume"], ["--preset", "everything"], ["--shard", "1/2"], ["--limit", "3"]])
def test_the_recognizer_capture_refuses_what_it_cannot_honour(tmp_path, children, flag):
    with pytest.raises(SystemExit, match="takes none of --preset, --resume, --shard, --limit"):
        bench_pipeline.main(["capture", "--frozen", str(tmp_path), "--work", str(tmp_path), "--dist", str(tmp_path),
                             "--group", "recognizers", *flag])
    assert children == []


@pytest.mark.parametrize("shard", ["0/2", "3/2", "1", "a/b", "1/0", "-1/2"])
def test_a_shard_is_k_of_n_from_1(tmp_path, children, shard):
    with pytest.raises((SystemExit, ValueError)):
        _capture(tmp_path, "--group", "r3", "--shard", shard)


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
    monkeypatch.setattr(frozen, "verify", lambda root, only=None: frozen.Frozen(root))
    monkeypatch.setattr(frozen, "install_datasets", lambda f: None)
    bench_pipeline.main(["fetch", "--frozen", str(tmp_path)])
    said = capsys.readouterr().out
    assert "a local copy, not downloaded now" in said and settings.FROZEN_MANIFEST_SHA256[:12] in said


@pytest.fixture
def published(tmp_path, monkeypatch):
    """A made-up frozen copy for `reference` (the published run's outputs
    in it), and a published-bench that holds a run of the pipeline."""
    bench = tmp_path / "published-bench"
    bench.mkdir()
    (bench / "OUTPUTS.json").write_text(json.dumps({"names": "run", "files": []}))
    root = tmp_path / "frozen"
    f = frozen.Frozen(root)
    for rel in compare.expected_files():
        if rel.startswith(("ab1/", "piimb/")) and rel not in settings.PUBLISHED_ABSENT:
            (f.published_outputs / rel).parent.mkdir(parents=True, exist_ok=True)
            (f.published_outputs / rel).write_text(json.dumps({"published": rel}))
    f.r3_published.mkdir(parents=True)
    for r3 in (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS):
        (f.r3_published / f"{r3.name}.json").write_text(json.dumps({"published": r3.name}))
    for v in (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS):
        (f.r3_published / f"{v.name}.log").write_text(f"verdict {v.name}\n")
    monkeypatch.setattr(settings, "PUBLISHED", bench)
    monkeypatch.setattr(frozen, "verify", lambda r, only=None: frozen.Frozen(r))
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


def test_the_round_trip_is_a_capture_of_its_own_in_the_default_preset(tmp_path, children):
    _capture(tmp_path, "--group", "ab1", "--preset", "default")
    assert not [c for c in children if str(settings.ROUNDTRIP) in c]
    _capture(tmp_path, "--group", "roundtrip")
    [call] = [c for c in children if str(settings.ROUNDTRIP) in c]
    assert json.loads(_value(call, "--config")) == settings.PRESETS["default"]
    result = json.loads((_part(tmp_path, "roundtrip-default-1-of-1") / "roundtrip.json").read_text())
    assert result["docs"] == 2 * len(FAKE_SETS["ab1"])
    with pytest.raises(SystemExit, match="default preset only"):
        _capture(tmp_path, "--group", "roundtrip", "--preset", "everything")


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


def test_reference_reads_the_published_run_from_the_frozen_copy_whatever_published_bench_holds(tmp_path, published):
    ref = tmp_path / "ref"
    bench_pipeline.main(["reference", "--frozen", str(published), "--out", str(ref)])
    for rel in ("ab1/scores-ab1-a.json", "piimb/piimb-everything.json"):
        assert (ref / rel).resolve() == (frozen.Frozen(published).published_outputs / rel).resolve()
        assert not _inside_bench(ref / rel)


def _inside_bench(path: Path) -> bool:
    return settings.PUBLISHED.resolve() in path.resolve().parents


def _published_bench(tmp_path, monkeypatch, names: str, data=None) -> Path:
    from pipeline.tests import outputs as made_up
    bench = made_up.write(tmp_path / "published-bench", data if data is not None else made_up.files())
    (bench / "OUTPUTS.json").write_text(json.dumps({"names": names, "files": [], "version": "0.6", "measured": {
        "nullpii": "0.6.1", "model": "lBroth/nullpii@" + "6" * 40, "backend": "cpu"}}))
    monkeypatch.setattr(settings, "PUBLISHED", bench)
    return bench


def _frozen_published_run(tmp_path, monkeypatch) -> Path:
    """A frozen copy holding the published run's outputs where `reference`
    reads them."""
    from pipeline.tests import outputs as made_up
    f = frozen.Frozen(tmp_path / "frozen")
    for rel, value in made_up.published().items():
        if rel.startswith("r3/"):
            name = Path(rel).stem
            target = f.r3_published / (f"{name}.json" if rel.endswith(".json") else f"{name}.log")
        else:
            target = f.published_outputs / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value))
    monkeypatch.setattr(frozen, "verify", lambda r, only=None: frozen.Frozen(r))
    return f.root


def test_compare_with_published_bench_holding_a_run_reads_it_as_a_run(tmp_path, monkeypatch):
    _published_bench(tmp_path, monkeypatch, "run")
    same = run(tmp_path, "same")
    worse = run(tmp_path, "worse", lambda f: f["ab1/scores-ab1-a.json"][DEFAULT].update(keep_rate=0.5))
    report = tmp_path / "report.md"
    args = ["--published-bench", "--frozen", str(tmp_path / "none"), "--report", str(report)]
    assert bench_pipeline.main(["compare", "--new", str(same), *args]) == compare.EXIT_UNCHANGED
    assert bench_pipeline.main(["compare", "--new", str(worse), *args]) == compare.EXIT_WORSE
    assert report.read_text().startswith("**1 worse**")
    assert report.read_text().rstrip().endswith("Compared with published-bench/, a run of the pipeline (0.6).")


def test_compare_with_published_bench_holding_the_published_run_reads_it_like_for_like(tmp_path, monkeypatch):
    from pipeline.tests import outputs as made_up
    _published_bench(tmp_path, monkeypatch, "published", made_up.published())
    root = _frozen_published_run(tmp_path, monkeypatch)
    new = run(tmp_path, "new")
    report = tmp_path / "report.md"
    import tempfile
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    code = bench_pipeline.main(["compare", "--new", str(new), "--published-bench", "--frozen", str(root),
                                "--report", str(report)])
    expected = compare.compare(new, bench_reference(root, tmp_path / "ref"), compare.PUBLISHED)
    assert code == compare.exit_code(expected) and code in (compare.EXIT_CHANGED, compare.EXIT_WORSE)
    text = report.read_text()
    assert "dropped (core regime no longer published)" in text
    assert "Compared with the published 0.5 run" in text
    # The reference was laid out in a directory of its own, and removed.
    assert list((tmp_path / "tmp").iterdir()) == []


def bench_reference(root: Path, out: Path) -> Path:
    bench_pipeline.main(["reference", "--frozen", str(root), "--out", str(out)])
    return out


@pytest.mark.parametrize("args, said", [
    (["--reference", "R", "--frozen", "F"], "--frozen goes with --published-bench"),
    (["--published-bench"], "takes --frozen"),
    (["--published-bench", "--frozen", "F", "--published-names"], "takes --frozen"),
])
def test_compare_refuses_arguments_that_do_not_go_together(tmp_path, args, said):
    with pytest.raises(SystemExit, match=said):
        bench_pipeline.main(["compare", "--new", str(tmp_path), *args])


def test_compare_needs_a_reference_or_published_bench(tmp_path):
    with pytest.raises(SystemExit):
        bench_pipeline.main(["compare", "--new", str(tmp_path)])
    with pytest.raises(SystemExit):
        bench_pipeline.main(["compare", "--new", str(tmp_path), "--reference", "R", "--published-bench"])


def test_score_records_what_the_parts_measured(tmp_path, children, monkeypatch):
    from pipeline import build
    monkeypatch.setattr(build, "cpu_model", lambda: "a CPU")
    _capture_everything(tmp_path)
    bench_pipeline.main(["score", "--frozen", str(tmp_path / "frozen"), "--work", str(tmp_path / "w")])
    measured = json.loads((tmp_path / "w" / "out" / "MEASURED.json").read_text())
    assert measured == {"nullpii": build.nullpii_version(views_root()), "model": build.model_ref(views_root()),
                        "backend": "cpu", "cpus": ["a CPU"]}
    marker = json.loads((_part(tmp_path, "r3-default-1-of-1") / "PART.json").read_text())
    assert marker["measured"]["cpu"] == "a CPU"


def views_root():
    from pipeline import views
    return views.ROOT


def _measured_run(tmp_path, **over):
    run = tmp_path / "out"
    run.mkdir(exist_ok=True)
    m = {"nullpii": "0.6.1", "model": "lBroth/nullpii@" + "6" * 40, "backend": "cpu", "cpus": ["x"], **over}
    (run / "MEASURED.json").write_text(json.dumps(m))
    return run


def test_measured_differs_says_when_a_numbers_pr_is_due_though_nothing_moved(tmp_path, monkeypatch, capsys):
    _published_bench(tmp_path, monkeypatch, "run")
    assert bench_pipeline.main(["measured-differs", "--run", str(_measured_run(tmp_path))]) == 0
    assert bench_pipeline.main(["measured-differs", "--run", str(_measured_run(tmp_path, nullpii="0.6.2"))]) == 3
    assert bench_pipeline.main(["measured-differs", "--run", str(
        _measured_run(tmp_path, model="lBroth/nullpii@" + "7" * 40))]) == 3
    # Another CPU model is no new measurement.
    assert bench_pipeline.main(["measured-differs", "--run", str(_measured_run(tmp_path, cpus=["y"]))]) == 0


def test_measured_differs_against_the_published_run_is_always_due(tmp_path, monkeypatch):
    from pipeline.tests import outputs as made_up
    _published_bench(tmp_path, monkeypatch, "published", made_up.published())
    (settings.PUBLISHED / "OUTPUTS.json").write_text(json.dumps({"names": "published", "files": []}))
    assert bench_pipeline.main(["measured-differs", "--run", str(_measured_run(tmp_path))]) == 3


def test_propose_words_a_run_where_nothing_moved(tmp_path, monkeypatch):
    from pipeline import proposal
    monkeypatch.setattr(proposal, "changed_paths", lambda root: ["packages/eval/published-bench/OUTPUTS.json"])
    report = tmp_path / "report.md"
    report.write_text("**nothing moved**\n")
    run = _measured_run(tmp_path)
    bench_pipeline.main(["propose", "--run", str(run), "--report", str(report), "--compare-exit", "0",
                         "--commit", "c" * 40, "--run-url", "https://github.com/lBroth/nullpii/actions/runs/1",
                         "--runner", "runners", "--title-out", str(tmp_path / "t"), "--body-out", str(tmp_path / "b")])
    assert (tmp_path / "t").read_text().strip().endswith("(nothing moved; measured nullpii 0.6.1)")
    assert "**Nothing moved.**" in (tmp_path / "b").read_text()


def test_measured_differs_against_the_published_run_is_due_even_for_its_own_measurement(tmp_path, monkeypatch):
    from pipeline.tests import outputs as made_up
    _published_bench(tmp_path, monkeypatch, "published", made_up.published())
    (settings.PUBLISHED / "OUTPUTS.json").write_text(json.dumps({"names": "published", "files": []}))
    same = _measured_run(tmp_path, **settings.PUBLISHED_MEASURED)
    assert bench_pipeline.main(["measured-differs", "--run", str(same)]) == 3
