#!/usr/bin/env python3
"""Unit tests for the catch-rate scorer.

Run directly (`python3 benchmark/test_score.py`) or via unittest discovery.
Standard-library only, consistent with scripts/.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _defect(defect_id="d1", keywords=None, severity="critical"):
    return {
        "id": defect_id,
        "category": "security",
        "severity": severity,
        "match_any": keywords or ["sql injection", "parameterized"],
    }


class DefectMatchingTests(unittest.TestCase):
    def test_caught_when_keyword_present_case_insensitive(self):
        defect = _defect(keywords=["SQL Injection"])
        review = "This is a classic sql injection via string concat."
        self.assertEqual(score.defect_is_caught(defect, review), "SQL Injection")

    def test_missed_when_no_keyword_present(self):
        defect = _defect(keywords=["sql injection", "parameterized"])
        review = "Looks fine to me, nicely written code."
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_first_matching_keyword_is_returned(self):
        defect = _defect(keywords=["nope", "injection", "concatenat"])
        review = "Risk of injection here."
        self.assertEqual(score.defect_is_caught(defect, review), "injection")

    def test_echoed_fixture_id_does_not_create_spurious_catch(self):
        defect = _defect(keywords=["injection", "secret"])
        review = "review of 001-sql-injection: the code is fine, nothing to flag."
        self.assertIsNone(score.defect_is_caught(defect, review, "001-sql-injection"))

    def test_real_finding_still_caught_after_id_strip(self):
        defect = _defect(keywords=["injection"])
        review = "001-sql-injection: this is a clear injection risk via concat."
        self.assertEqual(score.defect_is_caught(defect, review, "001-sql-injection"), "injection")


class FalsePositiveDetectionTests(unittest.TestCase):
    def test_bulleted_major_finding_is_flagged(self):
        review = "Findings:\n- Major: this variable is poorly named\n"
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_bolded_critical_finding_is_flagged(self):
        review = "**Critical** — unguarded input\nsome prose"
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_no_issues_prose_is_not_flagged(self):
        review = "No major issues found. The code looks correct and well tested."
        self.assertEqual(score.find_false_positive_findings(review), [])

    def test_minor_and_nit_are_not_false_positives(self):
        review = "- Minor: consider a clearer name\n- Nit: trailing whitespace"
        self.assertEqual(score.find_false_positive_findings(review), [])


class ScoreFixtureTests(unittest.TestCase):
    def test_defect_fixture_caught(self):
        fixture = {"id": "f", "title": "t", "defects": [_defect()]}
        review = "There is a sql injection risk."
        result = score.score_fixture(fixture, review)
        self.assertEqual(len(result["caught"]), 1)
        self.assertEqual(result["missed"], [])
        self.assertFalse(result["is_control"])

    def test_defect_fixture_missed(self):
        fixture = {"id": "f", "title": "t", "defects": [_defect()]}
        result = score.score_fixture(fixture, "no problems here")
        self.assertEqual(result["caught"], [])
        self.assertEqual(len(result["missed"]), 1)

    def test_control_counts_false_positives(self):
        fixture = {"id": "ctrl", "title": "t", "defects": []}
        review = "- Critical: imagined bug\nsome prose"
        result = score.score_fixture(fixture, review)
        self.assertTrue(result["is_control"])
        self.assertEqual(len(result["false_positives"]), 1)


class AggregateTests(unittest.TestCase):
    def test_catch_rate_and_counts(self):
        results = [
            {"expected_count": 1, "caught": [{}], "missed": [], "false_positives": []},
            {"expected_count": 1, "caught": [], "missed": [{}], "false_positives": []},
            {"expected_count": 0, "caught": [], "missed": [], "false_positives": [{}]},
        ]
        summary = score.aggregate(results)
        self.assertEqual(summary["total_defects"], 2)
        self.assertEqual(summary["caught"], 1)
        self.assertEqual(summary["missed"], 1)
        self.assertAlmostEqual(summary["catch_rate"], 0.5)
        self.assertEqual(summary["false_positives"], 1)

    def test_catch_rate_none_when_no_defects(self):
        summary = score.aggregate([{"expected_count": 0, "caught": [], "missed": [], "false_positives": []}])
        self.assertIsNone(summary["catch_rate"])


class CorpusIntegrityTests(unittest.TestCase):
    """Guard the shipped fixture corpus so a malformed fixture fails loudly."""

    def test_every_shipped_fixture_loads_and_validates(self):
        found = False
        for entry in sorted(os.listdir(FIXTURES_DIR)):
            fixture_dir = os.path.join(FIXTURES_DIR, entry)
            if not os.path.isfile(os.path.join(fixture_dir, "expected.json")):
                continue
            found = True
            fixture = score.load_fixture(fixture_dir)
            self.assertTrue(fixture["diff_text"].strip(), "%s has an empty diff" % entry)
            self.assertEqual(fixture["id"], entry)
        self.assertTrue(found, "no fixtures discovered — corpus is missing")

    def test_corpus_has_a_clean_control(self):
        controls = []
        for entry in sorted(os.listdir(FIXTURES_DIR)):
            fixture_dir = os.path.join(FIXTURES_DIR, entry)
            if not os.path.isfile(os.path.join(fixture_dir, "expected.json")):
                continue
            if not score.load_fixture(fixture_dir)["defects"]:
                controls.append(entry)
        self.assertTrue(controls, "corpus must include at least one clean control fixture")


if __name__ == "__main__":
    unittest.main(verbosity=2)
