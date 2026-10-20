# SPDX-License-Identifier: Apache-2.0
"""End-to-end invariants: every template in every mode, determinism,
check digits of emitted values, corpus-level rules and file re-verification.
Uses development seeds only (never the release seed)."""

import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import generate  # noqa: E402
from tracegen import checkdigits as cd  # noqa: E402
from tracegen.build import (MIN_TEMPLATES, BuiltDoc, build_corpus, build_one, check_corpus)  # noqa: E402
from tracegen.core import InvariantError, assemble  # noqa: E402
from tracegen.core import F as Frag  # noqa: E402
from tracegen.doc import Mode  # noqa: E402
from tracegen.templates import load_all  # noqa: E402

REG = load_all()
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9 ]{11,40}$")


def emitted_values(bd):
    a = bd.assembled
    return [(s["label"], a.text[s["start"]:s["end"]]) for s in a.spans]


class TestTemplates(unittest.TestCase):
    def test_enough_templates(self):
        self.assertGreaterEqual(len(REG), MIN_TEMPLATES)
        styles = {t.style for t in REG.values()}
        self.assertGreaterEqual(len(styles), 8)
        types = {ty for t in REG.values() for ty in t.types}
        self.assertEqual(types, {"file", "shell", "git", "trace", "log", "http", "ticket"})

    def test_every_template_every_mode(self):
        for tid, tpl in sorted(REG.items()):
            gold_seen = 0
            for mode in (Mode.FULL, Mode.NO_SECRET, Mode.CLEAN):
                for lang in ("en", "it", "de", "fr", "es"):
                    with self.subTest(tid=tid, mode=mode, lang=lang):
                        bd = build_one(tpl, "t", mode, lang, f"test:{tid}:{mode}:{lang}")
                        a = bd.assembled
                        self.assertTrue(300 <= len(a.text) <= 20000)
                        self.assertTrue(a.regions, "every document carries distractors")
                        if mode == Mode.CLEAN:
                            self.assertEqual(a.spans, [])
                        if mode != Mode.FULL:
                            self.assertFalse([s for s in a.spans if s["label"] == "secret"])
                        gold_seen += len(a.spans)
            self.assertGreater(gold_seen, 0, f"{tid} never emits gold")

    def test_deterministic(self):
        for tid in sorted(REG)[:: max(1, len(REG) // 12)]:
            a = build_one(REG[tid], "t", Mode.FULL, "de", f"det:{tid}").assembled
            b = build_one(REG[tid], "t", Mode.FULL, "de", f"det:{tid}").assembled
            self.assertEqual(a.text, b.text)
            self.assertEqual(a.spans, b.spans)
            self.assertEqual(a.regions, b.regions)

    def test_emitted_values_have_valid_check_digits(self):
        checked = {"iban": 0, "card": 0, "vin": 0}
        for tid, tpl in sorted(REG.items()):
            for i in range(3):
                bd = build_one(tpl, "t", Mode.FULL, "en", f"cd:{tid}:{i}")
                for label, val in emitted_values(bd):
                    compact = val.replace(" ", "").replace("-", "")
                    if label == "account_number" and IBAN_RE.match(val) and len(compact) >= 15 and compact[:2].isalpha():
                        self.assertTrue(cd.iban_valid(val), (tid, "iban"))
                        checked["iban"] += 1
                    elif label == "account_number" and compact.isdigit() and (
                            len(compact) == 16 or (len(compact) == 15 and compact[:2] in ("34", "37"))):
                        self.assertTrue(cd.luhn_valid(compact), (tid, "card"))
                        checked["card"] += 1
                    elif label == "private_vehicle_id" and len(val) == 17 and val.isalnum():
                        self.assertTrue(cd.vin_valid(val), (tid, "vin"))
                        checked["vin"] += 1
        for k, v in checked.items():
            self.assertGreater(v, 0, f"no {k} emitted")


class TestCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = 240
        cls.docs = build_corpus(7, cls.n)

    def test_corpus_rules(self):
        check_corpus(self.docs, self.n)
        self.assertEqual(len({d.doc_id for d in self.docs}), self.n)

    def test_template_cap_violation_detected(self):
        one = self.docs[0]
        fake = [BuiltDoc(f"x{i}", one.template_id, one.mode, one.lang, one.assembled, 1, (), ()) for i in range(self.n)]
        with self.assertRaises(InvariantError):
            check_corpus(fake, self.n)

    def test_files_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            gp, dp = os.path.join(tmp, "g.jsonl"), os.path.join(tmp, "d.jsonl")
            generate.write_jsonl(gp, [{"id": d.doc_id, "template_id": d.template_id, "text": d.assembled.text,
                                       "spans": d.assembled.spans} for d in self.docs])
            generate.write_jsonl(dp, [{"id": d.doc_id, "regions": d.assembled.regions} for d in self.docs])
            generate.verify_files(gp, dp, self.n)
            with open(gp, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            with open(dp, encoding="utf-8") as f:
                drows = [json.loads(line) for line in f]
            victim = next(i for i, r in enumerate(rows) if r["spans"] and drows[i]["regions"])
            sp = rows[victim]["spans"][0]
            drows[victim]["regions"].append({"start": sp["start"], "end": sp["end"], "class": "identifier"})
            generate.write_jsonl(dp, drows)
            with self.assertRaises(InvariantError):
                generate.verify_files(gp, dp, self.n)

    def test_offsets_match_values(self):
        for d in self.docs:
            a = d.assembled
            for s, v in zip(a.spans, a.span_values):
                self.assertEqual(a.text[s["start"]:s["end"]], v)


class TestAssembleFromFrag(unittest.TestCase):
    def test_plain_doc_has_no_tags(self):
        a = assemble(Frag("just text"))
        self.assertEqual(a.spans, [])
        self.assertEqual(a.regions, [])


if __name__ == "__main__":
    unittest.main()
