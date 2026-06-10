#!/usr/bin/env python3
"""Unit tests for the catch-rate benchmark harness (run_benchmark.py).

Focuses on the harness-only logic: configuration parsing, the answer-key-leak
mitigation (M4), pre-collected review lookup, and CLI exit codes. Scoring itself
is covered by test_score.py. Standard-library only.
"""
import argparse
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_benchmark  # noqa: E402


def _args(**overrides):
    base = {
        "config": None,
        "reviewer_cmd": None,
        "review_dir": None,
        "timeout": 5,
        "json": False,
        "save_reviews": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class ParseConfigsTests(unittest.TestCase):
    def test_reviewer_cmd_shorthand(self):
        configs = run_benchmark.parse_configs(_args(reviewer_cmd="cat"))
        self.assertEqual(configs, [{"name": "default", "kind": "cmd", "value": "cat"}])

    def test_review_dir_shorthand(self):
        configs = run_benchmark.parse_configs(_args(review_dir="/tmp/x"))
        self.assertEqual(configs, [{"name": "default", "kind": "dir", "value": "/tmp/x"}])

    def test_named_cmd_and_dir_configs_preserve_order(self):
        configs = run_benchmark.parse_configs(_args(config=["nine=cmd:run-nine", "five=dir:/tmp/five"]))
        self.assertEqual([c["name"] for c in configs], ["nine", "five"])
        self.assertEqual(configs[0], {"name": "nine", "kind": "cmd", "value": "run-nine"})
        self.assertEqual(configs[1], {"name": "five", "kind": "dir", "value": "/tmp/five"})

    def test_cmd_value_keeps_embedded_equals_and_colons(self):
        configs = run_benchmark.parse_configs(_args(config=["a=cmd:VAR=1 tool --flag=x:y"]))
        self.assertEqual(configs[0]["value"], "VAR=1 tool --flag=x:y")

    def test_missing_equals_raises(self):
        with self.assertRaises(ValueError):
            run_benchmark.parse_configs(_args(config=["bogus"]))

    def test_unknown_spec_prefix_raises(self):
        with self.assertRaises(ValueError):
            run_benchmark.parse_configs(_args(config=["a=shell:echo hi"]))


class ReviewFromCommandTests(unittest.TestCase):
    """The command must not be able to learn the fixture id (M4 answer-key leak)."""

    FIXTURE = {"id": "001-sql-injection", "diff_text": "diff --git a/x b/x\n+bad line\n"}

    def test_diff_is_piped_on_stdin(self):
        review, warning = run_benchmark.review_from_command(self.FIXTURE, "cat", timeout=5)
        self.assertIsNone(warning)
        self.assertIn("bad line", review)

    def test_fixture_id_is_not_in_environment(self):
        # Dump the whole environment; the human-readable fixture id must be absent.
        review, warning = run_benchmark.review_from_command(self.FIXTURE, "env", timeout=5)
        self.assertIsNone(warning)
        self.assertNotIn("001-sql-injection", review)
        self.assertNotIn("BENCHMARK_FIXTURE_ID", review)

    def test_opaque_token_and_diff_path_are_exposed(self):
        review, _ = run_benchmark.review_from_command(
            self.FIXTURE, 'echo "$BENCHMARK_FIXTURE_TOKEN $BENCHMARK_DIFF"', timeout=5
        )
        token, diff_path = review.split()
        self.assertEqual(len(token), 12)
        self.assertNotIn("001-sql-injection", diff_path)
        self.assertIn(token, diff_path)  # temp diff is named by the opaque token

    def test_preexisting_fixture_id_env_var_is_stripped(self):
        os.environ["BENCHMARK_FIXTURE_ID"] = "001-sql-injection"
        try:
            review, _ = run_benchmark.review_from_command(
                self.FIXTURE, "echo id=[${BENCHMARK_FIXTURE_ID:-unset}]", timeout=5
            )
            self.assertIn("id=[unset]", review)
        finally:
            os.environ.pop("BENCHMARK_FIXTURE_ID", None)

    def test_nonzero_exit_is_reported_as_warning(self):
        review, warning = run_benchmark.review_from_command(self.FIXTURE, "exit 3", timeout=5)
        self.assertIsNotNone(warning)
        self.assertIn("exited 3", warning)

    def test_timeout_is_reported_as_warning(self):
        review, warning = run_benchmark.review_from_command(self.FIXTURE, "sleep 5", timeout=1)
        self.assertEqual(review, "")
        self.assertIn("timed out", warning)


class ReviewFromDirTests(unittest.TestCase):
    def test_reads_md_then_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "001-x.md"), "w") as handle:
                handle.write("md review")
            review, warning = run_benchmark.review_from_dir({"id": "001-x"}, tmp)
            self.assertEqual(review, "md review")
            self.assertIsNone(warning)

    def test_txt_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "001-x.txt"), "w") as handle:
                handle.write("txt review")
            review, warning = run_benchmark.review_from_dir({"id": "001-x"}, tmp)
            self.assertEqual(review, "txt review")
            self.assertIsNone(warning)

    def test_missing_file_warns_and_scores_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            review, warning = run_benchmark.review_from_dir({"id": "001-x"}, tmp)
            self.assertEqual(review, "")
            self.assertIn("no review file", warning)


class MainExitCodeTests(unittest.TestCase):
    """End-to-end against the shipped corpus via the dir interface."""

    def _run(self, review_dir):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_benchmark.main(["--review-dir", review_dir])
        return code, buf.getvalue()

    def test_no_configs_prints_corpus_and_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_benchmark.main([])
        self.assertEqual(code, 0)
        self.assertIn("Corpus:", buf.getvalue())

    def test_all_caught_exits_zero(self):
        fixtures = [run_benchmark.score.load_fixture(d) for d in run_benchmark.discover_fixtures()]
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in fixtures:
                lines = []
                for defect in fixture["defects"]:
                    lines.append(
                        "- **%s**: in %s — %s"
                        % (defect["severity"], " ".join(defect["location_tokens"]), defect["description"])
                    )
                with open(os.path.join(tmp, fixture["id"] + ".md"), "w") as handle:
                    handle.write("\n".join(lines) or "Looks correct, no issues.")
            code, out = self._run(tmp)
        self.assertEqual(code, 0, out)
        self.assertIn("false positives : 0", out)

    def test_missed_defect_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Empty review dir => every defect missed => exit 2.
            code, out = self._run(tmp)
        self.assertEqual(code, 2)

    def test_false_positive_with_no_misses_exits_two(self):
        # A splatter reviewer: catches every defect (recall 100%) but also raises a
        # Major/Critical finding on the controls. Recall-only gating would pass it;
        # the precision-aware gate must fail it (exit 2).
        fixtures = [run_benchmark.score.load_fixture(d) for d in run_benchmark.discover_fixtures()]
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in fixtures:
                if fixture["defects"]:
                    lines = [
                        "- **%s**: in %s — %s"
                        % (defect["severity"], " ".join(defect["location_tokens"]), defect["description"])
                        for defect in fixture["defects"]
                    ]
                    body = "\n".join(lines)
                else:  # control — splatter a false positive
                    body = "- **Critical**: this clean control looks suspicious to me."
                with open(os.path.join(tmp, fixture["id"] + ".md"), "w") as handle:
                    handle.write(body)
            code, out = self._run(tmp)
        self.assertEqual(code, 2, out)
        self.assertIn("catch-rate      : 100%", out)
        self.assertNotIn("false positives : 0", out)

    def test_clean_reviewer_with_bolded_negated_dismissal_exits_zero(self):
        # All defects caught; controls carry a bolded NEGATED dismissal
        # ("No **critical** issues"). The negation-aware FP detector must not turn
        # that into a phantom FP that falsely fails the precision-aware gate.
        fixtures = [run_benchmark.score.load_fixture(d) for d in run_benchmark.discover_fixtures()]
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in fixtures:
                if fixture["defects"]:
                    body = "\n".join(
                        "- **%s**: in %s — %s"
                        % (defect["severity"], " ".join(defect["location_tokens"]), defect["description"])
                        for defect in fixture["defects"]
                    )
                else:
                    body = "No **critical** issues found; this change looks correct."
                with open(os.path.join(tmp, fixture["id"] + ".md"), "w") as handle:
                    handle.write(body)
            code, out = self._run(tmp)
        self.assertEqual(code, 0, out)
        self.assertIn("false positives : 0", out)

    def test_invalid_config_exits_one(self):
        code = run_benchmark.main(["--config", "bogus-no-equals"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
