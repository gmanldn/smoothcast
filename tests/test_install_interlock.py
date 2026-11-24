"""Offline installer transaction-lock regression tests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import install_location


class InstallInterlockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.destination = self.root / "installed"

    def test_second_writer_and_launch_preflight_refused(self):
        with install_location._transaction_lock(self.destination):
            with self.assertRaises(install_location.InstallBusy):
                with install_location._transaction_lock(self.destination):
                    self.fail("second writer entered")
            with self.assertRaises(install_location.InstallBusy):
                install_location.check_install_idle(self.destination)
        install_location.check_install_idle(self.destination)

    def test_different_destinations_are_independent(self):
        with install_location._transaction_lock(self.destination):
            with install_location._transaction_lock(self.root / "other"):
                pass

    def test_crashed_process_releases_lock_without_unlink(self):
        script = (
            "import sys, os; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); import install_location as i; "
            "lock=i._transaction_lock(Path(sys.argv[2])); "
            "lock.__enter__(); os._exit(17)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(ROOT / "setup"), str(self.destination)],
            timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 17)
        self.assertTrue(install_location._lock_path(self.destination).is_file())
        with install_location._transaction_lock(self.destination):
            pass

    def test_missing_lock_preflight_is_read_only(self):
        install_location.check_install_idle(self.destination)
        self.assertFalse(install_location._lock_path(self.destination).exists())

    def test_lock_covers_source_transaction_and_rollback(self):
        source = self.root / "checkout"
        (source / "src").mkdir(parents=True)
        (source / "src" / "example.py").write_text("pass\n")
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with install_location.installed_sources(source, self.destination):
                with self.assertRaises(install_location.InstallBusy):
                    install_location.check_install_idle(self.destination)
                raise RuntimeError("rollback")
        self.assertFalse(self.destination.exists())
        install_location.check_install_idle(self.destination)


if __name__ == "__main__":
    unittest.main()
