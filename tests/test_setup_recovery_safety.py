"""Setup recovery and native manifest safety, with no GUI or package installs."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import install_location
import native_runtime


class SetupRecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "checkout"
        self.target = self.root / "installed"
        for root, content in ((self.source, "new"), (self.target, "old")):
            (root / "src").mkdir(parents=True)
            (root / "setup").mkdir()
            (root / "setup" / "bootstrap.py").write_text("# bootstrap\n")
            (root / "pyproject.toml").write_text('[project]\nname = "smoothcast"\n')
            (root / "src" / "player.py").write_text(content)

    def test_failed_rollback_retains_old_sources(self):
        rename = Path.rename

        def fail_restore(path, target):
            if path.parent.name.startswith(".smoothcast-install-backup-"):
                raise PermissionError("simulated restore failure")
            return rename(path, target)

        with mock.patch.object(Path, "rename", fail_restore):
            with self.assertRaisesRegex(OSError, "recovery files retained"):
                with install_location.installed_sources(self.source, self.target):
                    raise RuntimeError("failed setup")
        backups = list(self.root.glob(".smoothcast-install-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "src" / "player.py").read_text(), "old")

    def test_normal_rollback_restores_old_sources_and_cleans_backup(self):
        with self.assertRaises(RuntimeError):
            with install_location.installed_sources(self.source, self.target):
                raise RuntimeError("failed setup")
        self.assertEqual((self.target / "src" / "player.py").read_text(), "old")
        self.assertFalse(list(self.root.glob(".smoothcast-install-backup-*")))

    def test_fresh_failure_does_not_erase_unrelated_new_files(self):
        fresh = self.root / "fresh"
        with self.assertRaises(RuntimeError):
            with install_location.installed_sources(self.source, fresh):
                (fresh / "keep.txt").write_text("user data")
                raise RuntimeError("failed setup")
        self.assertEqual((fresh / "keep.txt").read_text(), "user data")
        self.assertFalse((fresh / "src").exists())

    def test_nested_source_link_refused_and_prior_install_restored(self):
        private = self.root / "private.txt"
        private.write_text("not application data")
        try:
            (self.source / "src" / "linked.txt").symlink_to(private)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(Exception, "linked or special"):
            with install_location.installed_sources(self.source, self.target):
                self.fail("linked input was accepted")
        self.assertEqual((self.target / "src" / "player.py").read_text(), "old")
        self.assertFalse((self.target / "src" / "linked.txt").exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_nested_fifo_refused_without_opening_it(self):
        os.mkfifo(self.source / "src" / "pipe")
        with self.assertRaisesRegex(Exception, "linked or special"):
            with install_location.installed_sources(self.source, self.target):
                self.fail("FIFO was accepted")
        self.assertEqual((self.target / "src" / "player.py").read_text(), "old")


class ManifestRecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.venv = self.root / ".venv"
        self.venv.mkdir()
        self.path = native_runtime.manifest_path(self.venv)
        self.python = self.root / "Python With Spaces" / "python"

    def test_valid_manifest_with_spaces_roundtrips(self):
        native_runtime.save(self.venv, target="linux", native_python=self.python, env={})
        self.assertEqual(native_runtime.load(self.venv, target="linux")["native_python"],
                         str(self.python))

    def test_invalid_records_fail_closed(self):
        valid = {"format": 1, "target": "linux", "native_python": str(self.python)}
        for invalid in (dict(valid, format=True), dict(valid, native_python="python"),
                        dict(valid, native_python=str(self.python) + "\x00")):
            with self.subTest(invalid=invalid):
                self.path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(RuntimeError, "Rerun the platform setup script"):
                    native_runtime.load(self.venv, target="linux")

    def test_oversized_record_rejected(self):
        self.path.write_bytes(b" " * (native_runtime.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(RuntimeError, "too large"):
            native_runtime.load(self.venv, target="linux")

    def test_relative_native_path_cannot_overwrite_valid_record(self):
        native_runtime.save(self.venv, target="linux", native_python=self.python, env={})
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            native_runtime.save(self.venv, target="linux", native_python=Path("python"), env={})
        self.assertEqual(self.path.read_bytes(), original)

    def test_linked_manifest_refused_even_if_dangling(self):
        try:
            self.path.symlink_to(self.root / "missing")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(RuntimeError, "ordinary file"):
            native_runtime.load(self.venv, target="linux")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_manifest_refused_without_opening_it(self):
        os.mkfifo(self.path)
        with self.assertRaisesRegex(RuntimeError, "ordinary file"):
            native_runtime.load(self.venv, target="linux")


if __name__ == "__main__":
    unittest.main()
