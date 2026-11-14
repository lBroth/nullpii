# SPDX-License-Identifier: Apache-2.0
"""`kind_split.py` counts each tool's unmasked secrets of one gold kind and
of the rest by the scorer's own rule, and refuses a split with nothing on
one side. It needs the scorer's numpy (requirements-pipeline.txt), and
fails where it is not installed rather than being skipped."""
import json
import subprocess
import sys

import pytest

from pipeline import settings

sys.path.insert(0, str(settings.SCRIPTS / "ab1"))

import kind_split  # noqa: E402

TEXT = "id=0f8fe0c2 key=sk_live_abc pw=hunter22"
UUID, KEY, PW = (3, 11), (16, 27), (31, 39)


def _doc(*items):
    return {"text": TEXT, "items": [{"start": s, "end": e, "class": "MUST_MASK", "category": "secret", "kind": k}
                                     for (s, e), k in items]}


GOLD = [_doc((UUID, "UUID"), (KEY, "Key")), _doc((PW, "Password"))]


def test_each_side_is_counted_by_the_scorers_rule():
    spans = {
        # Masks the key; the UUID and the password leak.
        "a": [[(KEY[0], KEY[1], "secret")], []],
        # Masks every letter and digit of the UUID, the `=`-free value; the
        # punctuation left around it reveals nothing.
        "b": [[(UUID[0], UUID[1], "x"), (KEY[0], KEY[1] - 1, "x")], [(PW[0], PW[1], "x")]],
    }
    report = kind_split.split(GOLD, spans, "UUID")
    assert (report["items"], report["other_items"]) == (1, 2)
    assert report["tools"]["a"] == {"leaked": 1, "leaked_other": 1, "leak": 1.0, "leak_other": 0.5}
    # A key with one character left unmasked leaks.
    assert report["tools"]["b"] == {"leaked": 0, "leaked_other": 1, "leak": 0.0, "leak_other": 0.5}


def test_a_split_with_nothing_on_one_side_is_refused():
    with pytest.raises(SystemExit, match="nothing to split"):
        kind_split.split(GOLD, {"a": [[], []]}, "Token")


def test_only_secrets_are_split():
    gold = [{"text": TEXT, "items": [{"start": 0, "end": 2, "class": "MUST_MASK", "category": "person", "kind": "UUID"},
                                     {"start": 0, "end": 2, "class": "MUST_KEEP", "category": "secret", "kind": "UUID"}]}]
    assert kind_split.secret_items(gold[0]) == []


def test_the_script_writes_counts_and_prints_no_row(tmp_path):
    gold = tmp_path / "b1.jsonl"
    gold.write_text("".join(json.dumps(d) + "\n" for d in GOLD))
    cps = tmp_path / "cp"
    cps.mkdir()
    (cps / "t-ab1-b1.jsonl").write_text("".join(json.dumps({"idx": i, "spans": []}) + "\n" for i in range(2)))
    out = tmp_path / "split.json"
    printed = subprocess.run([sys.executable, str(settings.KIND_SPLIT), "--gold", str(gold), "--dataset", "ab1-b1",
                              "--kind", "UUID", "--checkpoints", str(cps), "--out", str(out)],
                             capture_output=True, text=True, check=True).stdout
    assert json.loads(printed) == {"kind": "UUID", "items": 1, "other_items": 2}
    assert "sk_live" not in printed and "sk_live" not in out.read_text()
    assert set(json.loads(out.read_text())["tools"]) == {"t", "t+agent"}


def test_the_agent_row_drops_the_spans_of_the_readable_categories(tmp_path):
    gold = tmp_path / "b1.jsonl"
    gold.write_text("".join(json.dumps(d) + "\n" for d in GOLD))
    cps = tmp_path / "cp"
    cps.mkdir()
    # The UUID masked under a category the agent policy leaves readable.
    rows = [{"idx": 0, "spans": [[UUID[0], UUID[1], "private_date", 0.9]]}, {"idx": 1, "spans": []}]
    (cps / "t-ab1-b1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "split.json"
    subprocess.run([sys.executable, str(settings.KIND_SPLIT), "--gold", str(gold), "--dataset", "ab1-b1",
                    "--kind", "UUID", "--checkpoints", str(cps), "--out", str(out)], capture_output=True, check=True)
    tools = json.loads(out.read_text())["tools"]
    assert (tools["t"]["leaked"], tools["t+agent"]["leaked"]) == (0, 1)
