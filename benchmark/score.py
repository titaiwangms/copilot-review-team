#!/usr/bin/env python3
"""Scoring logic for the catch-rate benchmark.

This module is deliberately free of subprocess / CLI concerns so it can be unit
tested in isolation. It answers one question: given a reviewer's plain-text
output and a fixture's list of expected (planted) defects, which defects did the
reviewer CATCH, which did it MISS, and — for the clean control — did it raise
false-positive findings?

A defect is considered "caught" when any of its `match_any` keywords appears
(case-insensitively, as a substring) anywhere in the reviewer's output. Keyword
matching is intentionally simple and transparent: the fixtures own the keyword
lists, so tightening or loosening a match is a data edit, not a code change.
"""
import json
import os
import re

# A clean-control finding is treated as a false positive only when the reviewer
# labels it at this severity or higher. Minor/Nit style suggestions on correct
# code are expected and are NOT penalized.
FALSE_POSITIVE_SEVERITY_RE = re.compile(
    r"(?im)^\s*(?:[-*+]\s*)?(?:\d+[.)]\s*)?(?:\*\*|__)?\s*(critical|major)\b"
)


def load_fixture(fixture_dir):
    """Load one fixture directory into a dict.

    Expects `expected.json` and `diff.patch` inside `fixture_dir`. Returns a dict
    with keys: id, title, language, defects, note, diff_text, dir.
    """
    expected_path = os.path.join(fixture_dir, "expected.json")
    diff_path = os.path.join(fixture_dir, "diff.patch")
    if not os.path.isfile(expected_path):
        raise FileNotFoundError(
            "fixture %r is missing expected.json" % fixture_dir
        )
    if not os.path.isfile(diff_path):
        raise FileNotFoundError(
            "fixture %r is missing diff.patch" % fixture_dir
        )
    with open(expected_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    with open(diff_path, encoding="utf-8") as handle:
        diff_text = handle.read()

    meta.setdefault("id", os.path.basename(os.path.normpath(fixture_dir)))
    meta.setdefault("defects", [])
    meta["diff_text"] = diff_text
    meta["dir"] = fixture_dir
    _validate_fixture(meta)
    return meta


def _validate_fixture(meta):
    """Fail loudly on a malformed fixture so corpus mistakes surface early."""
    for defect in meta["defects"]:
        missing = [k for k in ("id", "category", "severity", "match_any") if k not in defect]
        if missing:
            raise ValueError(
                "fixture %r defect %r missing keys: %s"
                % (meta["id"], defect.get("id", "?"), ", ".join(missing))
            )
        if not defect["match_any"]:
            raise ValueError(
                "fixture %r defect %r has an empty match_any list"
                % (meta["id"], defect["id"])
            )


def strip_fixture_id(review_text, fixture_id):
    """Remove the fixture id (and its spaced/joined variants) from review text.

    Fixture ids are human-readable and encode the defect category (e.g.
    `001-sql-injection`), so an id echoed into a review would otherwise satisfy
    keyword matches like "injection" or "secret" without the reviewer actually
    diagnosing anything. Stripping the id closes that gaming/pollution vector so
    a catch reflects the reviewer's analysis, not the fixture's name.
    """
    cleaned = review_text.lower()
    for variant in (fixture_id.lower(), fixture_id.replace("-", " ").lower(), fixture_id.replace("-", "").lower()):
        if variant:
            cleaned = cleaned.replace(variant, " ")
    return cleaned


def defect_is_caught(defect, review_text, fixture_id=""):
    """Return the first keyword that matched, or None if the defect was missed.

    The fixture id is stripped from the review text first (see strip_fixture_id)
    so an echoed id cannot produce a spurious catch.
    """
    haystack = strip_fixture_id(review_text, fixture_id) if fixture_id else review_text.lower()
    for keyword in defect["match_any"]:
        if keyword.lower() in haystack:
            return keyword
    return None


def find_false_positive_findings(review_text):
    """Return the reviewer lines that look like Major/Critical findings.

    Used only on the clean control. This is a transparent heuristic, not ground
    truth: it surfaces the offending lines so a human can confirm them. See the
    benchmark README's "Known limitations" section.
    """
    matches = []
    for line in review_text.splitlines():
        if FALSE_POSITIVE_SEVERITY_RE.match(line):
            matches.append(line.strip())
    return matches


def score_fixture(fixture, review_text):
    """Score a single reviewer output against one fixture.

    Returns a dict describing caught/missed defects and (for the clean control)
    false-positive finding lines.
    """
    caught = []
    missed = []
    for defect in fixture["defects"]:
        matched_keyword = defect_is_caught(defect, review_text, fixture["id"])
        record = {
            "id": defect["id"],
            "category": defect["category"],
            "severity": defect["severity"],
        }
        if matched_keyword is not None:
            record["matched_keyword"] = matched_keyword
            caught.append(record)
        else:
            missed.append(record)

    is_control = len(fixture["defects"]) == 0
    false_positives = find_false_positive_findings(review_text) if is_control else []

    return {
        "id": fixture["id"],
        "title": fixture.get("title", fixture["id"]),
        "is_control": is_control,
        "expected_count": len(fixture["defects"]),
        "caught": caught,
        "missed": missed,
        "false_positives": false_positives,
    }


def aggregate(fixture_results):
    """Roll per-fixture results into an overall scorecard."""
    total_defects = 0
    total_caught = 0
    total_false_positives = 0
    for result in fixture_results:
        total_defects += result["expected_count"]
        total_caught += len(result["caught"])
        total_false_positives += len(result["false_positives"])

    catch_rate = (total_caught / total_defects) if total_defects else None
    return {
        "fixtures": len(fixture_results),
        "total_defects": total_defects,
        "caught": total_caught,
        "missed": total_defects - total_caught,
        "catch_rate": catch_rate,
        "false_positives": total_false_positives,
    }
