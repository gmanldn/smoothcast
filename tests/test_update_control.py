"""Regression tests for the non-blocking git update worker."""
from pathlib import Path
from unittest import mock
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import update_control
import version


class FakeGit:
    """Deterministic ``git`` stand-in keyed on the subcommand.

    ``heads`` is consumed in order, so the pre-pull and post-pull rev-parse
    calls can report a different HEAD without any locale-dependent output.
    """

    def __init__(self, *, branch="main", dirty="", heads=("old", "new"),
                 pull_rc=0, pull_error=None, revparse_fails=False,
                 status_fails=False):
        self.branch = branch
        self.dirty = dirty
        self.heads = list(heads)
        self.pull_rc = pull_rc
        self.pull_error = pull_error
        self.revparse_fails = revparse_fails
        self.status_fails = status_fails
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        sub = cmd[1]
        if sub == "rev-parse" and "--abbrev-ref" in cmd:
            return self._done(cmd, self.branch)
        if sub == "status":
            return self._done(cmd, self.dirty, rc=128 if self.status_fails else 0)
        if sub == "rev-parse":
            if self.revparse_fails:
                return self._done(cmd, "", rc=128)
            return self._done(cmd, self.heads.pop(0) if self.heads else "same")
        if sub == "pull":
            if self.pull_error is not None:
                raise self.pull_error
            return self._done(cmd, "", rc=self.pull_rc)
        raise AssertionError(f"unexpected git call: {cmd}")

    @staticmethod
    def _done(cmd, out, rc=0):
        return subprocess.CompletedProcess(cmd, rc, out, "")

    @property
    def pull_call(self):
        for cmd, kwargs in self.calls:
            if cmd[1] == "pull":
                return cmd, kwargs
        return None, None


class UpdateControlTests(unittest.TestCase):
    def _repo(self, d):
        repo = Path(d)
        (repo / ".git").mkdir()
        return repo

    def _patch(self, fake):
        return mock.patch.object(update_control.subprocess, "run", side_effect=fake)

    def _write_version(self, repo, patch):
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src/version.py").write_text(
            f"MAJOR = {version.MAJOR}\nMINOR = {version.MINOR}\nPATCH = {patch}\n",
            encoding="utf-8",
        )

    def test_release_archive_skips_git(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(update_control.subprocess, "run") as run:
                self.assertIsNone(update_control.refresh_checkout(Path(d)))
                run.assert_not_called()

    def test_clean_eligible_checkout_is_pulled_with_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit()
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            cmd, kwargs = fake.pull_call
            self.assertEqual(cmd, ["git", "pull", "--ff-only"])
            self.assertEqual(kwargs["cwd"], repo)
            self.assertEqual(kwargs["timeout"], 8)

    def test_dirty_checkout_is_never_pulled(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(dirty=" M AGENTS.md\n")
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            self.assertIsNone(fake.pull_call[0])

    def test_detached_head_is_never_pulled(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(branch="HEAD")
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            self.assertIsNone(fake.pull_call[0])

    def test_developer_branch_is_never_pulled(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(branch="fix/issue-109")
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            self.assertIsNone(fake.pull_call[0])

    def test_locale_independent_head_change_returns_release_notice(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            self._write_version(repo, version.PATCH + 1)
            # A localised or atypically quiet git prints nothing on the pull.
            fake = FakeGit(heads=("aaa", "bbb"))
            with self._patch(fake):
                notice = update_control.refresh_checkout(repo)
            self.assertIn(
                f"v{version.MAJOR}.{version.MINOR}.{version.PATCH + 1} downloaded",
                notice,
            )
            self.assertIn(f"running {version.label()}", notice)
            self.assertIn("Restart", notice)

    def test_head_change_without_release_bump_stays_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            self._write_version(repo, version.PATCH)
            fake = FakeGit(heads=("aaa", "bbb"))
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))

    def test_unchanged_head_is_silent_even_when_pull_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            self._write_version(repo, version.PATCH + 1)
            fake = FakeGit(heads=("same", "same"))
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))

    def test_failed_pull_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(pull_rc=1)
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))

    def test_unreadable_head_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(revparse_fails=True)
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            self.assertIsNone(fake.pull_call[0])

    def test_unreadable_status_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            fake = FakeGit(status_fails=True)
            with self._patch(fake):
                self.assertIsNone(update_control.refresh_checkout(repo))
            self.assertIsNone(fake.pull_call[0])

    def test_offline_timeout_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(d)
            with mock.patch.object(
                update_control.subprocess, "run",
                side_effect=subprocess.TimeoutExpired("git", 8),
            ):
                self.assertIsNone(update_control.refresh_checkout(repo))


if __name__ == "__main__":
    unittest.main()
