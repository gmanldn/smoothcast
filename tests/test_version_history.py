"""Regression tests for read-only, multi-agent version history validation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

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


class TicketPatchHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Version Guard Test")
        (self.root / "src").mkdir()
        self.base = self.commit(1, "base")
        patcher = mock.patch.object(guard, "git", self.git)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args, missing_ok=False):
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True)
        if proc.returncode:
            if missing_ok:
                return None
            raise guard.VersionHistoryError(proc.stderr.strip() or "git failed")
        return proc.stdout.strip()

    def commit(self, patch, subject, *, extra=False, source_suffix=""):
        (self.root / "src/version.py").write_text(
            source(patch=patch) + source_suffix, encoding="utf-8")
        self.git("add", "src/version.py")
        if extra:
            (self.root / "extra.txt").write_text(subject, encoding="utf-8")
            self.git("add", "extra.txt")
        self.git("commit", "--allow-empty", "-qm", subject)
        return self.git("rev-parse", "HEAD")

    def test_mixed_historical_formats_reserve_exact_issue_ids(self):
        first = self.commit(2, "chore(version): PATCH for issue #58")
        second = self.commit(3, "chore(version): PATCH 1.2.3 for issue #583 [sc-auto-patch]")
        self.assertEqual(guard.check_range(self.base, second), 2)
        duplicate = self.commit(4, "chore(version): PATCH for issue #58 [sc-auto-patch]")
        with self.assertRaisesRegex(guard.VersionHistoryError, "duplicate PATCH.*#58"):
            guard.check_range(second, duplicate)
        with self.assertRaisesRegex(guard.VersionHistoryError, "duplicate PATCH.*#58"):
            guard.check_range(self.base, duplicate)
        self.assertEqual(guard.check_range(self.base, first), 1)

    def test_existing_duplicates_do_not_block_unrelated_progress_or_new_ticket(self):
        self.commit(2, "chore(version): PATCH for issue #595 [sc-auto-patch]")
        debt = self.commit(3, "chore(version): PATCH for issue #595")
        progress = self.commit(3, "fix: unrelated work")
        self.assertEqual(guard.check_range(debt, progress), 1)
        fresh = self.commit(4, "chore(version): PATCH for issue #596 [sc-auto-patch]")
        self.assertEqual(guard.check_range(debt, fresh), 2)
        duplicate = self.commit(5, "chore(version): PATCH for issue #595")
        with self.assertRaisesRegex(guard.VersionHistoryError, "duplicate PATCH.*#595"):
            guard.check_range(fresh, duplicate)

    def test_new_malformed_or_noncanonical_assignment_fails(self):
        for patch, title, extra, suffix, error in (
            (2, "chore(version): PATCH for issue #0", False, "", "malformed"),
            (2, "chore(version): PATCH 1.2.9 for issue #12", False, "", "subject/version"),
            (1, "chore(version): PATCH for issue #12", False, "", "change only"),
            (2, "chore(version): PATCH for issue #12", True, "", "change only"),
            (2, "chore(version): PATCH for issue #12", False, "extra = 1\n", "exact one-step"),
        ):
            with self.subTest(title=title, patch=patch, extra=extra, suffix=suffix):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fd")
                tip = self.commit(patch, title, extra=extra, source_suffix=suffix)
                with self.assertRaisesRegex(guard.VersionHistoryError, error):
                    guard.check_range(self.base, tip)

    def test_merge_cannot_introduce_second_assignment_from_side_branch(self):
        main = self.git("rev-parse", "--abbrev-ref", "HEAD")
        self.git("checkout", "-qb", "side")
        self.commit(2, "chore(version): PATCH for issue #42")
        self.git("checkout", "-q", main)
        prior = self.commit(2, "chore(version): PATCH for issue #42 [sc-auto-patch]")
        self.git("merge", "--no-ff", "-qm", "merge side", "side")
        merged = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(guard.VersionHistoryError, "duplicate PATCH.*#42"):
            guard.check_range(prior, merged)

    def test_prefix_colliding_issue_ids_stay_distinct(self):
        short = self.commit(2, "chore(version): PATCH for issue #12 [sc-auto-patch]")
        long = self.commit(3, "chore(version): PATCH for issue #123 [sc-auto-patch]")
        self.assertEqual(guard.check_range(self.base, long), 2)
        self.assertEqual(guard.check_range(short, long), 1)
        duplicate = self.commit(4, "chore(version): PATCH for issue #123")
        with self.assertRaisesRegex(guard.VersionHistoryError, "duplicate PATCH.*#123"):
            guard.check_range(long, duplicate)


if __name__ == "__main__":
    unittest.main()
