#!/usr/bin/env python3
"""Unit tests for scripts/_merge_playbook.py.

Run directly (`python3 scripts/_test_merge_playbook.py`) or via
`python3 -m unittest scripts._test_merge_playbook`. Stdlib only. Exits 0 on pass.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _merge_playbook as mp

SOURCE = "# Playbook heading\n\nsome managed content\n"


class MergePlaybookTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = self._dir.name
        self.target = os.path.join(self.dir, "copilot-instructions.md")
        self.source = os.path.join(self.dir, "source.md")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        self.addCleanup(self._dir.cleanup)

    def read_target(self):
        with open(self.target, encoding="utf-8") as fh:
            return fh.read()

    def write_target(self, text):
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write(text)

    def block(self):
        return mp.BEGIN + "\n" + SOURCE.strip("\n") + "\n" + mp.END + "\n"

    # --- install ---

    def test_new_file(self):
        rc = mp.cmd_install(self.target, self.source)
        self.assertEqual(rc, 0)
        self.assertEqual(self.read_target(), self.block())

    def test_append_preserves_user_content(self):
        self.write_target("my own instructions\nline two\n")
        mp.cmd_install(self.target, self.source)
        out = self.read_target()
        self.assertTrue(out.startswith("my own instructions\nline two\n"))
        self.assertIn(mp.BEGIN, out)
        self.assertIn("some managed content", out)
        # exactly one blank line between user content and the block
        self.assertIn("line two\n\n" + mp.BEGIN, out)

    def test_in_place_upgrade_is_idempotent(self):
        self.write_target("user header\n")
        mp.cmd_install(self.target, self.source)
        first = self.read_target()
        mp.cmd_install(self.target, self.source)
        second = self.read_target()
        self.assertEqual(first, second)
        # only one managed block survives
        self.assertEqual(second.count(mp.BEGIN), 1)
        self.assertEqual(second.count(mp.END), 1)
        self.assertTrue(second.startswith("user header\n"))

    def test_multiple_blocks_collapse(self):
        old = mp.BEGIN + "\nstale one\n" + mp.END + "\n"
        old2 = mp.BEGIN + "\nstale two\n" + mp.END + "\n"
        self.write_target("user\n\n" + old + "\nmiddle\n\n" + old2)
        mp.cmd_install(self.target, self.source)
        out = self.read_target()
        self.assertEqual(out.count(mp.BEGIN), 1)
        self.assertNotIn("stale one", out)
        self.assertNotIn("stale two", out)
        self.assertIn("user", out)
        self.assertIn("middle", out)
        self.assertIn("some managed content", out)

    def test_unbalanced_aborts_and_touches_nothing(self):
        bad = "user stuff\n" + mp.BEGIN + "\nhalf a block\n"
        self.write_target(bad)
        rc = mp.main(["_merge_playbook.py", "install", self.target, self.source])
        self.assertEqual(rc, 1)
        self.assertEqual(self.read_target(), bad)

    def test_end_before_begin_aborts(self):
        bad = mp.END + "\nstuff\n"
        self.write_target(bad)
        rc = mp.main(["_merge_playbook.py", "install", self.target, self.source])
        self.assertEqual(rc, 1)
        self.assertEqual(self.read_target(), bad)

    # --- remove ---

    def test_remove_strips_block_preserving_user(self):
        self.write_target("keep me\n")
        mp.cmd_install(self.target, self.source)
        rc = mp.cmd_remove(self.target)
        self.assertEqual(rc, 0)
        out = self.read_target()
        self.assertNotIn(mp.BEGIN, out)
        self.assertEqual(out, "keep me\n")

    def test_remove_deletes_file_when_empty(self):
        mp.cmd_install(self.target, self.source)
        rc = mp.cmd_remove(self.target)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.target))

    def test_remove_no_file_is_noop(self):
        rc = mp.cmd_remove(self.target)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.target))

    def test_remove_no_markers_left_untouched(self):
        self.write_target("just user content\n")
        rc = mp.cmd_remove(self.target)
        self.assertEqual(rc, 0)
        self.assertEqual(self.read_target(), "just user content\n")

    def test_remove_unbalanced_aborts(self):
        bad = mp.BEGIN + "\nunterminated\n"
        self.write_target(bad)
        rc = mp.main(["_merge_playbook.py", "remove", self.target])
        self.assertEqual(rc, 1)
        self.assertEqual(self.read_target(), bad)


if __name__ == "__main__":
    unittest.main()
