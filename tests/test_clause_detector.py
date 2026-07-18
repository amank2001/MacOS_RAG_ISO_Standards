"""Tests for clause detection logic."""

from __future__ import annotations

import unittest

from indexer.parsers.clause_detector import (
    detect_clause_from_line,
    detect_standard_id,
    parent_clause_number,
    split_text_by_clauses,
)


class ClauseDetectorTests(unittest.TestCase):
    def test_detect_numeric_clause(self):
        result = detect_clause_from_line("4.1 Context of the organization", 5)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.clause_number, "4.1")
        self.assertEqual(result.title, "Context of the organization")

    def test_detect_annex_clause(self):
        result = detect_clause_from_line("Annex A — Information security controls", 40)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.clause_number, "Annex A")

    def test_detect_annex_subclause(self):
        result = detect_clause_from_line("A.5.1 Policies for information security", 41)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.clause_number, "A.5.1")

    def test_detect_figure(self):
        result = detect_clause_from_line("Figure 1 — Process model", 10)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.clause_number, "Figure 1")

    def test_standard_id_from_filename(self):
        sid = detect_standard_id("", "ISO_27001_2022.pdf")
        self.assertIsNotNone(sid)
        assert sid is not None
        self.assertIn("27001", sid)

    def test_standard_id_from_filename_hyphen(self):
        sid = detect_standard_id("", "ISO-27001.pdf")
        self.assertIsNotNone(sid)
        assert sid is not None
        self.assertIn("27001", sid)

    def test_standard_id_from_filename_iso_iec(self):
        sid = detect_standard_id("", "ISO_IEC_27001_2022.pdf")
        self.assertIsNotNone(sid)
        assert sid is not None
        self.assertIn("27001", sid)

    def test_standard_id_from_text_still_works(self):
        sid = detect_standard_id("This document is ISO 9001:2015 compliant.", "random.pdf")
        self.assertIsNotNone(sid)
        assert sid is not None
        self.assertIn("9001", sid)

    def test_standard_id_part_number_preserved(self):
        sid = detect_standard_id("", "ISO 27001-1_2022.pdf")
        self.assertIsNotNone(sid)
        assert sid is not None
        self.assertIn("27001-1", sid)

    def test_parent_clause(self):
        self.assertEqual(parent_clause_number("4.1.2"), "4.1")
        self.assertIsNone(parent_clause_number("4"))

    def test_split_by_clauses(self):
        pages = [
            (1, "1 Scope\nThis is scope text."),
            (2, "4.1 Context\nThe organization shall determine."),
        ]
        segments = split_text_by_clauses(pages)
        self.assertGreaterEqual(len(segments), 2)


if __name__ == "__main__":
    unittest.main()
