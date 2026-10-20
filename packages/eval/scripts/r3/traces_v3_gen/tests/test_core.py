# SPDX-License-Identifier: Apache-2.0
"""Segment model and invariant checks."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracegen.core import (Assembled, F, InvariantError, Seg, T, assemble, check_document, esc_json, grid,  # noqa: E402
                           numbered, prefix_lines, table)


def G(label, text):
    return Seg(text, label=label)


def D(cls, text):
    return Seg(text, cls=cls)


class TestSeg(unittest.TestCase):
    def test_labels_validated(self):
        with self.assertRaises(ValueError):
            Seg("x", label="not_a_label")
        with self.assertRaises(ValueError):
            Seg("x", cls="not_a_class")
        with self.assertRaises(ValueError):
            Seg("x", label="secret", cls="placeholder")
        with self.assertRaises(ValueError):
            Seg("", label="secret")
        with self.assertRaises(ValueError):
            Seg(" padded", label="private_email")

    def test_template_slots(self):
        f = T("a ⟦x⟧ b ⟦y⟧", x=G("private_email", "u@d.it"), y="z")
        self.assertEqual("".join(s.text for s in f), "a u@d.it b z")
        with self.assertRaises(KeyError):
            T("⟦missing⟧")
        with self.assertRaises(KeyError):
            T("no slots", extra="x")


class TestAssemble(unittest.TestCase):
    def test_offsets_recorded_at_insertion(self):
        frag = F("name: ", G("private_person", "Anna Weber"), " ip ", D("reserved_ip", "127.0.0.1"),
                 " again ", G("private_person", "Anna Weber"))
        a = assemble(frag)
        check_document(a)
        self.assertEqual([(s["start"], s["end"]) for s in a.spans], [(6, 16), (36, 46)])
        for s in a.spans:
            self.assertEqual(a.text[s["start"]:s["end"]], "Anna Weber")
        self.assertEqual(a.text[a.regions[0]["start"]:a.regions[0]["end"]], "127.0.0.1")

    def test_prefix_lines_keeps_offsets(self):
        pem = "-----BEGIN KEY-----\nAAAA\nBBBB\n-----END KEY-----"
        frag = F("key:\n", G("secret", pem), "\n", G("private_ip", "10.1.2.3"), "\n")
        out = prefix_lines(frag, "  ⎿  ", "     ")
        a = assemble(out)
        check_document(a)
        self.assertEqual(len(a.spans), 2)
        self.assertTrue(a.text[a.spans[0]["start"]:a.spans[0]["end"]].startswith("-----BEGIN KEY-----\n     AAAA"))
        self.assertEqual(a.text[a.spans[1]["start"]:a.spans[1]["end"]], "10.1.2.3")

    def test_json_escaping_keeps_offsets(self):
        frag = F('{"t":"', esc_json(F("line1\n", G("private_person", "O'Brien"), "\t\"q\" ", G("secret", "a\\b"))), '"}')
        a = assemble(frag)
        check_document(a)
        obj = json.loads(a.text)
        self.assertIn("O'Brien", obj["t"])
        self.assertEqual(a.text[a.spans[1]["start"]:a.spans[1]["end"]], "a\\\\b")

    def test_tables_preserve_tags(self):
        rows = [["NAME", "IP"], ["web", G("private_ip", "10.0.0.7")], ["db", D("reserved_ip", "127.0.0.1")]]
        for frag in (table(rows), grid(rows[0], rows[1:], "psql"), grid(rows[0], rows[1:], "mysql"),
                     grid(rows[0], rows[1:], "md"), numbered(table(rows))):
            a = assemble(frag)
            check_document(a)
            self.assertEqual(len(a.spans), 1)
            self.assertEqual(len(a.regions), 1)


class TestInvariantChecker(unittest.TestCase):
    def test_detects_text_mismatch(self):
        a = Assembled("hello world", [{"start": 0, "end": 5, "label": "private_person"}], [], ["hellx"], [])
        with self.assertRaises(InvariantError):
            check_document(a)

    def test_detects_gold_overlap(self):
        a = Assembled("abcdefgh", [{"start": 0, "end": 4, "label": "secret"}, {"start": 3, "end": 6, "label": "secret"}],
                      [], ["abcd", "def"], [])
        with self.assertRaises(InvariantError):
            check_document(a)

    def test_detects_nested_gold_region_overlap(self):
        a = Assembled("abcdefghij", [{"start": 2, "end": 3, "label": "secret"}, {"start": 6, "end": 7, "label": "secret"}],
                      [{"start": 0, "end": 10, "class": "identifier"}], ["c", "g"], ["abcdefghij"])
        with self.assertRaises(InvariantError):
            check_document(a)

    def test_detects_invalid_label(self):
        a = Assembled("abc", [{"start": 0, "end": 3, "label": "person"}], [], ["abc"], [])
        with self.assertRaises(InvariantError):
            check_document(a)

    def test_adjacent_is_fine(self):
        a = assemble(F(G("private_ip", "10.0.0.1"), ":", D("identifier", "5432"), G("private_person", "x")))
        check_document(a)


if __name__ == "__main__":
    unittest.main()
