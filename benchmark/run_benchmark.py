#!/usr/bin/env python3
"""Catch-rate benchmark harness (proof of concept).

Measures whether a code reviewer actually CATCHES planted defects, rather than
whether the repo is merely tidy. It loads the labeled fixture corpus under
`benchmark/fixtures/`, obtains a review for each fixture, scores caught/missed
defects plus false positives on the clean control, and prints a catch-rate
scorecard.

Two ways to supply reviews (pick one):

  1. --reviewer-cmd "<shell command>"
     Run a command once per fixture to PRODUCE the review live. The unified diff
     is piped to the command on stdin, and these environment variables are set:
         BENCHMARK_DIFF        absolute path to the fixture's diff.patch
         BENCHMARK_FIXTURE_ID  the fixture id (e.g. 001-sql-injection)
     The command's stdout is captured as the review text. Example wiring for a
     Copilot CLI reviewer agent is documented in benchmark/README.md.

  2. --review-dir <dir>
     Score reviews you already collected. For each fixture <id>, the harness
     reads <dir>/<id>.md (falling back to <dir>/<id>.txt). Missing files score
     as an empty review (everything missed), which is reported.

With neither flag, the harness prints the corpus summary and exits, so you can
inspect the fixtures without running anything.

Dependencies: python3 standard library only (matches the rest of scripts/).
"""
import argparse
import glob
import json
import os
import subprocess
import sys

SCORE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCORE_DIR)
import score  # noqa: E402  (local module, added to path above)

FIXTURES_DIR = os.path.join(SCORE_DIR, "fixtures")


def discover_fixtures():
    """Return sorted fixture directories that contain an expected.json."""
    dirs = []
    for path in sorted(glob.glob(os.path.join(FIXTURES_DIR, "*"))):
        if os.path.isfile(os.path.join(path, "expected.json")):
            dirs.append(path)
    return dirs


def review_from_command(fixture, reviewer_cmd, timeout):
    """Run reviewer_cmd for one fixture and capture stdout as the review text."""
    env = dict(os.environ)
    env["BENCHMARK_DIFF"] = os.path.join(fixture["dir"], "diff.patch")
    env["BENCHMARK_FIXTURE_ID"] = fixture["id"]
    try:
        completed = subprocess.run(
            reviewer_cmd,
            shell=True,  # reviewer_cmd is an explicit operator-supplied template
            input=fixture["diff_text"],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", "reviewer-cmd timed out after %ss" % timeout
    if completed.returncode != 0:
        return completed.stdout, "reviewer-cmd exited %d: %s" % (
            completed.returncode,
            completed.stderr.strip()[:200],
        )
    return completed.stdout, None


def review_from_dir(fixture, review_dir):
    """Read a pre-collected review for one fixture from review_dir."""
    for ext in (".md", ".txt"):
        candidate = os.path.join(review_dir, fixture["id"] + ext)
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as handle:
                return handle.read(), None
    return "", "no review file found for %s in %s" % (fixture["id"], review_dir)


def print_scorecard(fixture_results, summary, warnings):
    """Print a human-readable catch-rate scorecard."""
    print("== Catch-rate benchmark ==\n")
    header = "%-22s %-8s %-7s %s" % ("fixture", "defects", "caught", "result")
    print(header)
    print("-" * len(header))
    for result in fixture_results:
        if result["is_control"]:
            fp = len(result["false_positives"])
            verdict = "clean (%d false positive(s))" % fp if fp else "clean (no false positives)"
            print("%-22s %-8s %-7s %s" % (result["id"], "0", "-", verdict))
            continue
        caught = len(result["caught"])
        expected = result["expected_count"]
        missed_ids = [m["id"] for m in result["missed"]]
        verdict = "ALL CAUGHT" if not missed_ids else "MISSED: " + ", ".join(missed_ids)
        print("%-22s %-8s %-7s %s" % (result["id"], expected, "%d/%d" % (caught, expected), verdict))

    print("\n== Summary ==")
    rate = summary["catch_rate"]
    rate_str = "n/a" if rate is None else "%.0f%% (%d/%d)" % (
        rate * 100, summary["caught"], summary["total_defects"]
    )
    print("  fixtures scored : %d" % summary["fixtures"])
    print("  catch-rate      : %s" % rate_str)
    print("  defects missed  : %d" % summary["missed"])
    print("  false positives : %d (on clean control)" % summary["false_positives"])

    if warnings:
        print("\n== Warnings ==")
        for warning in warnings:
            print("  ! %s" % warning)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--reviewer-cmd", help="shell command that emits a review for the diff on stdin")
    source.add_argument("--review-dir", help="directory of pre-collected <fixture-id>.md reviews to score")
    parser.add_argument("--timeout", type=int, default=300, help="per-fixture timeout for --reviewer-cmd (seconds)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    parser.add_argument("--save-reviews", help="when using --reviewer-cmd, write each captured review to this dir")
    args = parser.parse_args(argv)

    fixture_dirs = discover_fixtures()
    if not fixture_dirs:
        print("no fixtures found under %s" % FIXTURES_DIR, file=sys.stderr)
        return 1
    fixtures = [score.load_fixture(d) for d in fixture_dirs]

    if not args.reviewer_cmd and not args.review_dir:
        total = sum(len(f["defects"]) for f in fixtures)
        print("Corpus: %d fixtures, %d planted defects." % (len(fixtures), total))
        for fixture in fixtures:
            kind = "control" if not fixture["defects"] else "%d defect(s)" % len(fixture["defects"])
            print("  %-22s %s — %s" % (fixture["id"], kind, fixture.get("title", "")))
        print("\nProvide --reviewer-cmd or --review-dir to score. See benchmark/README.md.")
        return 0

    if args.save_reviews:
        os.makedirs(args.save_reviews, exist_ok=True)

    fixture_results = []
    warnings = []
    for fixture in fixtures:
        if args.reviewer_cmd:
            review_text, warning = review_from_command(fixture, args.reviewer_cmd, args.timeout)
            if args.save_reviews and review_text:
                with open(os.path.join(args.save_reviews, fixture["id"] + ".md"), "w", encoding="utf-8") as handle:
                    handle.write(review_text)
        else:
            review_text, warning = review_from_dir(fixture, args.review_dir)
        if warning:
            warnings.append("%s: %s" % (fixture["id"], warning))
        fixture_results.append(score.score_fixture(fixture, review_text))

    summary = score.aggregate(fixture_results)

    if args.json:
        print(json.dumps({"summary": summary, "fixtures": fixture_results, "warnings": warnings}, indent=2))
    else:
        print_scorecard(fixture_results, summary, warnings)

    # Non-zero exit if any defect was missed, so the benchmark can gate CI later.
    return 0 if summary["missed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
