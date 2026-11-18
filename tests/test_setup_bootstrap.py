"""Installer contract tests: offline, without GTK, Homebrew, sudo or MSYS2."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
sys.path.insert(0, str(ROOT / "src"))
import bootstrap
import launch
import shortcuts
import streamer
import startup_cleanup


class SetupContractTests(unittest.TestCase):
    def test_all_three_entry_points_exist_and_invoke_same_bootstrap(self):
        for path, target in (
            ("linuxsetup.sh", "linux"),
            ("macsetup.sh", "macos"),
            ("winsetup.bat", "windows"),
        ):
            with self.subTest(target=target):
                script = (ROOT / "setup" / path).read_text(encoding="utf-8")
                self.assertIn("bootstrap.py", script)
                self.assertIn("--target " + target, script)
        if os.name != "nt" and shutil.which("bash"):
            for filename in ("linuxsetup.sh", "macsetup.sh", "smoothcast"):
                result = subprocess.run(
                    ["bash", "-n", str(ROOT / ("setup" if filename.endswith(".sh")
                                              else ".") / filename)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_dependency_matrix_explicit_on_all_three_platforms(self):
        self.assertIn("gir1.2-adw-1", bootstrap.LINUX_PACKAGES["apt-get"])
        self.assertIn("libadwaita", bootstrap.LINUX_PACKAGES["dnf"])
        self.assertIn("libadwaita", bootstrap.LINUX_PACKAGES["pacman"])
        self.assertIn("mingw-w64-ucrt-x86_64-libadwaita",
                      bootstrap.WINDOWS_PACKAGES)
        self.assertIn("mingw-w64-ucrt-x86_64-ffmpeg",
                      bootstrap.WINDOWS_PACKAGES)
        self.assertIn("mingw-w64-ucrt-x86_64-python-gobject",
                      bootstrap.WINDOWS_PACKAGES)

    def test_linux_package_manager_selection_and_dry_run(self):
        self.assertEqual(
            bootstrap.manager_for_linux(which=lambda x: x if x == "dnf" else None),
            "dnf",
        )
        with mock.patch.object(bootstrap, "check_tools", return_value=[]), \
             mock.patch.object(bootstrap, "python_ok", return_value=True), \
             mock.patch.object(bootstrap, "works", return_value=True), \
             mock.patch.object(bootstrap, "checked_run") as run:
            interpreter, env = bootstrap.install_linux(check=True)
        self.assertTrue(str(interpreter).endswith("python3"))
        self.assertIsInstance(env, dict)
        run.assert_not_called()

    def test_linux_missing_components_invoke_system_package_manager(self):
        with mock.patch.object(bootstrap, "check_tools", return_value=["ffmpeg"]), \
             mock.patch.object(bootstrap, "python_ok", return_value=True), \
             mock.patch.object(bootstrap, "works", return_value=True), \
             mock.patch.object(bootstrap, "manager_for_linux", return_value="apt-get"), \
             mock.patch.object(bootstrap, "privileged", side_effect=lambda x: x), \
             mock.patch.object(bootstrap, "checked_run") as run:
            bootstrap.install_linux(check=False)
        self.assertEqual(run.call_count, 1)
        self.assertIn("ffmpeg", run.call_args.args[0])
        self.assertIn("gir1.2-adw-1", run.call_args.args[0])

    def test_linux_readonly_check_refuses_incomplete_install(self):
        with mock.patch.object(bootstrap, "check_tools", return_value=["ffmpeg"]), \
             mock.patch.object(bootstrap, "python_ok", return_value=False), \
             mock.patch.object(bootstrap, "checked_run") as run:
            with self.assertRaises(bootstrap.SetupError):
                bootstrap.install_linux(check=True)
        run.assert_not_called()

    def test_windows_runtime_paths_expose_native_gtk_dlls(self):
        env = bootstrap.windows_env(Path("C:/msys64"))
        self.assertIn("ucrt64", env["PATH"])
        self.assertIn("girepository-1.0", env["GI_TYPELIB_PATH"])
        self.assertIn("ucrt64", env["PYGI_DLL_PATH"])
        self.assertEqual(env["MSYSTEM"], "UCRT64")

    def test_windows_check_never_downloads_or_installs(self):
        with mock.patch.object(bootstrap, "python_ok", return_value=True), \
             mock.patch.object(bootstrap, "works", return_value=True), \
             mock.patch.object(bootstrap, "check_tools", return_value=[]), \
             mock.patch.object(bootstrap, "download_verified_msys2") as download, \
             mock.patch.object(bootstrap, "checked_run") as run:
            python, env = bootstrap.install_windows(check=True)
        self.assertEqual(python.name, "python.exe")
        self.assertEqual(env["MSYSTEM"], "UCRT64")
        download.assert_not_called()
        run.assert_not_called()

    def test_official_msys2_download_validates_sha256(self):
        binary = b"official fixture"
        sha = hashlib.sha256(binary).hexdigest()
        fake_assets = [
            {"name": "msys2-x86_64-20261118.exe",
             "browser_download_url": "https://github.com/msys2/installer.exe"},
            {"name": "msys2-x86_64-20261118.exe.sha256",
             "browser_download_url": "https://github.com/msys2/checksum"},
        ]
        api = json.dumps({"assets": fake_assets}).encode("utf-8")
        def fake_open(request, timeout=None):
            url = getattr(request, "full_url", request)
            data = (api if "api.github.com" in url else
                    (sha + "  msys2-x86_64-20261118.exe").encode()
                    if "checksum" in url else binary)
            return io.BytesIO(data)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(bootstrap.urllib.request, "urlopen",
                               side_effect=fake_open), \
             mock.patch.object(bootstrap.tempfile, "gettempdir",
                               return_value=directory):
            path = bootstrap.download_verified_msys2()
            self.assertEqual(path.read_bytes(), binary)

    def test_virtualenv_check_is_readonly(self):
        with mock.patch.object(bootstrap, "venv_python",
                               return_value=Path("/does/not/exist")):
            with mock.patch.object(bootstrap, "checked_run") as run:
                with self.assertRaises(bootstrap.SetupError):
                    bootstrap.ensure_venv(Path(sys.executable), {}, check=True)
                run.assert_not_called()

    def test_macos_application_bundle_has_valid_plist_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = shortcuts.install_macos(home=Path(directory))
            self.assertTrue((app / "Contents" / "Info.plist").is_file())
            script = app / "Contents" / "MacOS" / "SmoothCast"
            self.assertTrue(script.is_file())
            self.assertIn("setup/launch.py", script.read_text())
            # Windows does not expose POSIX executable mode bits for files.
            if os.name != "nt":
                self.assertTrue(script.stat().st_mode & 0o111)

    def test_windows_shortcut_paths_are_quoted_not_evaluated(self):
        source = shortcuts.windows_shortcut_command(
            executable=Path("C:/Program Files/Python/python.exe"),
            launcher=Path("C:/Users/O'Neil/SmoothCast/setup/launch.py"),
            destination=Path("C:/Users/O'Neil/AppData/SmoothCast.lnk"),
            working_dir=Path("C:/Users/O'Neil/SmoothCast"),
        )
        self.assertIn("O''Neil", source)
        self.assertIn("WScript.Shell", source)
        self.assertIn("CreateShortcut", source)

    def test_macos_and_windows_never_try_linux_pid_cleanup(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(platform=system), \
                 mock.patch.object(startup_cleanup.platform, "system",
                                   return_value=system), \
                 mock.patch.object(startup_cleanup, "discover") as discover:
                report = startup_cleanup.cleanup_before_window(
                    keep_streaming=False,
                )
                self.assertFalse(report.stopped)
                discover.assert_not_called()

    def test_vaapi_is_not_attempted_on_macos_or_windows(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), \
                 mock.patch.object(streamer.platform, "system",
                                   return_value=system):
                self.assertTrue(streamer.Session().used_software_fallback)
        with mock.patch.object(streamer.platform, "system",
                               return_value="Linux"):
            self.assertFalse(streamer.Session().used_software_fallback)

    def test_original_launcher_delegates_to_shared_bootstrap(self):
        script = (ROOT / "smoothcast").read_text()
        self.assertIn("setup/bootstrap.py", script)
        self.assertIn("setup/launch.py", script)
        self.assertIn('exec "$PYTHON" "$DIR/src/version.py"', script)


if __name__ == "__main__":
    unittest.main()
