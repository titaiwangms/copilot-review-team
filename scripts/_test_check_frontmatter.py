#!/usr/bin/env python3
"""Unit tests for the C2 frontmatter checker (scripts/_check_frontmatter.py).

Run directly (`python3 scripts/_test_check_frontmatter.py`) or via
`python3 -m unittest scripts._test_check_frontmatter`. Stdlib only.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_frontmatter import check_frontmatter

GOOD = """---
name: local-code-reviewer
description: reviews function-level correctness
model: claude-opus-4.8
tools:
  - read
  - search
---
body text
"""


def _with_model(line):
    """Return GOOD with the `model: ...` line swapped for `line` (or removed)."""
    out = []
    for raw in GOOD.splitlines(keepends=True):
        if raw.startswith("model:"):
            if line is not None:
                out.append(line + "\n")
        else:
            out.append(raw)
    return "".join(out)


class CheckFrontmatterTest(unittest.TestCase):
    def test_well_formed_passes(self):
        self.assertEqual(check_frontmatter(GOOD, "local-code-reviewer"), [])

    def test_model_list_value_rejected(self):
        errors = check_frontmatter(_with_model("model: [gpt-5.5]"), "local-code-reviewer")
        self.assertTrue(any("malformed" in e for e in errors), errors)

    def test_block_scalar_model_rejected(self):
        errors = check_frontmatter(_with_model("model: |"), "local-code-reviewer")
        self.assertTrue(any("malformed" in e for e in errors), errors)

    def test_empty_model_value_rejected(self):
        errors = check_frontmatter(_with_model("model:"), "local-code-reviewer")
        self.assertTrue(any("malformed" in e for e in errors), errors)

    def test_model_with_space_rejected(self):
        errors = check_frontmatter(_with_model("model: gpt 5.5"), "local-code-reviewer")
        self.assertTrue(any("malformed" in e for e in errors), errors)

    def test_missing_model_key_rejected(self):
        errors = check_frontmatter(_with_model(None), "local-code-reviewer")
        self.assertTrue(any("missing key 'model'" in e for e in errors), errors)

    def test_name_mismatch_rejected(self):
        errors = check_frontmatter(GOOD, "local-critical-reviewer")
        self.assertTrue(any("expected 'local-critical-reviewer'" in e for e in errors), errors)

    def test_no_frontmatter_rejected(self):
        errors = check_frontmatter("no frontmatter here\n", "local-code-reviewer")
        self.assertEqual(len(errors), 1)
        self.assertIn("frontmatter", errors[0])


if __name__ == "__main__":
    unittest.main()
