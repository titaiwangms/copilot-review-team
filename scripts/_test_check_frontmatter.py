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

    def test_ordered_models_with_required_policy_passes(self):
        text = _with_model(
            "models:\n  - gpt-6-astra\n  - gpt-6.1-sol\nmodelPolicy: required"
        )
        self.assertEqual(check_frontmatter(text, "local-code-reviewer"), [])

    def test_models_and_legacy_model_passes(self):
        text = _with_model("model: gpt-6-astra\nmodels:\n  - gpt-6.1-sol")
        self.assertEqual(check_frontmatter(text, "local-code-reviewer"), [])

    def test_empty_models_rejected(self):
        errors = check_frontmatter(_with_model("models:"), "local-code-reviewer")
        self.assertTrue(any("at least one" in e for e in errors), errors)

    def test_malformed_models_rejected(self):
        for value in (
            "models: gpt-6.1-sol",
            "models: [gpt-6-astra, gpt-6.1-sol]",
            "models: |\n  gpt-6.1-sol",
            "models:\n  - gpt 6",
            "models:\n  -",
            "models:\n  - gpt-6.1-sol\n  invalid",
            "models:\n  - gpt-6.1-sol\n  nested: value",
            "models:\n  - gpt-6-astra:",
            "models:\n\t- gpt-6-astra",
        ):
            with self.subTest(value=value):
                errors = check_frontmatter(_with_model(value), "local-code-reviewer")
                self.assertTrue(any("malformed" in e for e in errors), errors)

    def test_inconsistent_models_indentation_rejected(self):
        text = _with_model("models:\n  - gpt-6-astra\n    - gpt-6.1-sol")
        errors = check_frontmatter(text, "local-code-reviewer")
        self.assertTrue(any("indentation" in e for e in errors), errors)

    def test_internal_colon_in_model_id_passes(self):
        text = _with_model("models:\n  - provider:model")
        self.assertEqual(check_frontmatter(text, "local-code-reviewer"), [])

    def test_duplicate_models_rejected(self):
        for second in ("models:", "models:\n  - gpt-6.1-sol"):
            with self.subTest(second=second):
                text = _with_model("models:\n  - gpt-6-astra\n" + second)
                errors = check_frontmatter(text, "local-code-reviewer")
                self.assertTrue(any("duplicate models" in e for e in errors), errors)

    def test_shipped_native_fallback_contract(self):
        agents = {
            "local-critical-reviewer": ("gpt-6-astra", "gpt-6.1-sol"),
            "local-qa-tester": ("gpt-6-astra", "gpt-6.1-sol"),
            "local-deep-reviewer": ("claude-opus-5.5", "claude-sonnet-5.5"),
        }
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name, candidates in agents.items():
            with self.subTest(agent=name):
                with open(os.path.join(root, "agents", name + ".agent.md"), encoding="utf-8") as file:
                    text = file.read()
                self.assertEqual(check_frontmatter(text, name), [])
                expected = "models:\n  - %s\n  - %s\nmodelPolicy: required\n" % candidates
                self.assertIn(expected, text.split("---", 2)[1])

    def test_models_comments_and_blanks_pass(self):
        text = _with_model(
            "models:\n  # primary\n  - gpt-6-astra\n\n  - gpt-6.1-sol"
        )
        self.assertEqual(check_frontmatter(text, "local-code-reviewer"), [])

    def test_models_outside_frontmatter_do_not_count(self):
        text = _with_model("models:") + "\nmodels:\n  - gpt-6.1-sol\n"
        errors = check_frontmatter(text, "local-code-reviewer")
        self.assertTrue(any("at least one" in e for e in errors), errors)

    def test_model_policy_values(self):
        for policy in ("preferred", "required"):
            with self.subTest(policy=policy):
                text = _with_model("model: gpt-6.1-sol\nmodelPolicy: " + policy)
                self.assertEqual(check_frontmatter(text, "local-code-reviewer"), [])
        for policy in ("", "optional", "Required", "[required]"):
            with self.subTest(policy=policy):
                text = _with_model("model: gpt-6.1-sol\nmodelPolicy: " + policy)
                errors = check_frontmatter(text, "local-code-reviewer")
                self.assertTrue(any("modelPolicy" in e for e in errors), errors)

    def test_name_mismatch_rejected(self):
        errors = check_frontmatter(GOOD, "local-critical-reviewer")
        self.assertTrue(any("expected 'local-critical-reviewer'" in e for e in errors), errors)

    def test_no_frontmatter_rejected(self):
        errors = check_frontmatter("no frontmatter here\n", "local-code-reviewer")
        self.assertEqual(len(errors), 1)
        self.assertIn("frontmatter", errors[0])


if __name__ == "__main__":
    unittest.main()
