# SPDX-License-Identifier: Apache-2.0
"""`reproduce` checks every output the frozen predictions give against the
published one, and names each that differs; and PIIMB's report says
where the tool sits on the leaderboard."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import recipe, reproduce, settings
from pipeline.frozen import Frozen


def _report(name: str) -> dict:
    return {"name": name, "_macro": {"x": {"f2": 0.758}}}


@pytest.fixture
def scored(tmp_path, monkeypatch):
    """Scorers that write fixed outputs, and a published copy equal to them;
    returns (frozen copy, published-bench, what each scorer was asked)."""
    asked: list[tuple] = []

    def score_ab1(checkpoints, baseline, gold_dir, out_dir):
        asked.append(("ab1", baseline, gold_dir))
        for key in settings.AB1_GOLD:
            (out_dir).mkdir(parents=True, exist_ok=True)
            (out_dir / f"scores-{key}.json").write_text(json.dumps(_report(key)))

    def score_r3(results, baseline, openmed, out_dir, runs=recipe.R3_RUNS):
        asked.append(("r3", baseline, tuple(r.name for r in runs)))
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in runs:
            (out_dir / f"{r.name}.json").write_text(json.dumps(_report(r.name)))

    def verdicts(reports, baseline, others, which=recipe.VERDICTS):
        asked.append(("verdicts", baseline, others))
        return {v.name: f"verdict {v.name}\n" for v in which}

    def score_piimb(sentences, spans, leaderboard, name, out):
        asked.append(("piimb", sentences, spans.name, name))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"name": name, "avg_f2": 0.851}))

    for name, fn in [("score_ab1", score_ab1), ("score_r3", score_r3), ("verdicts", verdicts), ("score_piimb", score_piimb)]:
        monkeypatch.setattr(recipe, name, fn)
    f = Frozen(tmp_path / "frozen")
    f.r3_published.mkdir(parents=True)
    for r in (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS):
        (f.r3_published / f"{r.name}.json").write_text(json.dumps(_report(r.name)))
    for v in (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS):
        (f.r3_published / f"{v.name}.log").write_text(f"verdict {v.name}\n")
    bench = tmp_path / "published-bench"
    (bench / "ab1").mkdir(parents=True)
    for key in settings.AB1_GOLD:
        (bench / "ab1" / f"scores-{key}.json").write_text(json.dumps(_report(key)))
    (bench / "piimb").mkdir()
    (bench / "piimb" / "piimb-everything.json").write_text(json.dumps({"name": "nullpii-everything", "avg_f2": 0.851}))
    return f, bench, asked


def test_the_published_run_reproduces_when_every_output_is_the_same(tmp_path, scored):
    f, bench, asked = scored
    reproduce.check(f, tmp_path / "work", bench)
    assert ("r3", settings.PUBLISHED_R3_CORE_LABELS_BASELINE, tuple(r.name for r in recipe.CORE_LABEL_RUNS)) in asked
    # The sets come from the checked copy, never from what results/ holds.
    assert ("ab1", settings.PUBLISHED_AB1_BASELINE, f.dataset("ab1")) in asked
    assert ("piimb", f.piimb_sentences, f.piimb_published_spans.name, settings.tool_name("everything")) in asked
    # 11 reports of the recipe and 3 on core labels: the 14 published.
    assert len(recipe.R3_RUNS) + len(recipe.CORE_LABEL_RUNS) == len(list(f.r3_published.glob("*.json"))) == 14


@pytest.mark.parametrize("spoil, said", [
    (lambda f, b: (b / "ab1" / "scores-ab1-b2.json").write_text(json.dumps(_report("other"))), "scores-ab1-b2.json: /name"),
    (lambda f, b: (f.r3_published / "char-r3-lodo-r3-piilo.json").write_text("{}"), "char-r3-lodo-r3-piilo.json: /_macro"),
    (lambda f, b: (f.r3_published / "char-r3-defcore.json").write_text("{}"), "char-r3-defcore.json: /_macro"),
    (lambda f, b: (f.r3_published / "verdict-en.log").write_text("another verdict"), "verdict-en: the verdict text differs"),
    (lambda f, b: (f.r3_published / "sens-default-core-verdict.log").write_text("x"), "sens-default-core-verdict: the verdict"),
    (lambda f, b: (b / "piimb" / "piimb-everything.json").write_text('{"name": "nullpii-everything", "avg_f2": 0.85}'),
     "piimb-everything.json: /avg_f2"),
])
def test_any_output_that_differs_is_named(tmp_path, scored, spoil, said):
    f, bench, _ = scored
    spoil(f, bench)
    with pytest.raises(AssertionError, match=said):
        reproduce.check(f, tmp_path / "work", bench)


@pytest.mark.parametrize("spoil, said", [
    (lambda f: (f.r3_published / "char-r3-new.json").write_text("{}"), "published report not in the recipe: char-r3-new"),
    (lambda f: (f.r3_published / "verdict-new.log").write_text("x"), "published verdict not in the recipe: verdict-new"),
    (lambda f: (f.r3_published / "sens-default-core.json").unlink(), "report of the recipe not published: sens-default-core"),
    (lambda f: (f.r3_published / "verdict.log").unlink(), "verdict of the recipe not published: verdict"),
])
def test_the_recipe_declares_exactly_the_published_r3_outputs(tmp_path, scored, spoil, said):
    f, bench, _ = scored
    spoil(f)
    with pytest.raises(AssertionError, match=said):
        reproduce.check(f, tmp_path / "work", bench)


def test_the_core_label_verdict_leaves_out_its_own_baseline():
    others = reproduce._core_label_others()
    assert settings.PUBLISHED_R3_CORE_LABELS_BASELINE not in others
    assert others[0] == settings.PUBLISHED_R3_BASELINE
    assert set(others) == ({settings.PUBLISHED_R3_BASELINE, *settings.PUBLISHED_R3_OTHER_NULLPII}
                           - {settings.PUBLISHED_R3_CORE_LABELS_BASELINE})


def _piimb_inputs(root: Path, board: dict[str, float]) -> tuple[Path, Path, Path]:
    tasks = ["ai4privacy-en", "ai4privacy-multi", "gretel", "mapa-eur-lex", "nemotron-pii", "privy"]
    data, pred, leaderboard = root / "data.jsonl", root / "pred.jsonl", root / "board"
    data.write_text("".join(json.dumps({"task_name": t, "text": "abcdefghij", "entities": [{"start": 0, "end": 5}]}) + "\n"
                            for t in tasks))
    pred.write_text("".join(json.dumps({"dataset": t, "idx": 0, "spans": [[0, 4]]}) + "\n" for t in tasks))
    for model, f2 in board.items():
        (leaderboard / model).mkdir(parents=True)
        for t in tasks:
            (leaderboard / model / f"{t}.json").write_text(json.dumps({"scores": {"test": [{"f2": f2}]}}))
    return data, pred, leaderboard


def test_the_piimb_report_says_where_the_tool_sits_on_the_leaderboard(tmp_path):
    data, pred, leaderboard = _piimb_inputs(tmp_path, {"better": 0.9, "worse-a": 0.5, "worse-b": 0.4})
    out = tmp_path / "piimb.json"
    subprocess.run([sys.executable, "-I", str(settings.PIIMB_SCORE), "score", "--data", str(data), "--pred", str(pred),
                    "--name", "t", "--leaderboard", str(leaderboard), "--out", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    report = json.loads(out.read_text())
    # Precision 1, recall 0.8 on every task: F2 0.833, behind one row of three.
    assert report["avg_f2"] == pytest.approx(5 * 0.8 / (4 + 0.8))
    assert report["leaderboard"] == {"rank": 2, "of": 4}
    assert "without" not in report


def test_the_piimb_report_gives_the_average_and_place_without_a_task(tmp_path):
    data, pred, leaderboard = _piimb_inputs(tmp_path, {"better": 0.9, "worse": 0.5})
    # The better row is far behind on every task but nemotron-pii.
    for t in ["ai4privacy-en", "ai4privacy-multi", "gretel", "mapa-eur-lex", "privy"]:
        (leaderboard / "better" / f"{t}.json").write_text(json.dumps({"scores": {"test": [{"f2": 0.1}]}}))
    (leaderboard / "better" / "nemotron-pii.json").write_text(json.dumps({"scores": {"test": [{"f2": 1.0}]}}))
    out = tmp_path / "piimb.json"
    subprocess.run([sys.executable, "-I", str(settings.PIIMB_SCORE), "score", "--data", str(data), "--pred", str(pred),
                    "--name", "t", "--leaderboard", str(leaderboard), "--out", str(out), "--leave-out", "nemotron-pii"],
                   check=True, stdout=subprocess.DEVNULL)
    report = json.loads(out.read_text())
    assert report["without"]["task"] == "nemotron-pii"
    assert report["without"]["avg_f2"] == pytest.approx(5 * 0.8 / (4 + 0.8))
    assert report["without"]["leaderboard"] == {"rank": 1, "of": 3}


def test_a_leaderboard_model_without_every_task_is_an_error(tmp_path):
    data, pred, leaderboard = _piimb_inputs(tmp_path, {"partial": 0.9})
    (leaderboard / "partial" / "privy.json").unlink()
    done = subprocess.run([sys.executable, "-I", str(settings.PIIMB_SCORE), "score", "--data", str(data),
                           "--pred", str(pred), "--leaderboard", str(leaderboard)], capture_output=True, text=True)
    assert done.returncode != 0 and "partial has no F2 for every task" in done.stderr
