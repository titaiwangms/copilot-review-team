#!/usr/bin/env python3
"""Stdlib-only tests; all deployment writes stay inside temporary directories."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _manage_extras as extras
from _check_frontmatter import check_frontmatter
from _check_tools import tool_policy_errors
from _lib_parsing import parse_tools

ROOT = Path(__file__).resolve().parent.parent
AGENT = "agents/local-example.agent.md"
INSTRUCTION = "instructions/copilot-review-team-example.instructions.md"


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
        self.env = dict(os.environ, COPILOT_HOME=str(self.home))

    def run_script(self, script, *args, expected=0):
        result = subprocess.run(
            ["bash", str(ROOT / script), *args], env=self.env, cwd=ROOT,
            text=True, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def installed_agents(self):
        return {p.name for p in (self.home / "agents").glob("*.agent.md")}

    def snapshot(self):
        return {p.relative_to(self.home).as_posix(): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def test_default_install_is_review_only(self):
        self.run_script("install.sh")
        expected = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        self.assertEqual(self.installed_agents(), expected)
        self.assertFalse((self.home / "instructions").exists())
        self.assertFalse((self.home / extras.MANIFEST).exists())

    def test_opt_in_persists_and_opt_out_clears_it(self):
        self.run_script("install.sh", "--with-extras")
        expected = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        expected |= {p.name for p in (ROOT / "extras/agents").glob("*.agent.md")}
        self.assertEqual(self.installed_agents(), expected)
        instructions = {p.name for p in (ROOT / "extras/instructions").glob("*.md")}
        self.assertEqual({p.name for p in (self.home / "instructions").glob("*.md")},
                         instructions)
        self.run_script("install.sh")
        self.assertEqual(self.installed_agents(), expected)
        self.run_script("install.sh", "--without-extras")
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.assertFalse((self.home / "agents/local-openai-developer.agent.md").exists())
        self.run_script("install.sh")
        self.assertFalse((self.home / extras.MANIFEST).exists())

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
        self.run_script("install.sh", "--help")
        self.run_script("install.sh", "--unknown", expected=1)
        self.assertFalse(self.home.exists())

    def test_legacy_core_manifest_stays_review_only(self):
        self.home.mkdir()
        (self.home / ".copilot-review-team-manifest").write_text(
            "VERSION=2.4.0\nAGENT=local-code-reviewer.agent.md\n", encoding="utf-8"
        )
        self.run_script("install.sh")
        self.assertFalse((self.home / extras.MANIFEST).exists())
        self.assertFalse((self.home / "instructions").exists())

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
