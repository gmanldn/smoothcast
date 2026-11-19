"""Installer contract tests: offline, without GTK, Homebrew, sudo or MSYS2."""
from __future__ import annotations

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

    def test_windows_batch_preserves_nonzero_setup_exit_code(self):
        batch = (ROOT / "setup" / "winsetup.bat").read_text(encoding="utf-8")
        self.assertIn(':TRY_PYTHON', batch)
        self.assertIn(':NO_PYTHON', batch)
        # Percent-expansion of ERRORLEVEL inside a parenthesised CMD block can
        # wrongly report success after bootstrap failure. Use straight-line
        # commands plus immediate exit instead.
        self.assertNotIn('if not errorlevel 1 (', batch)
        self.assertEqual(batch.count('exit /b %errorlevel%'), 2)

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
             mock.patch.object(bootstrap, "venv_supported", return_value=True), \
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
             mock.patch.object(bootstrap, "venv_supported", return_value=True), \
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

    def test_python_floor_uses_exit_code_not_optimizable_assert(self):
        self.assertTrue(bootstrap.python_ok(sys.executable))
        source = bootstrap.python_ok.__code__
        self.assertIn("sys.exit", source.co_consts[-1])
        launcher = (ROOT / "smoothcast").read_text(encoding="utf-8")
        self.assertIn("sys.exit(0 if sys.version_info", launcher)
        self.assertNotIn("assert sys.version_info", launcher)

    def test_catt_prerelease_rejected_even_under_optimized_python(self):
        for version, accepted in (
            ("0.11.99", False), ("0.12rc1", False),
            ("0.12.0rc1", False), ("0.13.dev0", False),
            ("0.12", True), ("0.12.0", True),
            ("0.12.post1", True), ("1.0", True),
        ):
            with self.subTest(version=version):
                injection = (
                    "import importlib.metadata as _m; "
                    f"_m.version=lambda name:{version!r}; "
                )
                for optimize in (False, True):
                    argv = [sys.executable] + (["-O"] if optimize else [])
                    result = subprocess.run(
                        argv + ["-c", injection + bootstrap.CATT_CHECK],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode == 0, accepted,
                                     (version, optimize, result.stderr))
        launcher = (ROOT / "smoothcast").read_text(encoding="utf-8")
        self.assertNotIn("assert tuple(v)", launcher)
        self.assertIn("re.fullmatch", launcher)

    def test_ffmpeg_tool_probe_handles_missing_loader_timeout_and_exit(self):
        outcomes = {
            "ffmpeg": subprocess.CompletedProcess(["ffmpeg"], 0),
            "ffprobe": subprocess.TimeoutExpired(["ffprobe"], 4),
            "ffplay": OSError("bad shared library"),
        }
        def run(command, **kwargs):
            result = outcomes[Path(command[0]).name]
            if isinstance(result, Exception):
                raise result
            self.assertEqual(command[1], "-version")
            self.assertEqual(kwargs["timeout"], 4)
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            return result

        with mock.patch.object(bootstrap.shutil, "which",
                               side_effect=lambda name, path=None: "/bin/" + name), \
             mock.patch.object(bootstrap.subprocess, "run", side_effect=run):
            missing = bootstrap.check_tools()
        self.assertEqual(missing, [
            "ffprobe (version probe timed out)",
            "ffplay (failed to start; check loader/runtime)",
        ])
        outcomes["ffprobe"] = subprocess.CompletedProcess(["ffprobe"], 127)
        outcomes["ffplay"] = subprocess.CompletedProcess(["ffplay"], 0)
        with mock.patch.object(bootstrap.shutil, "which",
                               side_effect=lambda name, path=None: "/bin/" + name), \
             mock.patch.object(bootstrap.subprocess, "run", side_effect=run):
            self.assertEqual(bootstrap.check_tools(),
                             ["ffprobe (version probe exited 127)"])
        with mock.patch.object(bootstrap.shutil, "which", return_value=None), \
             mock.patch.object(bootstrap.subprocess, "run") as process:
            self.assertEqual(bootstrap.check_tools(), [
                "ffmpeg (missing)", "ffprobe (missing)", "ffplay (missing)",
            ])
            process.assert_not_called()

    def test_venv_probe_creates_only_disposable_environment(self):
        created = []
        def run(command, **kwargs):
            self.assertIn("--system-site-packages", command)
            target = Path(command[-1])
            created.append(target)
            target.mkdir(parents=True)
            (target / "pyvenv.cfg").write_text("home = /usr/bin", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(bootstrap.subprocess, "run", side_effect=run):
            self.assertTrue(bootstrap.venv_supported(Path(sys.executable)))
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists(), "temporary venv must be cleaned")
        with mock.patch.object(bootstrap.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(bootstrap.venv_supported(Path(sys.executable)))

    def test_debian_missing_python3_venv_is_detected_by_check_and_setup(self):
        patches = [
            mock.patch.object(bootstrap, "manager_for_linux", return_value="apt-get"),
            mock.patch.object(bootstrap, "check_tools", return_value=[]),
            mock.patch.object(bootstrap, "python_ok", return_value=True),
            mock.patch.object(bootstrap, "works", return_value=True),
            mock.patch.object(bootstrap, "venv_supported", return_value=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch.object(bootstrap, "checked_run") as run:
            with self.assertRaisesRegex(bootstrap.SetupError, "python3-venv"):
                bootstrap.install_linux(check=True)
            run.assert_not_called()
        with mock.patch.object(bootstrap, "privileged", side_effect=lambda x: x), \
             mock.patch.object(bootstrap, "checked_run") as run, \
             mock.patch.object(bootstrap, "pick_runtime",
                               return_value=Path(sys.executable)):
            bootstrap.install_linux(check=False)
        run.assert_called_once()
        self.assertIn("python3-venv", run.call_args.args[0])

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
        with tempfile.TemporaryDirectory() as directory:
            original_mkdtemp = tempfile.mkdtemp
            def private_dir(*, prefix):
                return original_mkdtemp(prefix=prefix, dir=directory)
            with mock.patch.object(bootstrap.urllib.request, "urlopen",
                                   side_effect=fake_open), \
                 mock.patch.object(bootstrap.tempfile, "mkdtemp",
                                   side_effect=private_dir):
                path = bootstrap.download_verified_msys2()
                self.assertEqual(path.read_bytes(), binary)
                self.assertEqual(path.parent.parent, Path(directory))
                self.assertTrue(path.parent.name.startswith("smoothcast-msys2-"))
                shutil.rmtree(path.parent)

    def test_missing_catt_recovers_from_project_metadata_not_removed_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "bin" / "python"
            executable.parent.mkdir(parents=True)
            executable.touch()
            catt_checks = 0

            def installed(_python, code, *, env=None):
                nonlocal catt_checks
                if code == bootstrap.GUI_CHECK:
                    return True
                if code == bootstrap.CATT_CHECK:
                    catt_checks += 1
                    return catt_checks > 1
                return False

            with mock.patch.object(bootstrap, "venv_python", return_value=executable), \
                 mock.patch.object(bootstrap, "works", side_effect=installed), \
                 mock.patch.object(bootstrap, "check_tools", return_value=[]), \
                 mock.patch.object(bootstrap, "checked_run") as run:
                result = bootstrap.ensure_venv(Path(sys.executable), dict(), check=False)
            self.assertEqual(result, executable)
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertEqual(command[:4], [str(executable), "-m", "pip", "install"])
            self.assertEqual(command[-2:], ["-e", str(ROOT)])
            self.assertNotIn("requirements.txt", " ".join(command))

    def test_native_launcher_refuses_gui_tests_before_starting_python(self):
        with mock.patch.object(launch, "python_path") as runtime, \
             mock.patch.object(launch.subprocess, "call") as call:
            with mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}):
                self.assertEqual(launch.main(["--self-test"]), 2)
            with mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": "1"}):
                self.assertEqual(launch.main([]), 2)
            runtime.assert_not_called()
            call.assert_not_called()

    def test_virtualenv_check_is_readonly(self):
        with mock.patch.object(bootstrap, "venv_python",
                               return_value=Path("/does/not/exist")):
            with mock.patch.object(bootstrap, "checked_run") as run:
                with self.assertRaises(bootstrap.SetupError):
                    bootstrap.ensure_venv(Path(sys.executable), {}, check=True)
                run.assert_not_called()

    def test_no_installer_references_a_missing_requirements_file(self):
        # `catt` is the only pip dependency and there is deliberately no
        # requirements.txt; `pip install -r` on a missing file aborts setup.
        source = (ROOT / "setup" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("requirements.txt", source)

    def test_venv_installs_catt_without_a_requirements_file(self):
        state = {"catt": False}

        def fake_works(python, code, *, env=None):
            return state["catt"] if "m.version" in code else True

        def fake_run(command, **kwargs):
            if "pip" in command and any("catt" in str(arg) for arg in command):
                state["catt"] = True

        with mock.patch.object(bootstrap, "venv_python",
                               return_value=Path(sys.executable)), \
             mock.patch.object(bootstrap, "works", side_effect=fake_works), \
             mock.patch.object(bootstrap, "check_tools", return_value=[]), \
             mock.patch.object(bootstrap, "checked_run", side_effect=fake_run) as run:
            installed = bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        self.assertEqual(installed, Path(sys.executable))
        command = run.call_args.args[0]
        self.assertIn("catt>=0.12", command)
        self.assertNotIn("requirements.txt", command)

    def test_macos_application_bundle_has_valid_plist_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = shortcuts.install_macos(home=Path(directory))
            self.assertTrue((app / "Contents" / "Info.plist").is_file())
            script = app / "Contents" / "MacOS" / "SmoothCast"
            self.assertTrue(script.is_file())
            self.assertIn(str(ROOT / "setup" / "launch.py"), script.read_text())
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
