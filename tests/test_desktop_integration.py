"""Regression checks for the GTK dock/application integration."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "install_desktop.py"
spec = importlib.util.spec_from_file_location("smoothcast_desktop", MODULE)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # macOS temporary-directory paths may traverse /var -> /private/var.
        self.root = Path(self.tmp.name).resolve() / 'project with spaces'
        (self.root / "data").mkdir(parents=True)
        (self.root / "data/cast-control.png").write_bytes(b"PNG-fixture")
        self.data_home = Path(self.tmp.name) / "xdg"
        self.home = Path(self.tmp.name) / "home"
        self.config = self.home / ".config"
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                    "USERPROFILE": str(self.home),
                                                    "XDG_CONFIG_HOME": str(self.config)})
        environment.start()
        self.addCleanup(environment.stop)
        patcher = mock.patch.object(desktop, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_installs_matching_desktop_id_and_icon(self):
        self.assertTrue(desktop.install(data_home=self.data_home, repair_pins=False))
        entry = (self.data_home / "applications/local.cast-control.desktop").read_text()
        # The dock must start *this checkout*, never a stale pip command.
        self.assertIn("Exec=" + desktop.exec_argument(self.root / "smoothcast") + " %F", entry)
        self.assertNotIn('Exec=smoothcast %F', entry)
        self.assertIn("Icon=local.cast-control\n", entry)
        self.assertIn("StartupWMClass=local.cast-control\n", entry)
        self.assertIn("Path=" + str(self.root) + "\n", entry)
        self.assertIn("TryExec=" + str(self.root / "smoothcast") + "\n", entry)
        self.assertIn("StartupNotify=true\n", entry)
        self.assertNotIn("NoDisplay=true", entry)
        self.assertEqual((self.data_home / "icons/hicolor/128x128/apps/local.cast-control.png").read_bytes(), b"PNG-fixture")
        legacy = (self.data_home / "applications/smoothcast.desktop").read_text()
        self.assertIn("NoDisplay=true\n", legacy)
        self.assertIn("Exec=" + desktop.exec_argument(self.root / "smoothcast") + " %F", legacy)
        self.assertFalse(desktop.install(data_home=self.data_home, repair_pins=False))

    def test_check_contract_matches_installed_absolute_exec(self):
        desktop.install(data_home=self.data_home, repair_pins=False)
        entry = (self.data_home / "applications/local.cast-control.desktop").read_bytes()
        self.assertEqual(entry, desktop.desktop_entry(self.root / "smoothcast"))
        self.assertFalse(desktop.install(data_home=self.data_home, repair_pins=False))

    def test_repairs_changed_launcher_and_icon_without_duplication(self):
        desktop.install(data_home=self.data_home, repair_pins=False)
        (self.data_home / "applications/local.cast-control.desktop").write_text("broken", encoding="utf-8")
        (self.data_home / "icons/hicolor/128x128/apps/local.cast-control.png").write_bytes(b"bad")
        self.assertTrue(desktop.install(data_home=self.data_home, repair_pins=False))
        self.assertIn("Name=SmoothCast", (self.data_home / "applications/local.cast-control.desktop").read_text())
        self.assertEqual((self.data_home / "icons/hicolor/128x128/apps/local.cast-control.png").read_bytes(), b"PNG-fixture")

    def test_launcher_recovers_partial_python_environment(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "smoothcast").read_text()
        runtime = (root / "setup/launch.py").read_text()
        self.assertIn("launch.runtime_ready()", script)
        self.assertIn('str(SETUP / "bootstrap.py")', script)
        self.assertIn('"install_desktop.py"', script)
        self.assertIn("bootstrap.GUI_CHECK", runtime)
        self.assertIn("bootstrap.CAST_DEPENDENCIES_CHECK", runtime)
        self.assertIn('for tool in ("ffmpeg", "ffprobe", "ffplay")', runtime)

    def test_runtime_launcher_uses_project_root_for_dock_launch(self):
        script = (Path(__file__).resolve().parents[1] / "setup/launch.py").read_text()
        self.assertIn("os.chdir(ROOT)", script)
        self.assertIn("os.execvpe(command[0], command, env)", script)

    def test_desktop_cli_parses_quiet_and_pin_without_crashing(self):
        # --quiet is invoked on every graphical startup. An invalid argparse
        # action used to raise ValueError before any dock repair could run.
        with mock.patch("sys.argv", ["install_desktop.py", "--quiet"]), \
             mock.patch.object(desktop, "install", return_value=False) as install:
            self.assertEqual(desktop.main(), 0)
        install.assert_called_once_with(repair_pins=True, pin=False, installer_target=False)
        with mock.patch("sys.argv", ["install_desktop.py", "--quiet", "--pin"]), \
             mock.patch.object(desktop, "install", return_value=True) as install:
            self.assertEqual(desktop.main(), 0)
        install.assert_called_once_with(repair_pins=True, pin=True, installer_target=False)

    @unittest.skipIf(os.name == "nt", "Linux freedesktop CLI installer")
    def test_actual_cli_install_twice_then_check_from_spaced_checkout(self):
        # The shipped CLI, not just install(), must be idempotent and agree
        # with --check when launched from a checkout whose path has spaces and
        # no `smoothcast` is available on PATH.
        import subprocess
        import sys
        checkout = self.root  # "project with spaces" fixture from setUp
        (checkout / "scripts").mkdir(exist_ok=True)
        source = Path(__file__).resolve().parents[1] / "scripts" / "install_desktop.py"
        (checkout / "scripts" / "install_desktop.py").write_bytes(source.read_bytes())
        launcher = checkout / "smoothcast"
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        xdg = Path(self.tmp.name) / "cli-xdg"
        env = dict(os.environ, XDG_DATA_HOME=str(xdg), PATH="/usr/bin:/bin")
        cli = [sys.executable, str(checkout / "scripts" / "install_desktop.py")]
        for _ in range(2):
            result = subprocess.run([*cli, "--quiet"], capture_output=True,
                                    text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        check = subprocess.run([*cli, "--check", "--quiet"], capture_output=True,
                               text=True, env=env, timeout=30)
        self.assertEqual(check.returncode, 0, check.stderr)
        expected = f'Exec="{launcher}" %F'
        for name in ("local.cast-control.desktop", "smoothcast.desktop"):
            entry = (xdg / "applications" / name).read_text(encoding="utf-8")
            self.assertIn(expected, entry)

    def _installation(self, root):
        (root / "setup").mkdir(parents=True)
        (root / "setup/bootstrap.py").touch()
        (root / "smoothcast").touch()
        (root / "smoothcast").chmod(0o755)
        (root / "pyproject.toml").write_text('name = "smoothcast"\n')
        (root / "data").mkdir()
        (root / "data/cast-control.png").write_bytes(b"installed-icon")
        return root

    def _remember(self, root):
        pointer = self.config / "smoothcast/install-location"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(root) + "\n")

    def test_checkout_repair_targets_remembered_install_and_both_legacy_ids(self):
        target = self._installation(self.home / "Custom installed SmoothCast")
        self._remember(target)
        self.assertTrue(desktop.install(data_home=self.data_home, repair_pins=False))
        for name in ("local.cast-control.desktop", *desktop.LEGACY_IDS):
            entry = (self.data_home / "applications" / name).read_bytes()
            self.assertEqual(entry, desktop.desktop_entry(target / "smoothcast", legacy=name in desktop.LEGACY_IDS))
        icon = self.data_home / "icons/hicolor/128x128/apps/local.cast-control.png"
        self.assertEqual(icon.read_bytes(), b"installed-icon")
        self.assertFalse(desktop.install(data_home=self.data_home, repair_pins=False))
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data_home)}), \
             mock.patch("sys.argv", ["install_desktop.py", "--check", "--quiet"]):
            self.assertEqual(desktop.main(), 0)
            (self.data_home / "applications/cast-control.desktop").unlink()
            self.assertEqual(desktop.main(), 1)

    def test_default_install_wins_when_no_saved_location(self):
        target = self._installation(self.home / ".local/opt/SmoothCast")
        self.assertEqual(desktop.registration_root(), target)

    def test_installer_explicit_new_target_wins_before_pointer_commit(self):
        old = self._installation(self.home / "Old installation")
        self._remember(old)
        desktop.install(data_home=self.data_home, repair_pins=False, installer_target=True)
        entry = (self.data_home / "applications/local.cast-control.desktop").read_bytes()
        self.assertEqual(entry, desktop.desktop_entry(self.root / "smoothcast"))
        self.assertEqual(desktop.registration_root(), old)

    def test_broken_saved_install_does_not_overwrite_existing_dock(self):
        desktop.install(data_home=self.data_home, repair_pins=False)
        path = self.data_home / "applications/local.cast-control.desktop"
        before = path.read_bytes()
        self._remember(self.home / "missing install")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            desktop.install(data_home=self.data_home, repair_pins=False)
        self.assertEqual(path.read_bytes(), before)

    def test_quotes_desktop_exec_field(self):
        result = desktop.exec_argument(Path('/tmp/a $"%'+chr(96)+'b/smoothcast'))
        self.assertIn(r'\$', result)
        self.assertIn(r'\"', result)
        self.assertIn('%%', result)
        self.assertIn("\\" + chr(96), result)

    def test_gnome_favourites_migration_preserves_other_pins(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/gsettings"):
                with mock.patch.object(desktop.subprocess, "run") as run:
                    run.return_value.stdout = "['firefox.desktop', 'smoothcast.desktop', 'terminal.desktop']\n"
                    self.assertTrue(desktop.repair_gnome_favourites())
                    self.assertEqual(run.call_args_list[-1].args[0][-1],
                                     "['firefox.desktop', 'local.cast-control.desktop', 'terminal.desktop']")

    def test_gnome_pin_appends_without_reordering(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/gsettings"):
                with mock.patch.object(desktop.subprocess, "run") as run:
                    run.return_value.stdout = "['firefox.desktop', 'terminal.desktop']\n"
                    self.assertTrue(desktop.repair_gnome_favourites(pin=True))
                    self.assertEqual(run.call_args_list[-1].args[0][-1],
                                     "['firefox.desktop', 'terminal.desktop', 'local.cast-control.desktop']")

    def test_gnome_pin_is_noop_when_already_pinned(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/gsettings"):
                with mock.patch.object(desktop.subprocess, "run") as run:
                    run.return_value.stdout = "['firefox.desktop', 'local.cast-control.desktop']\n"
                    self.assertFalse(desktop.repair_gnome_favourites(pin=True))
                    self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
