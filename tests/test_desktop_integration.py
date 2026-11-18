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
        self.assertIn('re.findall(r"\\d+",m.version("catt"))', script)
        self.assertIn('for tool in ffmpeg ffprobe ffplay; do', script)
        self.assertIn('"$DIR/setup/bootstrap.py" --target "$TARGET"', script)

    def test_runtime_launcher_uses_project_root_for_dock_launch(self):
        script = (Path(__file__).resolve().parents[1] / "setup/launch.py").read_text()
        self.assertIn("os.chdir(ROOT)", script)
        self.assertIn("os.execvpe(command[0], command, env)", script)

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