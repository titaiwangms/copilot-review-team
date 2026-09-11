#!/usr/bin/env python3
"""Unit tests for agent tool privilege policies."""

import unittest

from _check_tools import tool_policy_errors


class ToolPolicyTests(unittest.TestCase):
    def test_full_reviewer_accepts_read_search_and_shell(self):
        self.assertEqual(
            tool_policy_errors(
                "local-code-reviewer",
                ["read", "search", "shell"],
            ),
            [],
        )

    def test_full_reviewer_rejects_edit(self):
        errors = tool_policy_errors(
            "local-code-reviewer",
            ["read", "search", "edit"],
        )
        self.assertIn("reviewer must NOT have tool 'edit'", errors)

    def test_future_lightweight_review_is_fail_closed(self):
        for name in (
            "local-lightweight-performance-review",
            "local-lightweight-security-reviewer",
            "local-lightweight-risk-review-v2",
        ):
            with self.subTest(name=name):
                errors = tool_policy_errors(
                    name,
                    ["read", "search", "shell"],
                )
                self.assertEqual(len(errors), 1)
                self.assertIn("must be exactly", errors[0])

    def test_lightweight_review_accepts_only_read_and_search(self):
        self.assertEqual(
            tool_policy_errors(
                "local-lightweight-code-review",
                ["read", "search"],
            ),
            [],
        )

    def test_qa_requires_shell(self):
        self.assertIn(
            "missing required tool 'shell'",
            tool_policy_errors("local-qa-tester", ["read"]),
        )


if __name__ == "__main__":
    unittest.main()
