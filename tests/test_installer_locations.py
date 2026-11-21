"""Zero-Python installer and safe location regression tests (no network/GUI/sudo)."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import bootstrap
import install_location
import shortcuts


class InstallLocationTests(unittest.TestCase):
    def test_sensible_per_user_defaults(self):
        home = Path("/tmp/example home")
        env = {"LOCALAPPDATA": r"C:\Users\Example\AppData\Local"}
        self.assertEqual(install_location.default_directory("linux", home=home),
                         home / ".local" / "opt" / "SmoothCast")
        self.assertEqual(install_location.default_directory("macos", home=home),
                         home / "Applications" / "SmoothCast")
        self.assertIn("Programs", str(install_location.default_directory(
            "windows", home=home, env=env)))
        self.assertIn("SmoothCast", str(install_location.default_directory(
            "windows", home=home, env=env)))

    def test_destination_prompts_only_for_interactive_install(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            expected = home / "My Media Apps" / "SmoothCast"
            with mock.patch.object(install_location.sys.stdin, "isatty", return_value=True):
                actual = install_location.select_directory(
                    "linux", home=home, input_fn=lambda _prompt: str(expected))
                self.assertEqual(actual, expected.resolve())
                unprompted = install_location.select_directory(
                    "linux", home=home, yes=True,
                    input_fn=lambda _: self.fail("--yes prompted"))
                self.assertEqual(unprompted, (home / ".local/opt/SmoothCast").resolve())
                checked = install_location.select_directory(
                    "linux", home=home, check=True,
                    input_fn=lambda _: self.fail("--check prompted"))
                self.assertEqual(checked, unprompted)

    def test_remember_location_uses_private_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            chosen = home / "My apps" / "SmoothCast"
            install_location.remember_directory("linux", chosen, home=home)
            self.assertEqual(install_location.previous_directory("linux", home=home),
                             None)  # not a valid install yet
            (chosen / "setup").mkdir(parents=True)
            (chosen / "setup" / "bootstrap.py").write_text("# app\n")
            self.assertEqual(install_location.previous_directory("linux", home=home),
                             chosen.resolve())
            self.assertEqual(install_location.select_directory("linux", home=home,
                                                                yes=True),
                             chosen.resolve())

    def test_reject_overwriting_non_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "checkout"
            source.mkdir()
            self.assertRaises(ValueError, install_location.validate_destination,
                              source, source)
            self.assertRaises(ValueError, install_location.validate_destination,
                              source, base)
            destination = base / "my unrelated files"
            destination.mkdir()
            (destination / "notes.txt").write_text("important")
            self.assertRaises(ValueError, install_location.validate_destination,
                              source, destination)
            self.assertEqual((destination / "notes.txt").read_text(), "important")

    def test_copy_to_location_with_spaces_ignores_developer_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source checkout"
            (source / "src").mkdir(parents=True)
            (source / "setup").mkdir()
            (source / ".git").mkdir()
            (source / "src" / "__pycache__").mkdir()
            (source / "src" / "module.py").write_text("x = 1\n")
            (source / "setup" / "bootstrap.py").write_text("# bootstrap\n")
            (source / "pyproject.toml").write_text('[project]\nname = "smoothcast"\n')
            destination = base / "Installed apps" / "SmoothCast"
            with install_location.installed_sources(source, destination):
                self.assertEqual((destination / "src" / "module.py").read_text(), "x = 1\n")
                self.assertFalse((destination / ".git").exists())
                self.assertFalse((destination / "src" / "__pycache__").exists())
            self.assertTrue((destination / "setup" / "bootstrap.py").exists())
            self.assertTrue((source / ".git").exists())

    def test_update_failure_restores_old_code_and_keeps_venv_and_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "checkout"
            target = base / "installed"
            for folder in (source, target):
                (folder / "setup").mkdir(parents=True)
                (folder / "src").mkdir()
                (folder / "pyproject.toml").write_text('[project]\nname = "smoothcast"\n')
                (folder / "setup" / "bootstrap.py").write_text("# old\n")
            (source / "src" / "player.py").write_text("new\n")
            (target / "src" / "player.py").write_text("old\n")
            (target / ".venv").mkdir()
            (target / ".venv" / "important").write_text("preserve")
            (target / "my music.txt").write_text("preserve")
            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                with install_location.installed_sources(source, target):
                    self.assertEqual((target / "src" / "player.py").read_text(), "new\n")
                    raise RuntimeError("simulated failure")
            self.assertEqual((target / "src" / "player.py").read_text(), "old\n")
            self.assertEqual((target / ".venv" / "important").read_text(), "preserve")
            self.assertEqual((target / "my music.txt").read_text(), "preserve")

    def test_failed_fresh_install_removes_only_new_install(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "src"
            source.mkdir()
            (source / "setup").mkdir()
            (source / "setup" / "bootstrap.py").write_text("...")
            destination = Path(directory) / "new app"
            with self.assertRaises(RuntimeError):
                with install_location.installed_sources(source, destination):
                    raise RuntimeError("package installer failed")
            self.assertFalse(destination.exists())
            self.assertTrue(source.exists())

    def test_bootstrap_routes_to_selected_location_without_running_system_install(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "user apps" / "SmoothCast"
            with mock.patch.object(bootstrap.platform, "system", return_value="Linux"), \
                 mock.patch.object(install_location, "select_directory",
                                   return_value=dest), \
                 mock.patch.object(install_location, "validate_destination"), \
                 mock.patch.object(install_location, "installed_sources",
                                   return_value=nullcontext()), \
                 mock.patch.object(install_location, "remember_directory") as remember, \
                 mock.patch.object(bootstrap, "checked_run") as runner:
                result = bootstrap.main(["--target", "linux", "--yes"])
            self.assertEqual(result, 0)
            args = runner.call_args.args[0]
            self.assertEqual(args[0], sys.executable)
            self.assertEqual(args[1], str(dest / "setup" / "bootstrap.py"))
            self.assertIn("--in-place", args)
            self.assertEqual(args[args.index("--target") + 1], "linux")
            remember.assert_called_once()

    def test_readonly_check_never_copies_or_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "nonexistent app"
            with mock.patch.object(bootstrap.platform, "system", return_value="Linux"), \
                 mock.patch.object(install_location, "select_directory",
                                   return_value=dest), \
                 mock.patch.object(install_location, "installed_sources") as copy, \
                 mock.patch.object(bootstrap, "checked_run") as runner:
                self.assertEqual(bootstrap.main(["--target", "linux", "--check"]), 1)
            copy.assert_not_called()
            runner.assert_not_called()


class VirginEntrypointTests(unittest.TestCase):
    def test_shell_scripts_are_bash_syntax_valid(self):
        if os.name == "nt":
            self.skipTest("Bash not normally available on Windows")
        for name in ("linuxsetup.sh", "macsetup.sh"):
            path = ROOT / "setup" / name
            result = subprocess.run(["bash", "-n", str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_does_not_auto_install_when_python_override_is_invalid(self):
        if os.name == "nt":
            self.skipTest("Bash not normally available on Windows")
        for name in ("linuxsetup.sh", "macsetup.sh"):
            path = ROOT / "setup" / name
            env = dict(os.environ, PYTHON="/definitely/no/python")
            result = subprocess.run(["bash", str(path), "--check"],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue("Python" in result.stderr or "PYTHON" in result.stderr)

    def test_windows_fallback_is_signature_and_digest_verified(self):
        script = (ROOT / "setup" / "windows_python.ps1").read_text(encoding="utf-8")
        batch = (ROOT / "setup" / "winsetup.bat").read_text(encoding="utf-8")
        self.assertIn("Get-FileHash", script)
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertIn("Python Software Foundation", script)
        self.assertIn("python-3.14.10-amd64.exe", script)
        self.assertIn("--check", script)
        self.assertIn("windows_python.ps1", batch)
        self.assertIn("bootstrap.py", batch)
        self.assertIn("--target windows", batch)

    def test_all_declared_runtime_packages_are_bootstrapped(self):
        import re
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = [", project)
        section = project.split("dependencies = [", 1)[1].split("]", 1)[0]
        dependencies = re.findall('"([A-Za-z][^"]+)"', section)
        self.assertEqual(set(dependencies), set(bootstrap.PIP_PACKAGES))
        for name in ("psutil", "zeroconf", "smoothcast"):
            self.assertIn(name, bootstrap.PROJECT_DEPENDENCIES_CHECK)

    def test_project_runtime_version_ranges(self):
        import importlib.metadata
        import types
        cases = [
            ("5.8.0", "0.132.0", False),
            ("5.9.0", "0.131.9", False),
            ("5.9.0", "0.132.0", True),
            ("7.8.0", "0.200.1", True),
            ("8.0.0", "0.132.0", False),
            ("6.1.0", "1.0.0", False),
        ]
        modules = {name: types.ModuleType(name) for name in ('psutil', 'zeroconf')}
        for psutil, zeroconf, accepted in cases:
            versions = {'smoothcast': '3.2.0', 'psutil': psutil, 'zeroconf': zeroconf}
            with self.subTest(psutil=psutil, zeroconf=zeroconf), \
                 mock.patch.dict(sys.modules, modules), \
                 mock.patch.object(importlib.metadata, 'version',
                                   side_effect=lambda name: versions[name]):
                with self.assertRaises(SystemExit) as result:
                    exec(compile(bootstrap.PROJECT_DEPENDENCIES_CHECK,
                                 '<runtime-check>', 'exec'), {})
                self.assertEqual(result.exception.code == 0, accepted)
    def test_windows_icon_is_actual_ico_container(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            # A minimal header is sufficient for this pure container test.
            png = (b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR"
                   + struct.pack(">II", 128, 128) + b"\x08\x06\0\0\0")
            source, icon = path / "app.png", path / "app.ico"
            source.write_bytes(png)
            shortcuts.write_windows_icon(source, icon)
            data = icon.read_bytes()
            self.assertEqual(struct.unpack("<HHH", data[:6]), (0, 1, 1))
            self.assertEqual(struct.unpack("<II", data[14:22]), (len(png), 22))
            self.assertEqual(data[22:], png)

    def test_ffmpeg_4_is_detected_before_starting_a_film(self):
        def probe(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, stdout=(b"ffmpeg version 4.4.2\n"
                                  if Path(argv[0]).name == "ffmpeg" else None))
        with mock.patch.object(bootstrap.shutil, "which",
                               side_effect=lambda tool, path=None: "/fake/" + tool), \
             mock.patch.object(bootstrap.subprocess, "run", side_effect=probe):
            failures = bootstrap.check_tools()
        self.assertEqual(failures, ["ffmpeg 4 (requires >=5.0)"])

    def test_macos_pinned_homebrew_constants_match_python_bootstrap(self):
        import re
        script = (ROOT / "setup" / "macsetup.sh").read_text(encoding="utf-8")
        commit = re.search(r'^BREW_COMMIT="([^"]+)"', script, re.M)
        digest = re.search(r'^BREW_SHA256="([^"]+)"', script, re.M)
        self.assertIsNotNone(commit)
        self.assertIsNotNone(digest)
        self.assertEqual(commit.group(1), bootstrap.HOMEBREW_INSTALL_COMMIT)
        self.assertEqual(digest.group(1), bootstrap.HOMEBREW_INSTALL_SHA256)

    def test_terminal_symlink_install_destination_is_rejected(self):
        if os.name == "nt":
            self.skipTest("Creating directory symlinks may require Windows developer mode")
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            source.mkdir()
            target = parent / "data"
            target.mkdir()
            link = parent / "alias"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                install_location.validate_destination(source, link)

    def test_native_shortcut_contains_icon_path(self):
        cmd = shortcuts.windows_shortcut_command(
            executable=Path("C:/Python/python.exe"),
            launcher=Path("C:/Users/O'Neil/SmoothCast/setup/launch.py"),
            destination=Path("C:/Users/O'Neil/Start Menu/SmoothCast.lnk"),
            working_dir=Path("C:/Users/O'Neil/SmoothCast"),
            icon=Path("C:/Users/O'Neil/SmoothCast/Icon.ico"),
        )
        self.assertIn("IconLocation", cmd)
        self.assertIn("O''Neil", cmd)


if __name__ == "__main__":
    unittest.main()
