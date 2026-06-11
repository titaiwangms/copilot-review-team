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

    def write_target_bytes(self, data):
        with open(self.target, "wb") as fh:
            fh.write(data)

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

    # --- fidelity / byte round-trip (M1, M2, m5) ---

    def read_target_bytes(self):
        with open(self.target, "rb") as fh:
            return fh.read()

    def test_crlf_file_stays_crlf_through_install_and_remove(self):
        # A user file with Windows (CRLF) line endings must keep them.
        self.write_target_bytes(b"my notes\r\nsecond line\r\n")
        mp.cmd_install(self.target, self.source)
        after_install = self.read_target_bytes()
        self.assertIn(b"\r\n", after_install)
        # No bare LF (every \n must be preceded by \r).
        self.assertEqual(after_install.count(b"\n"), after_install.count(b"\r\n"))
        mp.cmd_remove(self.target)
        after_remove = self.read_target_bytes()
        self.assertEqual(after_remove, b"my notes\r\nsecond line\r\n")

    def test_install_then_remove_preserves_multiple_trailing_blank_lines(self):
        original = b"alpha\nbeta\n\n\n"
        self.write_target_bytes(original)
        mp.cmd_install(self.target, self.source)
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), original)

    def test_install_preserves_trailing_spaces_on_content_line(self):
        # A Markdown hard-break ('keep  ') must not lose its trailing spaces.
        self.write_target_bytes(b"keep  \nnext\n")
        mp.cmd_install(self.target, self.source)
        after = self.read_target_bytes()
        self.assertIn(b"keep  \n", after)
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), b"keep  \nnext\n")

    def test_install_then_remove_no_prior_block_is_byte_identical(self):
        original = b"just my notes\nwith two lines\n"
        self.write_target_bytes(original)
        mp.cmd_install(self.target, self.source)
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), original)

    def test_install_rejects_marker_in_source(self):
        bad_source = os.path.join(self.dir, "bad_source.md")
        with open(bad_source, "w", encoding="utf-8") as fh:
            fh.write("legit line\n" + mp.BEGIN + "\nsneaky\n")
        self.write_target("user content\n")
        rc = mp.cmd_install(self.target, bad_source)
        self.assertEqual(rc, 1)
        # Target must be untouched (no managed block written).
        self.assertEqual(self.read_target(), "user content\n")


if __name__ == "__main__":
    unittest.main()
