#!/usr/bin/env python3
"""Regression tests for the actual C4 shell validation block."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class ReviewerCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = (Path(__file__).parent / "validate.sh").read_text(encoding="utf-8")
        cls.check = (
            "set -euo pipefail\n"
            "FAILURES=0\n"
            "pass() { printf 'PASS: %s\\n' \"$*\"; }\n"
            "fail() { printf 'FAIL: %s\\n' \"$*\"; FAILURES=$((FAILURES + 1)); }\n"
            + script[script.index("# --- C4:"):script.index("# --- C5:")]
            + '\nexit "$FAILURES"\n'
        )

    def run_check(self, primary_count=5, alternates=None):
        with tempfile.TemporaryDirectory(prefix="reviewer-count-test-") as tmp:
            root = Path(tmp)
            agents = root / "agents"
            agents.mkdir()
            count_word = {5: "five", 6: "six"}[primary_count]
            for index in range(primary_count):
                (agents / f"local-test-{index}-reviewer.agent.md").write_text(
                    f"You are one of {count_word} reviewers.\n", encoding="utf-8"
                )
            for name, wording in (alternates or {}).items():
                (agents / name).write_text(wording + "\n", encoding="utf-8")
            (root / "README.md").write_text(
                f"The team has {count_word} reviewers.\n", encoding="utf-8"
            )
            (root / "copilot-instructions.md").write_text(
                f"Run {primary_count} reviewers.\n", encoding="utf-8"
            )
            return subprocess.run(
                ["bash", "-c", self.check],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

    def test_alternates_do_not_increase_primary_count(self):
        result = self.run_check(
            alternates={
                "local-test-reviewer-alternate.agent.md": "You are one of five reviewers.",
                "local-other-reviewer-alternate.agent.md": "You are one of 5 reviewers.",
                "local-qa-tester.agent.md": "You are the QA tester.",
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("found 5 reviewer agent file(s)", result.stdout)
        for name in ("local-test-reviewer-alternate", "local-other-reviewer-alternate"):
            self.assertIn(f"{name}.agent.md agrees with reviewer count (5)", result.stdout)
        self.assertNotIn("local-qa-tester", result.stdout)

    def test_six_primary_roles_reject_stale_alternate(self):
        for name in (
            "local-test-reviewer-alternate.agent.md",
        ):
            with self.subTest(name=name):
                result = self.run_check(6, {name: "You are one of five reviewers."})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("found 6 reviewer agent file(s)", result.stdout)
                self.assertIn(
                    f"FAIL: {name} does not say 'one of 6 reviewers'", result.stdout
                )

    def test_matching_word_and_digit_alternate_counts_pass(self):
        result = self.run_check(
            6,
            {
                "local-test-reviewer-alternate.agent.md": "You are one of six reviewers.",
                "local-other-reviewer-alternate.agent.md": "You are one of 6 reviewers.",
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fork_without_alternates_passes(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL:", result.stdout)


if __name__ == "__main__":
    unittest.main()
