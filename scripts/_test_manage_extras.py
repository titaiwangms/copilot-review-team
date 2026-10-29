#!/usr/bin/env python3
"""Stdlib-only tests; all deployment writes stay inside temporary directories."""
import contextlib
import errno
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _manage_extras as extras
import _merge_playbook as playbook
from _check_frontmatter import check_frontmatter
from _check_tools import tool_policy_errors
from _lib_parsing import parse_tools

ROOT = Path(__file__).resolve().parent.parent
AGENT = "agents/local-example.agent.md"
INSTRUCTION = "instructions/copilot-review-team-example.instructions.md"
TEAM_INSTRUCTION = "instructions/copilot-review-team.instructions.md"
GLOBAL_COMMENT = (
    b"<!-- Review team instructions: instructions/copilot-review-team.instructions.md -->\n"
)


class ExtrasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.source = self.root / "source"
        self.write(self.source / AGENT, "agent\n")
        self.write(self.source / INSTRUCTION, "instructions\n")
        self.counter = 0

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_action(self, action):
        self.counter += 1
        backup = self.home / (".backup-test-%s" % self.counter)
        with contextlib.redirect_stdout(io.StringIO()):
            extras.manage(action, self.home, backup, source=self.source)
        return backup

    def test_install_repeat_and_remove_preserve_unrelated_files(self):
        unrelated = self.home / "instructions/personal.instructions.md"
        self.write(unrelated, "personal")
        self.run_action("install")
        first = (self.home / extras.MANIFEST).read_bytes()
        backup = self.run_action("install")
        self.assertFalse(backup.exists())
        self.assertEqual((self.home / extras.MANIFEST).read_bytes(), first)
        self.run_action("remove")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.assertEqual(unrelated.read_text(), "personal")

    def test_existing_files_are_backed_up(self):
        self.write(self.home / AGENT, "old agent")
        self.write(self.home / INSTRUCTION, "old instruction")
        backup = self.run_action("install")
        self.assertEqual((backup / AGENT).read_text(), "old agent")
        self.assertEqual((backup / INSTRUCTION).read_text(), "old instruction")

    def test_first_ownership_write_failure_does_not_deploy_files(self):
        write = extras.atomic_write

        def fail_manifest(target, data, mode):
            if target == self.home / extras.MANIFEST:
                raise OSError(errno.ENOSPC, "injected manifest write failure")
            write(target, data, mode)

        with mock.patch.object(extras, "atomic_write", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.run_action("install")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_final_manifest_write_failure_keeps_deployed_files_removable(self):
        write = extras.atomic_write

        def fail_final_manifest(target, data, mode):
            if target == self.home / extras.MANIFEST and (self.home / INSTRUCTION).exists():
                raise OSError(errno.ENOSPC, "injected final manifest write failure")
            write(target, data, mode)

        with mock.patch.object(extras, "atomic_write", side_effect=fail_final_manifest):
            with self.assertRaises(OSError):
                self.run_action("install")
        self.assertEqual(extras.read_manifest(self.home), {AGENT, INSTRUCTION})
        self.assertEqual((self.home / AGENT).read_text(), "agent\n")
        self.assertEqual((self.home / INSTRUCTION).read_text(), "instructions\n")
        self.run_action("remove")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_deployment_failure_leaves_partial_install_recorded(self):
        write = extras.atomic_write

        def fail_instruction(target, data, mode):
            if target == self.home / INSTRUCTION:
                raise OSError(errno.ENOSPC, "injected deployment failure")
            write(target, data, mode)

        with mock.patch.object(extras, "atomic_write", side_effect=fail_instruction):
            with self.assertRaises(OSError):
                self.run_action("install")
        self.assertTrue((self.home / AGENT).exists())
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.assertEqual(extras.read_manifest(self.home), {AGENT, INSTRUCTION})
        self.run_action("remove")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_upgrade_ownership_failure_preserves_unclaimed_personal_file(self):
        self.run_action("install")
        self.write(self.source / AGENT, "updated\n")
        added = "agents/local-new.agent.md"
        self.write(self.source / added, "new\n")
        self.write(self.home / added, "personal\n")
        write = extras.atomic_write

        def fail_manifest(target, data, mode):
            if target == self.home / extras.MANIFEST:
                raise OSError(errno.ENOSPC, "injected ownership write failure")
            write(target, data, mode)

        with mock.patch.object(extras, "atomic_write", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                self.run_action("install")
        self.assertEqual((self.home / AGENT).read_text(), "updated\n")
        self.assertEqual(extras.read_manifest(self.home), {AGENT, INSTRUCTION})
        self.assertEqual((self.home / added).read_text(), "personal\n")
        self.assertEqual((self.home / ".backup-test-2" / added).read_text(), "personal\n")
        self.run_action("remove")
        self.assertEqual((self.home / added).read_text(), "personal\n")

    def test_failed_upgrade_finalization_keeps_union_until_cleanup(self):
        self.run_action("install")
        (self.source / INSTRUCTION).unlink()
        added = "agents/local-new.agent.md"
        self.write(self.source / added, "new\n")
        write = extras.atomic_write

        def fail_final_manifest(target, data, mode):
            if target == self.home / extras.MANIFEST and not (self.home / INSTRUCTION).exists():
                raise OSError(errno.ENOSPC, "injected final manifest write failure")
            write(target, data, mode)

        with mock.patch.object(extras, "atomic_write", side_effect=fail_final_manifest):
            with self.assertRaises(OSError):
                self.run_action("install")
        self.assertEqual(extras.read_manifest(self.home), {AGENT, INSTRUCTION, added})
        self.assertTrue((self.home / added).exists())
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.run_action("remove")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / added).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_upgrade_prunes_only_recorded_files(self):
        self.run_action("install")
        (self.source / INSTRUCTION).unlink()
        unrelated = self.home / "agents/local-personal.agent.md"
        self.write(unrelated, "personal")
        backup = self.run_action("install")
        self.assertEqual((backup / INSTRUCTION).read_text(), "instructions\n")
        self.assertFalse((self.home / INSTRUCTION).exists())
        self.assertEqual(unrelated.read_text(), "personal")

    def test_leaf_symlink_is_backed_up_and_replaced_without_writing_referent(self):
        outside = self.root / "outside"
        self.write(outside, "untouched")
        target = self.home / AGENT
        target.parent.mkdir()
        target.symlink_to(outside)
        backup = self.run_action("install")
        self.assertFalse(target.is_symlink())
        self.assertTrue((backup / AGENT).is_symlink())
        self.assertEqual(outside.read_text(), "untouched")

    def test_symlinked_parent_aborts_before_any_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / "instructions").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertFalse((self.home / AGENT).exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_manifest_aborts_install_and_remove(self):
        for name in ("../victim", "agents/../../victim", "/tmp/victim",
                     "agents//local-example.agent.md", "settings.json", ""):
            with self.subTest(name=name):
                self.write(self.home / extras.MANIFEST, name + "\n")
                for action in ("install", "remove"):
                    with self.assertRaises(ValueError):
                        self.run_action(action)
                self.assertFalse((self.home / AGENT).exists())

    def test_symlink_manifest_aborts(self):
        victim = self.root / "victim"
        self.write(victim, AGENT + "\n")
        (self.home / extras.MANIFEST).symlink_to(victim)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertEqual(victim.read_text(), AGENT + "\n")

    def test_directory_target_aborts_before_any_write(self):
        (self.home / INSTRUCTION).mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertFalse((self.home / AGENT).exists())

    def test_fifo_target_aborts_before_any_write(self):
        target = self.home / INSTRUCTION
        target.parent.mkdir()
        os.mkfifo(target)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertFalse((self.home / AGENT).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_check_is_read_only(self):
        self.run_action("check")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_uninstall_dangling_symlink_does_not_touch_referent(self):
        self.run_action("install")
        target = self.home / AGENT
        target.unlink()
        target.symlink_to(self.root / "missing")
        backup = self.run_action("remove")
        self.assertFalse(target.is_symlink())
        self.assertTrue((backup / AGENT).is_symlink())
        self.assertFalse((self.root / "missing").exists())

    def test_source_symlink_is_rejected(self):
        source = self.source / AGENT
        source.unlink()
        source.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            self.run_action("install")

    def test_backup_symlink_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / ".backup-test-1").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertEqual(list(outside.iterdir()), [])


class InstallIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "copilot"
        self.env = dict(os.environ, COPILOT_HOME=str(self.home),
                        HOME=str(Path(temporary.name) / "user-home"))

    def run_script(self, script, *args, expected=0, input_text=None):
        result = subprocess.run(
            ["bash", str(ROOT / script), *args], env=self.env, cwd=ROOT,
            text=True, capture_output=True, timeout=30, check=False, input=input_text,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def installed_agents(self):
        return {p.name for p in (self.home / "agents").glob("*.agent.md")}

    def snapshot(self):
        return {p.relative_to(self.home).as_posix(): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def expected_team_content(self):
        return b'---\napplyTo: "**"\n---\n\n' + (ROOT / "copilot-instructions.md").read_bytes()

    def test_default_install_is_review_only(self):
        self.run_script("install.sh")
        expected = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        self.assertEqual(self.installed_agents(), expected)
        self.assertEqual((self.home / TEAM_INSTRUCTION).read_bytes(), self.expected_team_content())
        self.assertEqual(list((self.home / "instructions").iterdir()),
                         [self.home / TEAM_INSTRUCTION])
        self.assertFalse((self.home / "copilot-instructions.md").exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.run_script("uninstall.sh")
        self.assertFalse((self.home / TEAM_INSTRUCTION).exists())
        self.assertFalse((self.home / "copilot-instructions.md").exists())

    def test_repeat_install_replaces_entire_dedicated_file_and_backs_it_up(self):
        self.run_script("install.sh")
        target = self.home / TEAM_INSTRUCTION
        original = b"custom edits\r\n# Personal\nno final newline"
        target.write_bytes(original)
        self.run_script("install.sh")
        self.assertEqual(target.read_bytes(), self.expected_team_content())
        backups = list(self.home.glob(".backup-*/" + TEAM_INSTRUCTION))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.run_script("install.sh")
        self.assertEqual(target.read_bytes(), self.expected_team_content())
        self.assertEqual(len(list(self.home.glob(".backup-*/" + TEAM_INSTRUCTION))), 2)

    def test_unset_copilot_home_uses_isolated_home_default(self):
        del self.env["COPILOT_HOME"]
        self.home = Path(self.env["HOME"]) / ".copilot"
        self.run_script("install.sh")
        self.assertEqual((self.home / TEAM_INSTRUCTION).read_bytes(), self.expected_team_content())
        self.run_script("uninstall.sh")
        self.assertFalse((self.home / TEAM_INSTRUCTION).exists())

    def test_default_preserves_arbitrary_global_markdown_bytes(self):
        self.home.mkdir()
        target = self.home / "copilot-instructions.md"
        original = (
            b"\xef\xbb\xbf#\tPersonal ###\r\nkeep notes  \r\n\r\n"
            + (ROOT / "copilot-instructions.md").read_bytes()
            + b"\nPersonal instructions\n=====\n```inline```\n```unclosed\nno final newline"
        )
        target.write_bytes(original)
        for args in ((), ("--with-extras",)):
            result = self.run_script("install.sh", *args)
            self.assertIn("global instructions remain active and untouched", result.stdout)
            self.assertIn("Clean up old team rules manually", result.stdout)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(self.home.glob(".backup-*/copilot-instructions.md")), [])
        self.run_script("uninstall.sh")
        self.assertEqual(target.read_bytes(), original)

    def test_overwrite_global_replaces_everything_with_only_a_comment(self):
        self.home.mkdir()
        target = self.home / "copilot-instructions.md"
        original = (
            b"\xef\xbb\xbf# Personal\r\nprivate notes\r\n# Build\nbuild rules\n"
            b"# Thinking\nthinking rules\n" + (ROOT / "copilot-instructions.md").read_bytes()
            + b"\n" + playbook.BEGIN.encode("utf-8") + b"\nunbalanced marker"
        )
        target.write_bytes(original)
        result = self.run_script("install.sh", "--overwrite-global-instructions")
        self.assertIn("WARNING: replacing ENTIRE copilot-instructions.md", result.stdout)
        self.assertIn("all personal/build/thinking instructions in that file will be removed",
                      result.stdout)
        backups = list(self.home.glob(".backup-*/copilot-instructions.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(target.read_bytes(), GLOBAL_COMMENT)
        self.assertEqual((self.home / TEAM_INSTRUCTION).read_bytes(), self.expected_team_content())
        self.run_script("uninstall.sh")
        self.assertEqual(target.read_bytes(), GLOBAL_COMMENT)

    def test_overwrite_global_when_absent_requires_no_prompt_or_backup(self):
        self.run_script("install.sh", "--overwrite-global-instructions")
        self.assertEqual((self.home / "copilot-instructions.md").read_bytes(), GLOBAL_COMMENT)
        self.assertEqual(list(self.home.glob(".backup-*/copilot-instructions.md")), [])

    def test_empty_global_stays_empty_without_notice(self):
        self.home.mkdir()
        target = self.home / "copilot-instructions.md"
        target.write_bytes(b"")
        result = self.run_script("install.sh")
        self.assertNotIn("global instructions remain active", result.stdout)
        self.assertEqual(target.read_bytes(), b"")
        self.run_script("uninstall.sh")
        self.assertEqual(target.read_bytes(), b"")

    def test_legacy_managed_global_is_untouched_on_install_and_stripped_on_uninstall(self):
        self.home.mkdir()
        target = self.home / "copilot-instructions.md"
        personal = b"# Personal\r\nkeep notes without final newline"
        target.write_bytes(personal)
        with contextlib.redirect_stdout(io.StringIO()):
            playbook.cmd_install(str(target), str(ROOT / "copilot-instructions.md"))
        original = target.read_bytes()
        self.run_script("install.sh")
        self.assertEqual(target.read_bytes(), original)
        self.run_script("uninstall.sh")
        self.assertEqual(target.read_bytes(), personal)
        self.assertFalse((self.home / TEAM_INSTRUCTION).exists())

    def test_dedicated_leaf_symlink_is_backed_up_replaced_and_removed_safely(self):
        target = self.home / TEAM_INSTRUCTION
        target.parent.mkdir(parents=True)
        outside = self.home.parent / "outside"
        outside.write_bytes(b"untouched\n")
        target.symlink_to(outside)
        self.run_script("install.sh")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), self.expected_team_content())
        backups = list(self.home.glob(".backup-*/" + TEAM_INSTRUCTION))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_symlink())
        target.unlink()
        target.symlink_to(outside)
        self.run_script("uninstall.sh")
        self.assertFalse(target.is_symlink())
        self.assertEqual(outside.read_bytes(), b"untouched\n")

    def test_global_leaf_symlink_is_only_replaced_with_explicit_consent(self):
        self.home.mkdir()
        outside = self.home.parent / "outside"
        outside.write_bytes(b"personal instructions\n")
        target = self.home / "copilot-instructions.md"
        target.symlink_to(outside)
        self.run_script("install.sh")
        self.assertTrue(target.is_symlink())
        self.assertEqual(list(self.home.glob(".backup-*/copilot-instructions.md")), [])
        self.run_script("install.sh", "--overwrite-global-instructions")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), GLOBAL_COMMENT)
        backups = list(self.home.glob(".backup-*/copilot-instructions.md"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_symlink())
        self.assertEqual(outside.read_bytes(), b"personal instructions\n")

    def test_dangling_instruction_symlinks_are_replaced_without_creating_referents(self):
        self.home.mkdir()
        missing = self.home.parent / "missing"
        for name in (TEAM_INSTRUCTION, "copilot-instructions.md"):
            target = self.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(missing)
        self.run_script("install.sh", "--overwrite-global-instructions")
        for name in (TEAM_INSTRUCTION, "copilot-instructions.md"):
            self.assertFalse((self.home / name).is_symlink())
            self.assertTrue(next(self.home.glob(".backup-*/" + name)).is_symlink())
        target = self.home / TEAM_INSTRUCTION
        target.unlink()
        target.symlink_to(missing)
        self.run_script("uninstall.sh")
        self.assertFalse(target.is_symlink())
        self.assertFalse(missing.exists())

    def test_symlinked_instruction_directory_aborts_install_and_uninstall_before_changes(self):
        outside = self.home.parent / "outside"
        outside.mkdir()
        self.home.mkdir()
        (self.home / "instructions").symlink_to(outside, target_is_directory=True)
        for command in ("install.sh", "uninstall.sh"):
            result = self.run_script(command, expected=1)
            self.assertIn("unsafe parent directory", result.stderr)
            self.assertFalse((self.home / "agents").exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_unsafe_instruction_targets_abort_before_core_install(self):
        for name, args in (
            (TEAM_INSTRUCTION, ()),
            ("copilot-instructions.md", ("--overwrite-global-instructions",)),
        ):
            for kind in ("directory", "directory-symlink", "fifo"):
                with self.subTest(name=name, kind=kind):
                    target = self.home / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if kind == "directory":
                        target.mkdir()
                    elif kind == "directory-symlink":
                        target.symlink_to(target.parent, target_is_directory=True)
                    else:
                        os.mkfifo(target)
                    result = self.run_script("install.sh", *args, expected=1)
                    self.assertIn("expected a", result.stderr)
                    self.assertFalse((self.home / "agents").exists())
                    if kind == "directory":
                        target.rmdir()
                    else:
                        target.unlink()

    def test_purge_global_still_requires_confirmation(self):
        for reply, removed in (("n\n", False), ("yes\n", True)):
            with self.subTest(reply=reply):
                self.run_script("install.sh", "--overwrite-global-instructions")
                self.run_script("uninstall.sh", "--purge-playbook", input_text=reply)
                self.assertEqual((self.home / "copilot-instructions.md").exists(), not removed)
                self.assertFalse((self.home / TEAM_INSTRUCTION).exists())

    def test_opt_in_persists_and_opt_out_clears_it(self):
        self.run_script("install.sh", "--with-extras")
        expected = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        expected |= {p.name for p in (ROOT / "extras/agents").glob("*.agent.md")}
        self.assertEqual(self.installed_agents(), expected)
        instructions = {p.name for p in (ROOT / "extras/instructions").glob("*.md")}
        instructions.add(Path(TEAM_INSTRUCTION).name)
        self.assertEqual({p.name for p in (self.home / "instructions").glob("*.md")},
                         instructions)
        self.run_script("install.sh")
        self.assertEqual(self.installed_agents(), expected)
        self.run_script("install.sh", "--without-extras")
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.assertFalse((self.home / "agents/local-openai-developer.agent.md").exists())
        self.run_script("install.sh")
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_shell_cleanup_after_failed_extras_manifest_finalization(self):
        self.home.mkdir()
        files = extras.source_files(ROOT / "extras")
        personal = self.home / "instructions/personal.instructions.md"
        personal.parent.mkdir()
        personal.write_text("personal\n", encoding="utf-8")
        write = extras.atomic_write

        def fail_final_manifest(target, data, mode):
            if target == self.home / extras.MANIFEST and all(
                (self.home / name).exists() for name in files
            ):
                raise OSError(errno.ENOSPC, "injected final manifest write failure")
            write(target, data, mode)

        for index, command in enumerate((("install.sh", "--without-extras"), ("uninstall.sh",))):
            with self.subTest(command=command):
                with mock.patch.object(extras, "atomic_write", side_effect=fail_final_manifest):
                    with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
                        extras.manage("install", self.home, self.home / (".backup-failed-%s" % index))
                self.assertEqual(extras.read_manifest(self.home), set(files))
                self.run_script(*command)
                self.assertFalse((self.home / extras.MANIFEST).exists())
                self.assertTrue(all(not (self.home / name).exists() for name in files))
                self.assertEqual(personal.read_text(), "personal\n")

    def test_full_uninstall_and_dry_run_preserve_personal_content(self):
        self.home.mkdir()
        personal = self.home / "copilot-instructions.md"
        personal.write_text("Personal instructions\n", encoding="utf-8")
        self.run_script("install.sh", "--with-extras")
        unrelated = self.home / "instructions/personal.instructions.md"
        unrelated.write_text("personal", encoding="utf-8")
        before = self.snapshot()
        self.run_script("uninstall.sh", "--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.run_script("uninstall.sh")
        self.assertEqual(self.installed_agents(), set())
        self.assertEqual(personal.read_text(), "Personal instructions\n")
        self.assertEqual(unrelated.read_text(), "personal")
        self.assertFalse((self.home / TEAM_INSTRUCTION).exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_bad_extras_manifest_aborts_before_core_changes(self):
        self.home.mkdir()
        (self.home / extras.MANIFEST).write_text("../victim\n", encoding="utf-8")
        self.run_script("install.sh", "--with-extras", expected=1)
        self.assertFalse((self.home / "agents").exists())
        self.run_script("uninstall.sh", expected=1)

    def test_update_and_uninstall_preserve_missing_final_newline(self):
        self.home.mkdir()
        personal = self.home / "copilot-instructions.md"
        original = b"personal\r\nnotes without final newline"
        personal.write_bytes(original)
        self.run_script("install.sh", "--with-extras")
        self.run_script("install.sh")
        self.run_script("uninstall.sh")
        self.assertEqual(personal.read_bytes(), original)

    def test_help_and_unknown_option_do_not_install(self):
        result = self.run_script("install.sh", "--help")
        self.assertIn("--overwrite-global-instructions", result.stdout)
        self.run_script("install.sh", "--unknown", expected=1)
        self.assertFalse(self.home.exists())

    def test_legacy_core_manifest_stays_review_only(self):
        self.home.mkdir()
        (self.home / ".copilot-review-team-manifest").write_text(
            "VERSION=2.4.0\nAGENT=local-code-reviewer.agent.md\n", encoding="utf-8"
        )
        self.run_script("install.sh")
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.assertEqual((self.home / TEAM_INSTRUCTION).read_bytes(), self.expected_team_content())

    def test_symlink_home_supports_core_and_optional_lifecycles(self):
        real_home = self.home.with_name("real-home")
        real_home.mkdir()
        self.home.symlink_to(real_home, target_is_directory=True)
        self.run_script("install.sh")
        self.run_script("uninstall.sh")
        self.assertEqual(self.installed_agents(), set())
        self.run_script("install.sh", "--with-extras")
        self.run_script("install.sh")
        self.assertTrue((self.home / extras.MANIFEST).exists())
        self.run_script("install.sh", "--without-extras")
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.run_script("install.sh", "--with-extras")
        self.run_script("uninstall.sh")
        self.assertEqual(self.installed_agents(), set())

    def test_fifo_extras_target_aborts_before_core_install(self):
        target = self.home / (
            "instructions/copilot-review-team-thinking.instructions.md"
        )
        target.parent.mkdir(parents=True)
        os.mkfifo(target)
        self.run_script("install.sh", "--with-extras", expected=1)
        self.assertFalse((self.home / "agents").exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_optional_sources_are_valid_and_disjoint_from_core(self):
        core = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        optional = list((ROOT / "extras/agents").glob("*.agent.md"))
        self.assertTrue(optional)
        self.assertFalse(core & {p.name for p in optional})
        for path in optional:
            with self.subTest(agent=path.name):
                text = path.read_text(encoding="utf-8")
                name = path.name[:-len(".agent.md")]
                self.assertEqual(check_frontmatter(text, name), [])
                self.assertEqual(tool_policy_errors(name, parse_tools(text)), [])


if __name__ == "__main__":
    unittest.main()
