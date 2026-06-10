#!/usr/bin/env python3
"""Scoring logic for the catch-rate benchmark.

This module is deliberately free of subprocess / CLI concerns so it can be unit
tested in isolation. It answers one question: given a reviewer's plain-text
output and a fixture's list of expected (planted) defects, which defects did the
reviewer CATCH, which did it MISS, and — for a clean control — did it raise
false-positive findings?

Why a catch requires a LOCATED finding
--------------------------------------
A naive "does any keyword appear?" test is trivially gameable: a reviewer that
emits a constant blob of defect keywords without reading the code would score a
perfect catch-rate, defeating the whole point of the benchmark (make review
quality *falsifiable*). So a defect is "caught" only when the review contains, in
a single block (paragraph), ALL of:

  1. one of the defect's specific `match_any` phrases (multi-word, defect-specific
     — NOT bare nouns like "injection" that appear in unrelated prose), AND
  2. that phrase in a NON-negated context (so "there is no SQL injection" does not
     count as catching the SQL-injection defect), AND
  3. a reference to the defect's `location` — one of `location_tokens` (the
     function name or file) — within PROXIMITY_CHARS of the phrase.

Requirement 3 is the key anti-gaming property: to ground a catch, the reviewer
must cite the symbol/file from the diff it was handed, i.e. it must actually read
the change. Citing `file:line` / the symbol is exactly what real reviewers (and
this repo's reviewer agents) are instructed to do, so this rewards genuine
findings and rejects keyword splatter. See benchmark/README.md.

Keyword and location lists live in each fixture's `expected.json`, so tuning a
match is a data edit, not a code change.
"""
import json
import os
import re

# How close (in characters, within one block) a location token must sit to a
# matched phrase for the match to count as a grounded, located finding.
PROXIMITY_CHARS = 160

# Negation cues scanned in a short window immediately before a phrase match. If
# present, the phrase is being dismissed ("no SQL injection here"), not reported.
_NEGATION_RE = re.compile(
    r"\b(no|not|never|without|isn't|aren't|wasn't|weren't|doesn't|don't|didn't|"
    r"cannot|can't|free of|none of|no sign of|no risk of|rather than)\b|n't"
)
_NEGATION_WINDOW_CHARS = 30

# A clean-control finding is treated as a false positive only when the reviewer
# labels it at this severity or higher. Minor/Nit style suggestions on correct
# code are expected and are NOT penalized. We match a severity label that opens a
# line (optionally as a markdown heading, bullet, or numbered item) OR that is
# emphasized inline (**Critical** / __Major__) anywhere in a line.
FALSE_POSITIVE_SEVERITY_RE = re.compile(
    r"(?im)^\s*#{0,6}\s*(?:[-*+]\s*)?(?:\d+[.)]\s*)?(?:\*\*|__)?\s*(critical|major)\b"
)
_INLINE_FALSE_POSITIVE_RE = re.compile(r"(?i)(?:\*\*|__)\s*(critical|major)\b")


def _split_blocks(text):
    """Split review text into blocks (paragraphs) on blank lines.

    Grounding (phrase + location proximity) is evaluated within a single block so
    a phrase reported for one finding cannot borrow a location mentioned in an
    unrelated paragraph.
    """
    blocks = re.split(r"\n\s*\n", text)
    return [block.strip() for block in blocks if block.strip()]


def _is_negated(block, phrase_index):
    """True if a negation cue sits just before the phrase at phrase_index."""
    window = block[max(0, phrase_index - _NEGATION_WINDOW_CHARS):phrase_index]
    return bool(_NEGATION_RE.search(window))


def _is_grounded(block, phrase_index, phrase_length, location_tokens):
    """True if a location token appears within PROXIMITY_CHARS of the phrase.

    With no location_tokens (defensive — every shipped defect supplies them),
    grounding is skipped and any phrase match grounds itself.
    """
    if not location_tokens:
        return True
    start = max(0, phrase_index - PROXIMITY_CHARS)
    end = phrase_index + phrase_length + PROXIMITY_CHARS
    window = block[start:end]
    return any(token in window for token in location_tokens)


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
        required = ("id", "category", "severity", "match_any", "location_tokens")
        missing = [key for key in required if key not in defect]
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
        if not defect["location_tokens"]:
            raise ValueError(
                "fixture %r defect %r has an empty location_tokens list; a catch "
                "must be groundable to a location" % (meta["id"], defect["id"])
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
    """Return the first phrase that grounded a catch, or None if missed.

    A catch requires, within one block of the review: a specific `match_any`
    phrase, in a non-negated context, with one of the defect's `location_tokens`
    nearby (see this module's docstring and the helpers above). The fixture id is
    stripped from the text first so an echoed id cannot fake a catch.
    """
    text = strip_fixture_id(review_text, fixture_id) if fixture_id else review_text.lower()
    location_tokens = [token.lower() for token in defect.get("location_tokens", [])]
    phrases = [phrase.lower() for phrase in defect["match_any"]]

    for block in _split_blocks(text):
        for original_phrase, phrase in zip(defect["match_any"], phrases):
            index = block.find(phrase)
            while index != -1:
                if not _is_negated(block, index) and _is_grounded(
                    block, index, len(phrase), location_tokens
                ):
                    return original_phrase
                index = block.find(phrase, index + 1)
    return None


def find_false_positive_findings(review_text):
    """Return the reviewer lines that look like Major/Critical findings.

    Used only on a control. This is a transparent heuristic, not ground truth: it
    surfaces lines that ASSERT a Major/Critical finding (line-leading severity
    labels incl. markdown headings, plus inline **emphasized** ones) so a human can
    confirm them. An inline severity label in a NON-negated context counts; a
    negated dismissal ("No **critical** issues found") does not — it reuses the
    same negation guard as the catch side, so a clean reviewer is not penalized for
    saying a defect is absent. See the benchmark README's "Known limitations".
    """
    matches = []
    for line in review_text.splitlines():
        if FALSE_POSITIVE_SEVERITY_RE.match(line):
            matches.append(line.strip())
            continue
        inline = _INLINE_FALSE_POSITIVE_RE.search(line)
        if inline and not _is_negated(line.lower(), inline.start()):
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
        matched_phrase = defect_is_caught(defect, review_text, fixture["id"])
        record = {
            "id": defect["id"],
            "category": defect["category"],
            "severity": defect["severity"],
        }
        if matched_phrase is not None:
            record["matched_phrase"] = matched_phrase
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
