"""Claude Code integration: CLAUDE.md shape and the GUI-launch hook.

No GTK, display or receiver. The one subprocess test only runs the hook script
with a JSON payload on stdin.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "claude_hooks" / "block_gui_launch.py"

_spec = importlib.util.spec_from_file_location("block_gui_launch", HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


class ClaudeMdTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_imports_agents_md_so_there_is_one_source_of_truth(self):
        # Claude Code reads CLAUDE.md instead of AGENTS.md when both exist.
        body = re.sub(r"<!--.*?-->", "", self.text, flags=re.S).lstrip()
        self.assertTrue(body.startswith("@AGENTS.md"))

    def test_stays_short(self):
        self.assertLess(len(self.text.splitlines()), 60)

    def test_local_overrides_are_gitignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("CLAUDE.local.md", ignore)
        self.assertIn(".claude/settings.local.json", ignore)

    def test_referenced_repo_files_exist(self):
        for rel in re.findall(r"`((?:src|scripts|docs|\.claude)/[\w./-]+)`", self.text):
            with self.subTest(path=rel):
                self.assertTrue((ROOT / rel).exists(), rel)
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", self.text):
            if not target.startswith(("http://", "https://")):
                with self.subTest(link=target):
                    self.assertTrue((ROOT / target).is_file(), target)

    def test_efficiency_anchor_used_by_claude_md_exists(self):
        workflow = (ROOT / "docs/agents/efficiency.md").read_text(encoding="utf-8")
        self.assertIn("## GitHub CLI in Claude Code web sessions", workflow)


class HookConfigTests(unittest.TestCase):
    def test_settings_wire_the_hook_to_bash(self):
        settings = json.loads((ROOT / ".claude/settings.json").read_text("utf-8"))
        entry = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertIn("block_gui_launch.py", entry["hooks"][0]["command"])
        self.assertTrue(HOOK.is_file())


class BlockGuiLaunchTests(unittest.TestCase):
    BLOCKED = (
        "./smoothcast",
        "smoothcast",
        "/home/me/smoothcast/smoothcast --self-test",
        "cd /tmp && ./smoothcast",
        "gtk-launch local.cast-control",
        "python3 smoothcast",
        "python3 src/cast_control.py",
        "python3 -I src/cast_control.py --self-test",
        "python3 -m cast_control",
        "DISPLAY=:0 python3 smoothcast",
        "sudo -u me ./smoothcast",
        "nohup ./smoothcast &",
        "pytest -q ; ./smoothcast",
        "python3.13 setup/launch.py",
    )
    ALLOWED = (
        "./smoothcast --version",
        "smoothcast -V",
        "smoothcast --diagnostics /tmp/x.json",
        "smoothcast --network-check 192.168.1.5",
        "smoothcast --library-index list --limit 5",
        "python3 smoothcast --version",
        "python3 src/version.py",
        "python3 -m pytest -q tests",
        "python3 -m compileall -q src scripts setup tests",
        "python3 scripts/test_gui_isolated.py",
        "python3 scripts/ticket_digest.py --next",
        "cat smoothcast",
        "grep -n gtk-launch README.md",
        "git add smoothcast src/cast_control.py",
        "ls ./smoothcast",
        "bash setup/linuxsetup.sh --check",
        "echo \"unbalanced",
        "",
    )

    def test_blocks_commands_that_open_the_window(self):
        for command in self.BLOCKED:
            with self.subTest(command=command):
                self.assertIsNotNone(hook.decide(command))

    def test_allows_safe_and_unrelated_commands(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(hook.decide(command))

    def run_hook(self, payload):
        return subprocess.run(
            [sys.executable, "-I", str(HOOK)], input=payload,
            capture_output=True, text=True, timeout=20,
        )

    def test_exit_code_two_blocks_and_explains(self):
        result = self.run_hook(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "./smoothcast"}}))
        self.assertEqual(result.returncode, 2)
        self.assertIn("test_gui_isolated.py", result.stderr)

    def test_exit_code_zero_allows(self):
        result = self.run_hook(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "python3 -m pytest -q tests"}}))
        self.assertEqual(result.returncode, 0)

    def test_unrecognised_payload_fails_open(self):
        for payload in ("", "not json", "{}", json.dumps({"tool_input": {"command": 7}})):
            with self.subTest(payload=payload):
                self.assertEqual(self.run_hook(payload).returncode, 0)


if __name__ == "__main__":
    unittest.main()
