"""Installer contract tests: offline, without GTK, Homebrew, sudo or MSYS2."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import plistlib
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
            for filename in ("linuxsetup.sh", "macsetup.sh"):
                result = subprocess.run(
                    ["bash", "-n", str(ROOT / "setup" / filename)],
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

    def test_windows_first_run_bootstrap_is_not_duplicated(self):
        source = (ROOT / "setup" / "windows_python.ps1").read_text(encoding="utf-8")
        self.assertEqual(source.count("function Install-Python {"), 1)
        self.assertEqual(source.count("function Find-Python {"), 1)
        self.assertNotIn("\n) {\n", source)
        self.assertIn("& $python $entry @Forward", source)
        batch = (ROOT / "SmoothCast.bat").read_text(encoding="utf-8")
        self.assertIn("-Launch %*", batch)
        self.assertIn('set "SC_EXIT=%errorlevel%"', batch)
        self.assertIn("exit /b %SC_EXIT%", batch)
        self.assertIn("pause", batch)
        self.assertIn("--silent --disable-interactivity", source)
        self.assertIn("InstallLauncherAllUsers=0", source)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser required")
    def test_windows_bootstrap_parses_without_running_installation(self):
        # Parsing is read-only: never execute the installer or launch a GUI.
        script = (
            "$tokens = $null; $errors = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            "$env:SC_PS_FILE, [ref]$tokens, [ref]$errors); "
            "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "SC_PS_FILE": str(ROOT / "setup" / "windows_python.ps1")},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_readiness_uses_native_env_and_checks_project_dependencies(self):
        env = {"PATH": "selected-native-tools", "MSYSTEM": "UCRT64"}
        with mock.patch.object(launch, "runtime_python", return_value=Path("python.exe")), \
             mock.patch.object(launch, "runtime_environment", return_value=env), \
             mock.patch.object(launch.subprocess, "run") as run, \
             mock.patch.object(launch.shutil, "which", return_value="tool") as which:
            run.return_value.returncode = 0
            self.assertTrue(launch.runtime_ready())
            self.assertEqual([c.args[0][-1] for c in run.call_args_list],
                             [launch.RUNTIME_CHECK, bootstrap.PROJECT_DEPENDENCIES_CHECK])
            self.assertTrue(all(c.kwargs["env"] == env for c in run.call_args_list))
            self.assertTrue(all(c.kwargs["path"] == env["PATH"] for c in which.call_args_list))
            run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=1)]
            self.assertFalse(launch.runtime_ready())

    def test_runtime_readiness_never_uses_wrong_native_environment(self):
        with mock.patch.object(launch, "runtime_python", return_value=Path("python.exe")), \
             mock.patch.object(launch, "runtime_environment", side_effect=RuntimeError("moved")), \
             mock.patch.object(launch.subprocess, "run") as run:
            self.assertFalse(launch.runtime_ready())
            run.assert_not_called()

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

    def test_optional_link_tools_use_native_packages_and_recheck(self):
        env = {"PATH": "/trusted/bin"}
        for manager, prefix in (
                ("apt-get", ["apt-get", "install", "-y"]),
                ("dnf", ["dnf", "install", "-y"]),
                ("pacman", ["pacman", "-S", "--needed", "--noconfirm"])):
            with self.subTest(manager=manager), \
                 mock.patch.object(bootstrap, "manager_for_linux", return_value=manager), \
                 mock.patch.object(bootstrap, "privileged", side_effect=lambda x: x), \
                 mock.patch.object(bootstrap.shutil, "which",
                                   side_effect=[None, None, "/trusted/yt-dlp", "/trusted/aria2c"]), \
                 mock.patch.object(bootstrap.subprocess, "run",
                                   return_value=mock.Mock(returncode=0)) as probe, \
                 mock.patch.object(bootstrap, "checked_run") as install:
                bootstrap.install_link_tools("linux", env)
                install.assert_called_once_with([*prefix, "yt-dlp", "aria2"], env=env)
                self.assertEqual(probe.call_count, 2)
                self.assertTrue(all(call.kwargs["timeout"] == 5 for call in probe.call_args_list))

    def test_optional_link_tools_macos_and_windows_use_native_repository(self):
        env = {"PATH": "/trusted/bin"}
        for target in ("macos", "windows"):
            with self.subTest(target=target), \
                 mock.patch.object(bootstrap.shutil, "which",
                                   side_effect=[None, None, "/trusted/yt-dlp", "/trusted/aria2c"]), \
                 mock.patch.object(bootstrap.subprocess, "run",
                                   return_value=mock.Mock(returncode=0)), \
                 mock.patch.object(bootstrap, "checked_run") as install, \
                 mock.patch.object(bootstrap, "find_brew", return_value="/trusted/brew"), \
                 mock.patch.object(bootstrap, "msys2_root",
                                   return_value=bootstrap.Path("/trusted/msys64")), \
                 mock.patch.object(bootstrap.Path, "is_file", return_value=True):
                bootstrap.install_link_tools(target, env)
                command = install.call_args.args[0]
                if target == "macos":
                    self.assertEqual(command, ["/trusted/brew", "install", "yt-dlp", "aria2"])
                else:
                    self.assertIn("mingw-w64-ucrt-x86_64-yt-dlp", command[-1])
                    self.assertIn("mingw-w64-ucrt-x86_64-aria2", command[-1])
                self.assertEqual(install.call_args.kwargs["env"], env)

    def test_optional_link_tools_readonly_never_installs_or_hides_probe_failure(self):
        with mock.patch.object(bootstrap.shutil, "which", return_value="/trusted/engine"), \
             mock.patch.object(bootstrap.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("engine", 5)), \
             mock.patch.object(bootstrap, "checked_run") as install:
            with self.assertRaisesRegex(bootstrap.SetupError, "version probe failed"):
                bootstrap.install_link_tools("linux", {"PATH": "/trusted"}, check=True)
            install.assert_not_called()

    def test_optional_link_tools_existing_executables_do_not_install(self):
        with mock.patch.object(bootstrap.shutil, "which", return_value="/trusted/engine"), \
             mock.patch.object(bootstrap.subprocess, "run", return_value=mock.Mock(returncode=0)), \
             mock.patch.object(bootstrap, "checked_run") as install:
            bootstrap.install_link_tools("linux", {"PATH": "/trusted"}, check=False)
            install.assert_not_called()

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
        launcher = (ROOT / "sc.py").read_text(encoding="utf-8")
        self.assertIn("sys.version_info < (3, 10)", launcher)
        self.assertNotIn("assert sys.version_info", launcher)

    def test_cast_dependency_bounds_rejected_under_optimized_python(self):
        cases = (
            ("0.11.99", "13.1.0", False),
            ("0.12rc1", "13.1.0", False),
            ("0.12.0rc1", "13.1.0", False),
            ("0.13.dev0", "13.1.0", False),
            ("0.12", "13.1.0", True), ("0.12.0", "13.1.0", True),
            ("0.12.post1", "13.1.0", True), ("1.0", "13.1.0", False),
            ("0.13.9", "13.1.0", True), ("0.14.0", "13.1.0", False),
            ("0.12", "13.0.8", False), ("0.12", "15.0.0", False),
            ("0.12", "13.1.0rc1", False), ("0.12", "14.1.0", True),
        )
        # One fresh interpreter per optimization mode exercises the shipped check
        # for every version, instead of one interpreter per version (16 spawns).
        script = (
            "import importlib.metadata as m, json\n"
            f"cases = {[(catt, pycast) for catt, pycast, _accepted in cases]!r}\n"
            f"check = {bootstrap.CAST_DEPENDENCIES_CHECK!r}\n"
            "codes = []\n"
            "for catt_version, pycast_version in cases:\n"
            "    m.version = lambda name, c=catt_version, p=pycast_version: c if name == 'catt' else p\n"
            "    try:\n"
            "        exec(compile(check, '<cast-check>', 'exec'), {'__name__': '__main__'})\n"
            "    except SystemExit as exc:\n"
            "        codes.append(exc.code)\n"
            "    else:\n"
            "        codes.append(None)\n"
            "print(json.dumps(codes))\n"
        )
        for optimize in (False, True):
            argv = [sys.executable] + (["-O"] if optimize else [])
            result = subprocess.run(
                argv + ["-c", script], capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            codes = json.loads(result.stdout)
            self.assertEqual(len(codes), len(cases))
            for (catt_version, pycast_version, accepted), code in zip(cases, codes):
                with self.subTest(catt=catt_version, pychromecast=pycast_version,
                                  optimize=optimize):
                    self.assertEqual(code == 0, accepted,
                                     (catt_version, pycast_version, optimize, result.stderr))
        self.assertNotIn("assert tuple(v)", launch.RUNTIME_CHECK)
        self.assertIn("re.fullmatch", launch.RUNTIME_CHECK)

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

    def test_windows_native_packages_avoid_cpython_binary_wheels(self):
        for name in ("python-psutil", "python-zeroconf", "gstreamer",
                     "gst-plugins-base", "gst-plugins-good", "gst-libav"):
            self.assertIn("mingw-w64-ucrt-x86_64-" + name, bootstrap.WINDOWS_PACKAGES)

    def test_windows_runtime_paths_expose_native_gtk_dlls(self):
        env = bootstrap.windows_env(Path("C:/msys64"))
        self.assertIn("ucrt64", env["PATH"])
        self.assertIn("girepository-1.0", env["GI_TYPELIB_PATH"])
        self.assertIn("ucrt64", env["PYGI_DLL_PATH"])
        self.assertEqual(env["MSYSTEM"], "UCRT64")

    def test_windows_check_rejects_missing_native_packages_without_installing(self):
        with (mock.patch.object(bootstrap, "python_ok", return_value=True),
              mock.patch.object(bootstrap, "works", return_value=True),
              mock.patch.object(bootstrap, "check_tools", return_value=[]),
              mock.patch.object(bootstrap, "windows_packages_ready", return_value=False),
              mock.patch.object(bootstrap.native_runtime, "load", return_value=None),
              mock.patch.object(bootstrap, "checked_run") as run,
              mock.patch.object(bootstrap, "download_verified_msys2") as download):
            with self.assertRaisesRegex(bootstrap.SetupError, "native packages=True"):
                bootstrap.install_windows(check=True)
        run.assert_not_called()
        download.assert_not_called()

    def test_windows_package_probe_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shell = root / "usr" / "bin" / "bash.exe"
            shell.parent.mkdir(parents=True)
            shell.touch()
            with mock.patch.object(bootstrap.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertTrue(bootstrap.windows_packages_ready(root, {}))
                self.assertEqual(run.call_args.args[0][1:4],
                                 ["--noprofile", "--norc", "-c"])
                self.assertTrue(run.call_args.args[0][-1].startswith("pacman -Q "))
                run.return_value.returncode = 1
                self.assertFalse(bootstrap.windows_packages_ready(root, {}))
                run.side_effect = subprocess.TimeoutExpired("pacman", 20)
                self.assertFalse(bootstrap.windows_packages_ready(root, {}))

    def test_windows_check_never_downloads_or_installs(self):
        with mock.patch.object(bootstrap, "python_ok", return_value=True), \
             mock.patch.object(bootstrap, "works", return_value=True), \
             mock.patch.object(bootstrap, "check_tools", return_value=[]), \
             mock.patch.object(bootstrap, "windows_packages_ready", return_value=True), \
             mock.patch.object(bootstrap.native_runtime, "load", return_value=None), \
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

    def test_missing_cast_dependencies_recover_from_project_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "bin" / "python"
            executable.parent.mkdir(parents=True)
            executable.touch()
            dependencies_installed = False

            def installed(_python, code, *, env=None):
                nonlocal dependencies_installed
                if code == bootstrap.GUI_CHECK:
                    return True
                if code in {
                    bootstrap.CAST_DEPENDENCIES_CHECK,
                    bootstrap.PROJECT_DEPENDENCIES_CHECK,
                }:
                    return dependencies_installed
                return False

            def pip_install(_command, **_kwargs):
                nonlocal dependencies_installed
                dependencies_installed = True

            with mock.patch.object(bootstrap, "venv_python", return_value=executable), \
                 mock.patch.object(bootstrap, "works", side_effect=installed), \
                 mock.patch.object(bootstrap, "check_tools", return_value=[]), \
                 mock.patch.object(bootstrap, "checked_run", side_effect=pip_install) as run:
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
        # `catt` and PyChromecast are the pip dependencies; there is deliberately no
        # requirements.txt; `pip install -r` on a missing file aborts setup.
        source = (ROOT / "setup" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("requirements.txt", source)

    def test_venv_installs_cast_dependencies_without_a_requirements_file(self):
        state = {"dependencies": False}

        def fake_works(python, code, *, env=None):
            return state["dependencies"] if "m.version" in code else True

        def fake_run(command, **kwargs):
            if "pip" in command and any("PyChromecast" in str(arg) for arg in command):
                state["dependencies"] = True

        with mock.patch.object(bootstrap, "venv_python",
                               return_value=Path(sys.executable)), \
             mock.patch.object(bootstrap, "works", side_effect=fake_works), \
             mock.patch.object(bootstrap, "check_tools", return_value=[]), \
             mock.patch.object(bootstrap, "checked_run", side_effect=fake_run) as run:
            installed = bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        self.assertEqual(installed, Path(sys.executable))
        command = run.call_args.args[0]
        self.assertIn("catt>=0.12,<0.14", command)
        self.assertIn("PyChromecast>=13.1.0,<15", command)
        self.assertNotIn("requirements.txt", command)

    def test_macos_application_bundle_has_valid_plist_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            prior_contents = (Path(directory) / "Applications" / "SmoothCast.app" /
                              "Contents")
            (prior_contents / "MacOS").mkdir(parents=True)
            (prior_contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "local.smoothcast.player",
            }))
            (prior_contents / "MacOS" / "old-launcher").write_text("old")

            def fake_macos_tool(command, **_kwargs):
                if command[0] == "sips":
                    Path(command[-1]).write_bytes(b"png")
                elif command[0] == "iconutil":
                    Path(command[command.index("-o") + 1]).write_bytes(b"icns")

            with mock.patch.object(shortcuts, "sys",
                                   mock.Mock(platform="darwin", executable=sys.executable)), \
                 mock.patch.object(shortcuts.subprocess, "run", side_effect=fake_macos_tool):
                app = shortcuts.install_macos(home=Path(directory))
            self.assertTrue((app / "Contents" / "Info.plist").is_file())
            with (app / "Contents" / "Info.plist").open("rb") as stream:
                metadata = plistlib.load(stream)
            self.assertEqual(metadata["CFBundleIdentifier"], "local.smoothcast.player")
            self.assertEqual(metadata["CFBundlePackageType"], "APPL")
            self.assertEqual(metadata["CFBundleIconFile"], "SmoothCast.icns")
            self.assertTrue((app / "Contents" / "Resources" / "SmoothCast.icns").is_file())
            self.assertFalse((app / "Contents" / "MacOS" / "old-launcher").exists())
            self.assertEqual(list(app.parent.glob(".smoothcast-app-backup-*")), [])
            script = app / "Contents" / "MacOS" / "SmoothCast"
            self.assertTrue(script.is_file())
            self.assertIn(str(ROOT / "sc.py"), script.read_text())
            # Windows does not expose POSIX executable mode bits for files.
            if os.name != "nt":
                self.assertTrue(script.stat().st_mode & 0o111)

    def test_macos_icon_failure_preserves_previous_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Applications" / "SmoothCast.app"
            contents = app / "Contents"
            (contents / "MacOS").mkdir(parents=True)
            (contents / "MacOS" / "SmoothCast").write_text("old launcher")
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "local.smoothcast.player",
            }))

            def fail_iconutil(command, **_kwargs):
                if command[0] == "sips":
                    Path(command[-1]).write_bytes(b"png")
                elif command[0] == "iconutil":
                    raise subprocess.CalledProcessError(1, command)

            with mock.patch.object(shortcuts, "sys",
                                   mock.Mock(platform="darwin", executable=sys.executable)), \
                 mock.patch.object(shortcuts.subprocess, "run", side_effect=fail_iconutil):
                with self.assertRaises(subprocess.CalledProcessError):
                    shortcuts.install_macos(home=Path(directory))

            self.assertEqual((contents / "MacOS" / "SmoothCast").read_text(), "old launcher")
            with (contents / "Info.plist").open("rb") as stream:
                self.assertEqual(plistlib.load(stream)["CFBundleIdentifier"],
                                 "local.smoothcast.player")
            self.assertEqual(list(app.parent.glob(".smoothcast-app-stage-*")), [])

    def test_macos_registration_refuses_to_replace_another_application(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Applications" / "SmoothCast.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.example.other-app",
            }))
            with self.assertRaisesRegex(ValueError, "another application"):
                shortcuts.install_macos(home=Path(directory))
            with (contents / "Info.plist").open("rb") as stream:
                self.assertEqual(plistlib.load(stream)["CFBundleIdentifier"],
                                 "com.example.other-app")

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

    def test_windows_installed_shortcut_uses_bootstrap_and_verifies_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "App with spaces"
            root.mkdir()
            (root / "SmoothCast.bat").touch()
            (root / "sc.py").touch()
            roaming = Path(directory) / "Roaming"
            with (mock.patch.object(shortcuts, "ROOT", root),
                  mock.patch.dict(os.environ, {"LOCALAPPDATA": directory}),
                  mock.patch.object(shortcuts, "write_windows_icon"),
                  mock.patch.object(shortcuts.subprocess, "run") as run):
                result = shortcuts.install_windows(appdata=roaming)
            script = run.call_args.args[0][-1]
            self.assertIn(str(root / "SmoothCast.bat"), script)
            self.assertNotIn("python.exe", script)
            self.assertIn("Test-Path -LiteralPath", script)
            self.assertIn("$saved.TargetPath", script)
            self.assertIn("$saved.WorkingDirectory", script)
            self.assertEqual(result.name, "SmoothCast.lnk")
            self.assertTrue(run.call_args.kwargs["check"])

    def test_macos_and_windows_never_try_linux_pid_cleanup(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(platform=system), \
                 mock.patch.object(startup_cleanup.platform, "system",
                                   return_value=system), \
                 mock.patch.object(startup_cleanup.process_identity, "psutil",
                                   None), \
                 mock.patch.object(startup_cleanup, "discover") as discover:
                # Without psutil the cleanup fails closed off Linux, whether or
                # not the host running the tests happens to have it installed.
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

    def test_canonical_launcher_delegates_to_shared_bootstrap(self):
        script = (ROOT / "sc.py").read_text()
        self.assertTrue(script.startswith("#!/usr/bin/env python3\n"))
        self.assertIn('str(SETUP / "bootstrap.py")', script)
        self.assertIn("launch.runtime_ready()", script)
        self.assertIn("launch.main(args)", script)
        self.assertIn('"install_desktop.py"', script)
        wrapper = (ROOT / "smoothcast").read_text()
        self.assertIn("from sc import main", wrapper)
        self.assertNotIn("def _bootstrap", wrapper)

    def test_canonical_launcher_keeps_headless_queries_out_of_bootstrap(self):
        loader = importlib.machinery.SourceFileLoader(
            "smoothcast_launcher", str(ROOT / "sc.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        launcher = importlib.util.module_from_spec(spec)
        loader.exec_module(launcher)
        old = os.environ.pop("SMOOTHCAST_TEST_CONTEXT", None)
        try:
            for argv in (["--version"], ["-V"], ["--diagnostics"],
                         ["--diagnostics", "/tmp/report"], ["--self-test", "x"]):
                with self.subTest(argv=argv):
                    self.assertTrue(launcher._headless(argv))
            for argv in ([], ["film.mkv"], ["--version", "extra"],
                         ["--network-check"]):
                with self.subTest(argv=argv):
                    self.assertFalse(launcher._headless(argv))
            os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"
            self.assertTrue(launcher._headless([]))
        finally:
            if old is None:
                os.environ.pop("SMOOTHCAST_TEST_CONTEXT", None)
            else:
                os.environ["SMOOTHCAST_TEST_CONTEXT"] = old


if __name__ == "__main__":
    unittest.main()
