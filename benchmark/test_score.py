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


def _defect(defect_id="d1", keywords=None, location_tokens=None, severity="critical"):
    return {
        "id": defect_id,
        "category": "security",
        "severity": severity,
        "match_any": keywords or ["sql injection", "parameterized query"],
        "location_tokens": location_tokens if location_tokens is not None else ["find_user_by_name"],
    }


class DefectMatchingTests(unittest.TestCase):
    def test_caught_when_phrase_and_location_present(self):
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        review = "In find_user_by_name the input is concatenated — sql injection."
        self.assertEqual(score.defect_is_caught(defect, review), "sql injection")

    def test_case_insensitive(self):
        defect = _defect(keywords=["SQL Injection"], location_tokens=["Find_User_By_Name"])
        review = "find_user_by_name: classic sql injection via concat."
        self.assertEqual(score.defect_is_caught(defect, review), "SQL Injection")

    def test_missed_when_no_phrase(self):
        defect = _defect(keywords=["sql injection", "parameterized query"])
        review = "find_user_by_name looks fine to me, nicely written code."
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_first_matching_phrase_returned(self):
        defect = _defect(keywords=["nope phrase", "sql injection"], location_tokens=["users.py"])
        review = "users.py has a sql injection risk."
        self.assertEqual(score.defect_is_caught(defect, review), "sql injection")

    def test_echoed_fixture_id_does_not_create_spurious_catch(self):
        # The only source of the phrase is the echoed id; after stripping it, and
        # with no genuine phrase, this must be a miss.
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        review = "find_user_by_name 001-sql-injection: the code looks fine."
        self.assertIsNone(score.defect_is_caught(defect, review, "001-sql-injection"))

    def test_real_finding_still_caught_after_id_strip(self):
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        review = "001-sql-injection: find_user_by_name has a clear sql injection via concat."
        self.assertEqual(score.defect_is_caught(defect, review, "001-sql-injection"), "sql injection")


class GroundingTests(unittest.TestCase):
    def test_phrase_without_location_is_not_caught(self):
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        review = "There is a sql injection somewhere in the codebase."
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_phrase_and_location_in_different_blocks_not_caught(self):
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        review = "find_user_by_name is the new function.\n\nSeparately, sql injection is bad in general."
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_phrase_and_location_far_apart_in_block_not_caught(self):
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        filler = "x " * 120  # push the location well beyond PROXIMITY_CHARS
        review = "find_user_by_name " + filler + " sql injection"
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_constant_keyword_blob_scores_nothing(self):
        # Reproduces the critical-review C1 attack: keywords but no location.
        defect = _defect(keywords=["sql injection"], location_tokens=["find_user_by_name"])
        blob = "sql injection command injection hardcoded secret resource leak"
        self.assertIsNone(score.defect_is_caught(defect, blob))


class NegationTests(unittest.TestCase):
    def test_negated_phrase_not_caught(self):
        defect = _defect(keywords=["command injection"], location_tokens=["archive_path"])
        review = "archive_path is safe; there is no command injection risk."
        self.assertIsNone(score.defect_is_caught(defect, review))

    def test_non_negated_phrase_caught(self):
        defect = _defect(keywords=["command injection"], location_tokens=["archive_path"])
        review = "archive_path runs with shell=true — command injection is possible."
        self.assertEqual(score.defect_is_caught(defect, review), "command injection")


class FalsePositiveDetectionTests(unittest.TestCase):
    def test_bulleted_major_finding_is_flagged(self):
        review = "Findings:\n- Major: this variable is poorly named\n"
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_bolded_critical_finding_is_flagged(self):
        review = "**Critical** — unguarded input\nsome prose"
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_markdown_heading_severity_is_flagged(self):
        review = "## Critical: imagined bug in clean code\n"
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_inline_bolded_severity_is_flagged(self):
        review = "This is a **critical** bug in otherwise clean code."
        self.assertEqual(len(score.find_false_positive_findings(review)), 1)

    def test_no_issues_prose_is_not_flagged(self):
        review = "No major issues found. The code looks correct and well tested."
        self.assertEqual(score.find_false_positive_findings(review), [])

    def test_critically_word_is_not_flagged(self):
        review = "This module is critically important to the system."
        self.assertEqual(score.find_false_positive_findings(review), [])

    def test_minor_and_nit_are_not_false_positives(self):
        review = "- Minor: consider a clearer name\n- Nit: trailing whitespace"
        self.assertEqual(score.find_false_positive_findings(review), [])


class ScoreFixtureTests(unittest.TestCase):
    def test_defect_fixture_caught(self):
        fixture = {"id": "999-demo", "title": "t", "defects": [_defect()]}
        review = "find_user_by_name: there is a sql injection risk."
        result = score.score_fixture(fixture, review)
        self.assertEqual(len(result["caught"]), 1)
        self.assertEqual(result["missed"], [])
        self.assertFalse(result["is_control"])
        self.assertEqual(result["caught"][0]["matched_phrase"], "sql injection")

    def test_defect_fixture_missed(self):
        fixture = {"id": "999-demo", "title": "t", "defects": [_defect()]}
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


class FixtureValidationTests(unittest.TestCase):
    def test_defect_without_location_tokens_is_rejected(self):
        meta = {"id": "bad", "defects": [{
            "id": "x", "category": "security", "severity": "critical",
            "match_any": ["sql injection"], "location_tokens": [],
        }]}
        with self.assertRaises(ValueError):
            score._validate_fixture(meta)

    def test_defect_without_match_any_is_rejected(self):
        meta = {"id": "bad", "defects": [{
            "id": "x", "category": "security", "severity": "critical",
            "match_any": [], "location_tokens": ["foo"],
        }]}
        with self.assertRaises(ValueError):
            score._validate_fixture(meta)


class CorpusIntegrityTests(unittest.TestCase):
    """Guard the shipped fixture corpus so a malformed fixture fails loudly."""

    def _fixtures(self):
        fixtures = []
        for entry in sorted(os.listdir(FIXTURES_DIR)):
            fixture_dir = os.path.join(FIXTURES_DIR, entry)
            if os.path.isfile(os.path.join(fixture_dir, "expected.json")):
                fixtures.append((entry, score.load_fixture(fixture_dir)))
        return fixtures

    def test_every_shipped_fixture_loads_and_validates(self):
        fixtures = self._fixtures()
        self.assertTrue(fixtures, "no fixtures discovered — corpus is missing")
        for entry, fixture in fixtures:
            self.assertTrue(fixture["diff_text"].strip(), "%s has an empty diff" % entry)
            self.assertEqual(fixture["id"], entry)

    def test_corpus_has_multiple_controls(self):
        controls = [entry for entry, fixture in self._fixtures() if not fixture["defects"]]
        self.assertGreaterEqual(len(controls), 2, "corpus should have several controls incl. near-misses")

    def test_each_defect_fixture_is_self_consistent(self):
        # A review built from the defect's own description + its location tokens
        # must be caught — proves the phrases and location tokens are coherent and
        # that the corpus does not silently contain unscoreable defects.
        for entry, fixture in self._fixtures():
            for defect in fixture["defects"]:
                review = (
                    "- **%s**: in %s — %s"
                    % (defect["severity"], " ".join(defect["location_tokens"]), defect["description"])
                )
                self.assertIsNotNone(
                    score.defect_is_caught(defect, review, fixture["id"]),
                    "defect %s in %s is not caught by a review of its own description"
                    % (defect["id"], entry),
                )


class AntiGamingCorpusTests(unittest.TestCase):
    """End-to-end proof that the two known gaming strings score 0 catch-rate.

    These reproduce the bypasses the critical/code reviewers demonstrated against
    the original keyword scorer and assert they now FAIL against the real corpus.
    """

    def _corpus(self):
        fixtures = []
        for entry in sorted(os.listdir(FIXTURES_DIR)):
            fixture_dir = os.path.join(FIXTURES_DIR, entry)
            if os.path.isfile(os.path.join(fixture_dir, "expected.json")):
                fixtures.append(score.load_fixture(fixture_dir))
        return fixtures

    def _catch_rate(self, review_for):
        results = [score.score_fixture(f, review_for(f)) for f in self._corpus()]
        return score.aggregate(results)

    def test_constant_keyword_blob_scores_zero(self):
        # A reviewer that emits every defect phrase but never cites a location —
        # the original "perfect score without reading the code" attack (C1).
        phrases = []
        for fixture in self._corpus():
            for defect in fixture["defects"]:
                phrases.extend(defect["match_any"])
        blob = " ".join(phrases)
        summary = self._catch_rate(lambda _f: blob)
        self.assertEqual(summary["caught"], 0)
        self.assertEqual(summary["catch_rate"], 0.0)

    def test_defect_dismissing_review_scores_zero(self):
        # A reviewer that cites the location AND the phrase but DISMISSES it
        # ("looks correct, no <phrase>") — the code reviewer's demo that scored
        # 67% at a true 0%. Negation handling must now make this a clean miss.
        def dismiss(fixture):
            lines = []
            for defect in fixture["defects"]:
                loc = " ".join(defect["location_tokens"])
                for phrase in defect["match_any"]:
                    lines.append("%s looks correct; there is no %s here." % (loc, phrase))
            return "\n".join(lines) or "Looks correct, no issues."

        summary = self._catch_rate(dismiss)
        self.assertEqual(summary["caught"], 0)
        self.assertEqual(summary["catch_rate"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
