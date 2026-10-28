#!/usr/bin/env python3
"""Unit tests for scripts/_merge_playbook.py.

Run directly (`python3 scripts/_test_merge_playbook.py`) or via
`python3 -m unittest scripts._test_merge_playbook`. Stdlib only. Exits 0 on pass.
"""
import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _merge_playbook as mp

SOURCE = "# Playbook heading\n\nsome managed content\n"
LEGACY = (
    "# Multi-agent team playbook\n\n"
    "## The team\n"
    "local-code-reviewer local-critical-reviewer "
    "local-deep-reviewer local-integration-reviewer\n"
    "## Default pipeline for non-trivial tasks\n"
    "old building/review routing\n"
    "## Review-only requests (no developer phase)\n"
    "old review routing\n"
    "## Repo-specific overrides\n"
    "old overrides\n\n"
)


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

    def test_legacy_blocks_install_with_or_without_managed_block(self):
        for suffix in ("", self.block()):
            with self.subTest(managed=bool(suffix)):
                original = "personal\n\n" + LEGACY + suffix
                self.write_target(original)
                error = io.StringIO()
                with contextlib.redirect_stderr(error):
                    rc = mp.main(["_merge_playbook.py", "install", self.target, self.source])
                self.assertEqual(rc, 1)
                self.assertIn("--migrate-legacy-playbook", error.getvalue())
                self.assertEqual(self.read_target(), original)
                self.assertEqual(len(os.listdir(self.dir)), 2)

    def test_legacy_migration_preserves_other_sections_bytes_and_permissions(self):
        for eol in ("\n", "\r\n"):
            with self.subTest(eol=repr(eol)):
                personal = "Personal notes  \n\n".replace("\n", eol)
                thinking = "# Brainstorming / thinking team\n\nkeep thinking\n".replace("\n", eol)
                trailing = "# Personal section\nno final newline".replace("\n", eol)
                keep = personal + thinking + trailing
                original = personal + LEGACY.replace("\n", eol) + thinking + trailing
                self.write_target_bytes(original.encode("utf-8"))
                os.chmod(self.target, 0o600)
                before_backups = set(os.listdir(self.dir))
                self.assertEqual(mp.cmd_install(self.target, self.source, True), 0)
                installed = self.read_target_bytes()
                residual, _ = mp._split_managed(installed.decode("utf-8"))
                self.assertEqual(residual, keep)
                self.assertEqual(installed.count(mp.BEGIN.encode("utf-8")), 1)
                backups = set(os.listdir(self.dir)) - before_backups
                self.assertEqual(len(backups), 1)
                backup = os.path.join(self.dir, backups.pop())
                with open(backup, "rb") as handle:
                    self.assertEqual(handle.read(), original.encode("utf-8"))
                self.assertEqual(stat.S_IMODE(os.stat(backup).st_mode), 0o600)
                self.assertEqual(mp.cmd_install(self.target, self.source, True), 0)
                self.assertEqual(self.read_target_bytes(), installed)
                self.assertEqual(set(os.listdir(self.dir)), before_backups | {os.path.basename(backup)})
                self.assertEqual(mp.cmd_remove(self.target), 0)
                self.assertEqual(self.read_target_bytes(), keep.encode("utf-8"))

    def test_migration_replaces_legacy_and_existing_managed_copy(self):
        self.write_target(LEGACY + "# Thinking\nkeep\n\n" + self.block())
        self.assertEqual(mp.main([
            "_merge_playbook.py", "install", self.target, self.source,
            "--migrate-legacy-playbook",
        ]), 0)
        out = self.read_target()
        self.assertNotIn("# Multi-agent team playbook", out)
        self.assertIn("# Thinking\nkeep", out)
        self.assertEqual(out.count(mp.BEGIN), 1)
        self.assertEqual(out.count(SOURCE.strip()), 1)

    def test_check_is_read_only_and_refuses_unrecognized_migration(self):
        for original in (LEGACY, "# Multi-agent team playbook\ncustom content\n"):
            with self.subTest(original=original):
                self.write_target(original)
                before = set(os.listdir(self.dir))
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(mp.main(["_merge_playbook.py", "check", self.target]), 1)
                    result = mp.main([
                        "_merge_playbook.py", "check", self.target,
                        "--migrate-legacy-playbook",
                    ])
                self.assertEqual(result, 0 if original == LEGACY else 1)
                self.assertEqual(set(os.listdir(self.dir)), before)
                self.assertEqual(self.read_target(), original)

    def test_migration_failure_leaves_original_and_backup(self):
        self.write_target(LEGACY)
        with mock.patch.object(mp, "_atomic_write", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                mp.cmd_install(self.target, self.source, True)
        self.assertEqual(self.read_target(), LEGACY)
        backups = [name for name in os.listdir(self.dir) if ".legacy-" in name]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.dir, backups[0]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), LEGACY)

    def test_unclosed_fence_cannot_hide_a_section_boundary_during_migration(self):
        original = LEGACY + "```text\n# Personal notes\nkeep me\n"
        self.write_target(original)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mp.main([
                "_merge_playbook.py", "install", self.target, self.source,
                "--migrate-legacy-playbook",
            ]), 1)
        self.assertEqual(self.read_target(), original)
        self.assertEqual(len(os.listdir(self.dir)), 2)

    def test_legacy_headings_inside_fenced_examples_are_preserved(self):
        for fence in ("```markdown", "~~~~"):
            with self.subTest(fence=fence):
                original = fence + "\n" + LEGACY + fence[:3] + "\n"
                if fence.startswith("~"):
                    original = fence + "\n" + LEGACY + "~~~~\n"
                self.write_target(original)
                self.assertEqual(mp.cmd_install(self.target, self.source), 0)
                self.assertTrue(self.read_target().startswith(original))

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

    def test_missing_final_newline_round_trip_and_upgrade(self):
        for original in (
            b"personal notes",
            b"first\nlast",
            b"first\r\nlast",
            b"first\r\nsecond\nlast",
            b"notes  ",
            b"notes\r",
            b"first\r\nnotes\r",
        ):
            with self.subTest(original=original):
                self.write_target_bytes(original)
                self.assertEqual(mp.cmd_install(self.target, self.source), 0)
                installed = self.read_target_bytes()
                self.assertIn(mp.NO_FINAL_NEWLINE.encode("utf-8"), installed)
                self.assertEqual(mp.cmd_install(self.target, self.source), 0)
                self.assertEqual(self.read_target_bytes(), installed)
                self.assertEqual(mp.cmd_remove(self.target), 0)
                self.assertEqual(self.read_target_bytes(), original)

    def test_mixed_line_endings_round_trip(self):
        original = b"first\r\nsecond\nthird\r\n"
        self.write_target_bytes(original)
        mp.cmd_install(self.target, self.source)
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), original)

    def test_non_newline_separators_do_not_create_marker_lines(self):
        original = ("notes\v" + mp.BEGIN + "\fstill personal").encode("utf-8")
        self.write_target_bytes(original)
        mp.cmd_install(self.target, self.source)
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), original)

    def test_remove_missing_newline_metadata_preserves_appended_user_content(self):
        self.write_target_bytes(b"personal notes")
        mp.cmd_install(self.target, self.source)
        self.write_target_bytes(self.read_target_bytes() + b"new personal content\n")
        mp.cmd_remove(self.target)
        self.assertEqual(self.read_target_bytes(), b"personal notesnew personal content\n")

    def test_invalid_missing_newline_metadata_aborts_without_writing(self):
        for original in (
            mp.BEGIN + "\n" + mp.NO_FINAL_NEWLINE + "\n" + mp.END + "\n",
            "user\n\n" + mp.BEGIN + "\ncontent\n" + mp.NO_FINAL_NEWLINE + "\n" + mp.END + "\n",
            "user\n\n" + mp.BEGIN + "\r\n" + mp.NO_FINAL_NEWLINE + "\r\n" + mp.END + "\r\n",
        ):
            with self.subTest(original=original):
                self.write_target_bytes(original.encode("utf-8"))
                for command in (
                    ["_merge_playbook.py", "remove", self.target],
                    ["_merge_playbook.py", "install", self.target, self.source],
                ):
                    self.assertEqual(mp.main(command), 1)
                    self.assertEqual(self.read_target_bytes(), original.encode("utf-8"))

    def test_install_preserves_existing_file_permissions(self):
        # _atomic_write's temp-file-then-replace must not silently widen (or
        # narrow) an existing target's mode to whatever the process umask
        # would otherwise produce.
        self.write_target("my own instructions\n")
        os.chmod(self.target, 0o600)
        mp.cmd_install(self.target, self.source)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o600)
        mp.cmd_remove(self.target)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o600)

    def test_install_new_file_gets_umask_default_mode(self):
        # No pre-existing file to preserve the mode of; the temp file's
        # umask-derived default mode should pass through untouched.
        old_umask = os.umask(0o022)
        try:
            mp.cmd_install(self.target, self.source)
        finally:
            os.umask(old_umask)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o644)

    def test_install_rejects_marker_in_source(self):
        bad_source = os.path.join(self.dir, "bad_source.md")
        with open(bad_source, "w", encoding="utf-8") as fh:
            fh.write("legit line\n" + mp.BEGIN + "\nsneaky\n")
        self.write_target("user content\n")
        rc = mp.cmd_install(self.target, bad_source)
        self.assertEqual(rc, 1)
        # Target must be untouched (no managed block written).
        self.assertEqual(self.read_target(), "user content\n")

    def test_install_rejects_metadata_in_source(self):
        self.write_target("user content\n")
        with open(self.source, "w", encoding="utf-8") as file:
            file.write(mp.NO_FINAL_NEWLINE + "\n")
        self.assertEqual(mp.cmd_install(self.target, self.source), 1)
        self.assertEqual(self.read_target(), "user content\n")


if __name__ == "__main__":
    unittest.main()
