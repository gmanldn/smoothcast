"""Installed build identity regressions: no GUI, receiver or network."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
sys.path.insert(0, str(ROOT / "src"))
import checkout_refresh
import install_location
import version


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class InstalledBuildIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "checkout"
        self.target = Path(self.tmp.name) / "installed"
        self.source.mkdir()
        (self.source / "src").mkdir()
        (self.source / "setup").mkdir()
        (self.source / "src" / "player.py").write_text("old\n")
        (self.source / "setup" / "bootstrap.py").write_text("# bootstrap\n")
        (self.source / "pyproject.toml").write_text('[project]\nname = "smoothcast"\n')
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *args], text=True,
        ).strip()

    def test_clean_checkout_identity_survives_copy_without_git(self):
        sha = self.git("rev-parse", "HEAD")
        stamp = self.git("show", "-s", "--format=%cI", sha)
        expected_date = stamp[:10] + " " + stamp[11:13] + stamp[14:16]
        with install_location.installed_sources(self.source, self.target):
            self.assertFalse((self.target / ".git").exists())
            self.assertEqual(version.read_checkout_revision(self.target), sha)
            self.assertEqual(checkout_refresh.installed_revision(self.target), sha)
            self.assertEqual(version.read_checkout_commit_date(self.target), expected_date)
            self.assertEqual(version.read_checkout_commit_date(self.target, sha),
                             expected_date)

    def test_dirty_and_untracked_source_do_not_claim_clean_commit(self):
        for path in ("src/player.py", "src/new.py"):
            (self.source / path).write_text("dirty\n")
            with install_location.installed_sources(self.source, self.target):
                self.assertIsNone(version.read_checkout_revision(self.target))

    def test_source_changed_during_copy_does_not_claim_old_commit(self):
        sha = self.git("rev-parse", "HEAD")
        (self.target / "src").mkdir(parents=True)
        self.git("commit", "--allow-empty", "-qm", "new")
        install_location._record_source_revision(self.source, self.target, sha)
        self.assertIsNone(version.read_checkout_revision(self.target))

    def test_install_rollback_restores_previous_identity(self):
        old = self.git("rev-parse", "HEAD")
        stamp = self.git("show", "-s", "--format=%cI", old)
        old_date = stamp[:10] + " " + stamp[11:13] + stamp[14:16]
        with install_location.installed_sources(self.source, self.target):
            pass
        self.git("commit", "--allow-empty", "-qm", "new")
        with self.assertRaises(RuntimeError):
            with install_location.installed_sources(self.source, self.target):
                self.assertNotEqual(version.read_checkout_revision(self.target), old)
                raise RuntimeError("installation failed")
        self.assertEqual(version.read_checkout_revision(self.target), old)
        self.assertEqual(checkout_refresh.installed_revision(self.target), old)
        self.assertEqual(version.read_checkout_commit_date(self.target), old_date)

    def test_unknown_or_forged_source_marker_is_not_copied(self):
        shutil.rmtree(self.source / ".git")
        (self.source / "src" / install_location.BUILD_MARKER).write_text("a" * 40)
        with install_location.installed_sources(self.source, self.target):
            self.assertIsNone(version.read_checkout_revision(self.target))

    def test_malformed_and_oversized_marker_is_unknown(self):
        (self.target / "src").mkdir(parents=True)
        marker = self.target / "src" / install_location.BUILD_MARKER
        for value in ("a" * 39, "g" * 40, "a" * 10000, "a" * 40 + "x"):
            marker.write_text(value)
            self.assertIsNone(version.read_checkout_revision(self.target))

    def test_installed_marker_date_is_bound_to_its_revision(self):
        (self.target / "src").mkdir(parents=True)
        marker = self.target / "src" / install_location.BUILD_MARKER
        sha = "a" * 40
        marker.write_text(f"{sha}\n2026-11-09\n", encoding="ascii")
        self.assertEqual(version.read_checkout_revision(self.target), sha)
        self.assertEqual(version.read_checkout_commit_date(self.target), "2026-11-09")
        self.assertIsNone(version.read_checkout_commit_date(self.target, "b" * 40))
        marker.write_text(f"{sha}\n2026-11-09 0726\n", encoding="ascii")
        self.assertEqual(version.read_checkout_commit_date(self.target), "2026-11-09 0726")
        for date in ("not-a-date", "2026-13-40", "2026-11-09T00:00:00Z",
                     "2026-11-09 2460", "2026-11-09 726"):
            marker.write_text(f"{sha}\n{date}\n", encoding="ascii")
            self.assertIsNone(version.read_checkout_commit_date(self.target), date)
        marker.write_text(sha + "\n", encoding="ascii")
        self.assertIsNone(version.read_checkout_commit_date(self.target))

    def test_running_label_is_independent_of_subsequent_disk_reads(self):
        with mock.patch.object(version, "RUNNING_REVISION", "a" * 40):
            with mock.patch.object(version, "read_checkout_revision", return_value="b" * 40):
                self.assertEqual(version.running_label(), version.build_label("a" * 40))


if __name__ == "__main__":
    unittest.main()
