#!/usr/bin/env python3
"""Catch-rate benchmark harness (proof of concept).

Measures whether a code reviewer actually CATCHES planted defects, rather than
whether the repo is merely tidy. It loads the labeled fixture corpus under
`benchmark/fixtures/`, obtains a review for each fixture, scores caught/missed
defects plus false positives on the clean/near-miss controls, and prints a
catch-rate scorecard.

A reviewer "configuration" is one way of producing reviews. You can score a
single configuration or compare several (e.g. a 9-reviewer pipeline vs a
5-reviewer pipeline — the comparison that gates issue #10).

Configurations
--------------
Each `--config NAME=SPEC` adds one configuration. SPEC is either:
  * `cmd:<shell command>` — run the command once per fixture to PRODUCE a review.
    The diff is piped to the command on stdin. To avoid leaking the answer key,
    the command is NOT told the fixture id; instead it gets:
        BENCHMARK_DIFF           path to a temp copy of the diff (opaque filename)
        BENCHMARK_FIXTURE_TOKEN  an opaque per-run random token
    The command's stdout is captured as the review text.
  * `dir:<path>` — score reviews already collected. For each fixture <id>, reads
    <path>/<id>.md (falling back to <id>.txt). A missing file scores as an empty
    review (everything missed) and is reported as a warning.

Shorthands for a single configuration:
  --reviewer-cmd "<command>"   ==  --config default=cmd:<command>
  --review-dir <path>          ==  --config default=dir:<path>

With two or more configurations, the harness prints a comparison table of
catch-rate / misses / false-positives per configuration. With one, it prints a
per-fixture scorecard. With none, it prints the corpus summary and exits.

Dependencies: python3 standard library only (matches the rest of scripts/).
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

BENCHMARK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BENCHMARK_DIR)
import score  # noqa: E402  (local module, added to path above)

FIXTURES_DIR = os.path.join(BENCHMARK_DIR, "fixtures")


def discover_fixtures():
    """Return sorted fixture directories that contain an expected.json.

    A directory needs only `expected.json` to be discovered; a missing
    `diff.patch` is left to score.load_fixture to reject loudly (fail-fast on a
    malformed fixture rather than silently skipping it).
    """
    dirs = []
    for path in sorted(glob.glob(os.path.join(FIXTURES_DIR, "*"))):
        if os.path.isfile(os.path.join(path, "expected.json")):
            dirs.append(path)
    return dirs


def review_from_command(fixture, reviewer_cmd, timeout):
    """Run reviewer_cmd for one fixture and capture stdout as the review text.

    The fixture id is never exposed to the command (see M4 in the review): the
    diff is copied to a temp file with an opaque name and the command receives an
    opaque BENCHMARK_FIXTURE_TOKEN, so a reviewer cannot special-case fixtures or
    learn which one is a control. The diff is also piped on stdin.
    """
    token = uuid.uuid4().hex[:12]
    tmpdir = tempfile.mkdtemp(prefix="benchmark-")
    try:
        diff_path = os.path.join(tmpdir, token + ".patch")
        with open(diff_path, "w", encoding="utf-8") as handle:
            handle.write(fixture["diff_text"])

        env = dict(os.environ)
        env["BENCHMARK_DIFF"] = diff_path
        env["BENCHMARK_FIXTURE_TOKEN"] = token
        env.pop("BENCHMARK_FIXTURE_ID", None)  # never leak the human-readable id

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
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def review_from_dir(fixture, review_dir):
    """Read a pre-collected review for one fixture from review_dir."""
    for ext in (".md", ".txt"):
        candidate = os.path.join(review_dir, fixture["id"] + ext)
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as handle:
                return handle.read(), None
    return "", "no review file found for %s in %s" % (fixture["id"], review_dir)


def run_configuration(config, fixtures, timeout, save_reviews=None):
    """Score one configuration across all fixtures.

    Returns (fixture_results, summary, warnings).
    """
    fixture_results = []
    warnings = []
    if save_reviews:
        os.makedirs(save_reviews, exist_ok=True)

    for fixture in fixtures:
        if config["kind"] == "cmd":
            review_text, warning = review_from_command(fixture, config["value"], timeout)
            if save_reviews and review_text:
                out_path = os.path.join(save_reviews, fixture["id"] + ".md")
                with open(out_path, "w", encoding="utf-8") as handle:
                    handle.write(review_text)
        else:  # "dir"
            review_text, warning = review_from_dir(fixture, config["value"])
        if warning:
            warnings.append("%s: %s" % (fixture["id"], warning))
        fixture_results.append(score.score_fixture(fixture, review_text))

    summary = score.aggregate(fixture_results)
    return fixture_results, summary, warnings


def _rate_str(summary):
    rate = summary["catch_rate"]
    if rate is None:
        return "n/a"
    return "%.0f%% (%d/%d)" % (rate * 100, summary["caught"], summary["total_defects"])


def print_scorecard(fixture_results, summary, warnings):
    """Print a per-fixture scorecard for a single configuration."""
    print("== Catch-rate benchmark ==\n")
    header = "%-30s %-8s %-7s %s" % ("fixture", "defects", "caught", "result")
    print(header)
    print("-" * len(header))
    for result in fixture_results:
        if result["is_control"]:
            fp = len(result["false_positives"])
            verdict = "clean (%d false positive(s))" % fp if fp else "clean (no false positives)"
            print("%-30s %-8s %-7s %s" % (result["id"], "0", "-", verdict))
            continue
        caught = len(result["caught"])
        expected = result["expected_count"]
        missed_ids = [m["id"] for m in result["missed"]]
        verdict = "ALL CAUGHT" if not missed_ids else "MISSED: " + ", ".join(missed_ids)
        print("%-30s %-8s %-7s %s" % (result["id"], expected, "%d/%d" % (caught, expected), verdict))

    print("\n== Summary ==")
    print("  fixtures scored : %d" % summary["fixtures"])
    print("  catch-rate      : %s" % _rate_str(summary))
    print("  defects missed  : %d" % summary["missed"])
    print("  false positives : %d (on clean/near-miss controls)" % summary["false_positives"])
    _print_warnings(warnings)


def print_comparison(config_summaries):
    """Print a side-by-side comparison table across configurations.

    config_summaries: list of (name, summary, warnings). This is the view that
    answers "what does cutting a reviewer cost?" — the gate for issue #10.
    """
    print("== Catch-rate comparison ==\n")
    header = "%-20s %-16s %-8s %s" % ("configuration", "catch-rate", "missed", "false-pos")
    print(header)
    print("-" * len(header))
    for name, summary, _ in config_summaries:
        print("%-20s %-16s %-8d %d" % (name, _rate_str(summary), summary["missed"], summary["false_positives"]))

    baseline_name, baseline, _ = config_summaries[0]
    if len(config_summaries) > 1 and baseline["catch_rate"] is not None:
        print("\n== Deltas vs '%s' ==" % baseline_name)
        for name, summary, _ in config_summaries[1:]:
            if summary["catch_rate"] is None:
                continue
            d_rate = (summary["catch_rate"] - baseline["catch_rate"]) * 100
            d_fp = summary["false_positives"] - baseline["false_positives"]
            print("  %-18s catch-rate %+.0f pts, false-positives %+d" % (name, d_rate, d_fp))

    all_warnings = [(name, w) for name, _, ws in config_summaries for w in ws]
    if all_warnings:
        print("\n== Warnings ==")
        for name, warning in all_warnings:
            print("  ! [%s] %s" % (name, warning))


def _print_warnings(warnings):
    if warnings:
        print("\n== Warnings ==")
        for warning in warnings:
            print("  ! %s" % warning)


def parse_configs(args):
    """Build the ordered list of configurations from CLI args.

    Returns a list of {"name", "kind", "value"} dicts. Raises ValueError on a
    malformed --config spec.
    """
    configs = []
    if args.reviewer_cmd:
        configs.append({"name": "default", "kind": "cmd", "value": args.reviewer_cmd})
    if args.review_dir:
        configs.append({"name": "default", "kind": "dir", "value": args.review_dir})
    for raw in args.config or []:
        if "=" not in raw:
            raise ValueError("--config must be NAME=SPEC, got %r" % raw)
        name, spec = raw.split("=", 1)
        if spec.startswith("cmd:"):
            configs.append({"name": name, "kind": "cmd", "value": spec[len("cmd:"):]})
        elif spec.startswith("dir:"):
            configs.append({"name": name, "kind": "dir", "value": spec[len("dir:"):]})
        else:
            raise ValueError("--config %r spec must start with 'cmd:' or 'dir:'" % raw)
    return configs


def print_corpus_summary(fixtures):
    total = sum(len(f["defects"]) for f in fixtures)
    controls = sum(1 for f in fixtures if not f["defects"])
    print("Corpus: %d fixtures, %d planted defects, %d control(s)." % (len(fixtures), total, controls))
    for fixture in fixtures:
        kind = "control" if not fixture["defects"] else "%d defect(s)" % len(fixture["defects"])
        print("  %-30s %-12s %s" % (fixture["id"], kind, fixture.get("title", "")))
    print("\nProvide --config / --reviewer-cmd / --review-dir to score. See benchmark/README.md.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config", action="append",
        help="add a configuration: NAME=cmd:<command> or NAME=dir:<path> (repeatable)",
    )
    parser.add_argument("--reviewer-cmd", help="shorthand for --config default=cmd:<command>")
    parser.add_argument("--review-dir", help="shorthand for --config default=dir:<path>")
    parser.add_argument("--timeout", type=int, default=300, help="per-fixture timeout for cmd configs (seconds)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    parser.add_argument("--save-reviews", help="for a single cmd config, write each captured review to this dir")
    args = parser.parse_args(argv)

    fixture_dirs = discover_fixtures()
    if not fixture_dirs:
        print("no fixtures found under %s" % FIXTURES_DIR, file=sys.stderr)
        return 1
    fixtures = [score.load_fixture(d) for d in fixture_dirs]

    try:
        configs = parse_configs(args)
    except ValueError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1

    if not configs:
        print_corpus_summary(fixtures)
        return 0

    if args.save_reviews and len(configs) > 1:
        print("error: --save-reviews is only supported with a single configuration", file=sys.stderr)
        return 1

    config_summaries = []
    for config in configs:
        save = args.save_reviews if (config["kind"] == "cmd" and len(configs) == 1) else None
        fixture_results, summary, warnings = run_configuration(config, fixtures, args.timeout, save)
        config_summaries.append((config["name"], summary, warnings, fixture_results))

    if args.json:
        payload = {
            "configurations": [
                {"name": name, "summary": summary, "fixtures": results, "warnings": warnings}
                for name, summary, warnings, results in config_summaries
            ]
        }
        print(json.dumps(payload, indent=2))
    elif len(config_summaries) == 1:
        name, summary, warnings, fixture_results = config_summaries[0]
        print_scorecard(fixture_results, summary, warnings)
    else:
        print_comparison([(name, summary, warnings) for name, summary, warnings, _ in config_summaries])

    # Single-config gate: non-zero if any defect was MISSED (recall) or any
    # false positive was raised on a control (precision), so a CI job fails on
    # either a splatter reviewer that over-flags clean code or one that misses
    # defects. Comparison runs are informational (exit 0 unless a corpus error).
    if len(config_summaries) == 1:
        summary = config_summaries[0][1]
        return 0 if (summary["missed"] == 0 and summary["false_positives"] == 0) else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
