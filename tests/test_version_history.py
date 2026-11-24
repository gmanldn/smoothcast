"""Regression tests for read-only, multi-agent version history validation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci/check_version_history.py"
spec = importlib.util.spec_from_file_location("check_version_history", SCRIPT)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def source(major=1, minor=2, patch=1):
    return f"MAJOR = {major}\nMINOR = {minor}\nPATCH = {patch}\n"


class VersionHistoryTests(unittest.TestCase):
    def test_exactly_one_literal_bounded_version(self):
        self.assertEqual(guard.parse_version(source()), (1, 2, 1))
        for candidate in (
            source() + "PATCH = 2\n",
            "MAJOR = True\nMINOR = 2\nPATCH = 1\n",
            "MAJOR = 1\nMINOR = -2\nPATCH = 1\n",
            "MAJOR = 1\nMINOR = 2\nPATCH = 2**8\n",
            "MAJOR = 1\nMINOR = 2\n",
            source() + "PATCH += 1\n",
            source() + "PATCH: int = 2\n",
            source() + "if True:\n    PATCH = 3\n",
            source() + "(PATCH := 7)\n",
            source() + "for PATCH in range(2):\n    pass\n",
            source() + "del PATCH\n",
            source() + "def PATCH():\n    pass\n",
            source() + "from math import pi as PATCH\n",
            source() + "MAJOR, PATCH = (3, 4)\n",
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(guard.VersionHistoryError):
                    guard.parse_version(candidate)

    def test_only_single_step_and_unchanged_transitions(self):
        before = (1, 2, 51)
        for after in ((1, 2, 51), (1, 2, 52), (1, 3, 0), (2, 0, 0)):
            self.assertTrue(guard.valid_transition(before, after))
        for after in ((1, 2, 50), (1, 2, 53), (1, 3, 1), (2, 1, 0), (1, 1, 999)):
            self.assertFalse(guard.valid_transition(before, after))

    def test_range_checks_intermediate_commits_not_just_tip(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(directory), *args], text=True
                ).strip()
            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Version Guard Test")
            (directory / "src").mkdir()
            version = directory / "src/version.py"
            def commit(value, name):
                version.write_text(source(patch=value), encoding="utf-8")
                git("add", "src/version.py")
                git("commit", "-qm", name)
                return git("rev-parse", "HEAD")
            first = commit(1, "base")
            commit(2, "valid increment")
            commit(4, "invalid skipped patch")
            (directory / "notes.txt").write_text("unrelated", encoding="utf-8")
            git("add", "notes.txt")
            git("commit", "-qm", "unrelated tip")
            last = git("rev-parse", "HEAD")
            previous_git = guard.git
            try:
                def local_git(*args, missing_ok=False):
                    proc = subprocess.run(
                        ["git", "-C", str(directory), *args], capture_output=True, text=True
                    )
                    if proc.returncode:
                        if missing_ok:
                            return None
                        raise guard.VersionHistoryError(proc.stderr.strip() or "git failed")
                    return proc.stdout.strip()
                guard.git = local_git
                with self.assertRaisesRegex(guard.VersionHistoryError, "only unchanged"):
                    guard.check_range(first, last)
            finally:
                guard.git = previous_git


if __name__ == "__main__":
    unittest.main()
