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
        self.root = Path(self.tmp.name) / 'project with spaces'
        (self.root / "data").mkdir(parents=True)
        (self.root / "data/cast-control.png").write_bytes(b"PNG-fixture")
        self.data_home = Path(self.tmp.name) / "xdg"
        patcher = mock.patch.object(desktop, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_installs_matching_desktop_id_and_icon(self):
        self.assertTrue(desktop.install(data_home=self.data_home, repair_pins=False))
        entry = (self.data_home / "applications/local.cast-control.desktop").read_text()
        # The dock must start *this checkout*, never a stale pip command.
        self.assertIn('Exec="' + str(self.root / "smoothcast") + '" %F', entry)
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
        self.assertIn('Exec="' + str(self.root / "smoothcast") + '" %F', legacy)
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
        script = (Path(__file__).resolve().parents[1] / "smoothcast").read_text()
        self.assertIn('RUNTIME="$DIR/.venv/bin/python"', script)
        self.assertIn('m.version("catt")', script)
        self.assertIn('match=re.fullmatch(', script)
        self.assertIn('sys.exit(0 if match', script)
        self.assertNotIn('assert tuple(v)', script)
        self.assertIn('for tool in ffmpeg ffprobe ffplay; do', script)
        self.assertIn('"$DIR/setup/bootstrap.py" --target "$TARGET"', script)

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
        install.assert_called_once_with(repair_pins=True, pin=False)
        with mock.patch("sys.argv", ["install_desktop.py", "--quiet", "--pin"]), \
             mock.patch.object(desktop, "install", return_value=True) as install:
            self.assertEqual(desktop.main(), 0)
        install.assert_called_once_with(repair_pins=True, pin=True)

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