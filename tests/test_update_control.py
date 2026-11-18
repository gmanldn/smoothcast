"""Regression tests for the non-blocking git update worker."""
from pathlib import Path
from unittest import mock
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import update_control


class UpdateControlTests(unittest.TestCase):
    def test_release_archive_skips_git(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(update_control.subprocess, "run") as run:
                self.assertIsNone(update_control.refresh_checkout(Path(d)))
                run.assert_not_called()

    def test_update_returns_restart_notice(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".git").mkdir()
            completed = subprocess.CompletedProcess(
                ["git"], 0, "Updating abc..def\nFast-forward\n", "",
            )
            with mock.patch.object(update_control.subprocess, "run", return_value=completed) as run:
                self.assertIn("restart", update_control.refresh_checkout(repo))
                self.assertEqual(run.call_args.kwargs["cwd"], repo)
                self.assertEqual(run.call_args.kwargs["timeout"], 8)

    def test_already_current_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".git").mkdir()
            with mock.patch.object(update_control.subprocess, "run", return_value=
                            subprocess.CompletedProcess(["git"], 0, "Already up to date.\n", "")):
                self.assertIsNone(update_control.refresh_checkout(repo))

    def test_offline_timeout_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".git").mkdir()
            with mock.patch.object(update_control.subprocess, "run",
                                   side_effect=subprocess.TimeoutExpired("git", 8)):
                self.assertIsNone(update_control.refresh_checkout(repo))


if __name__ == "__main__":
    unittest.main()
