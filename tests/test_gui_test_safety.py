"""Portable safeguards: pytest must never show or focus the real GTK window."""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import gui_test_safety

spec = importlib.util.spec_from_file_location(
    "smoothcast_gui_test_runner", ROOT / "scripts" / "test_gui_isolated.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GuiTestSafetyTests(unittest.TestCase):
    def test_pytest_clears_inherited_desktop_display_channels(self):
        # Guard must be applied before test collection, not after tests have
        # had a chance to create GTK objects or spawn GUI subprocesses.
        source = (ROOT / "tests" / "conftest.py").read_text("utf-8")
        ast.parse(source)
        self.assertIn('os.environ["SMOOTHCAST_TEST_CONTEXT"] = "1"', source)
        self.assertIn('os.environ["GDK_BACKEND"] = "x11"', source)
        for name in (
            "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
            "XAUTHORITY", "SMOOTHCAST_GUI_TEST_ISOLATED",
        ):
            self.assertIn(f'"{name}"', source)
        self.assertIn("os.environ.pop(name, None)", source)

    def test_live_desktop_refused_even_when_selftest_argument_explicit(self):
        for env in (
            {},
            {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"},
            {"DISPLAY": ":0", "SMOOTHCAST_GUI_TEST_ISOLATED": "1"},
            {"DISPLAY": ":99", "SMOOTHCAST_GUI_TEST_ISOLATED": "1"},
        ):
            with self.subTest(env=env):
                self.assertFalse(gui_test_safety.is_isolated_gui_test(env))

    def test_isolated_display_requires_private_xdg_and_no_session_bus(self):
        with tempfile.TemporaryDirectory() as folder:
            authority = Path(folder) / "xauthority"
            authority.touch()
            env = {
                "SMOOTHCAST_GUI_TEST_ISOLATED": "1",
                "DISPLAY": ":123",
                "GDK_BACKEND": "x11",
                "XAUTHORITY": str(authority),
                "XDG_CONFIG_HOME": str(Path(folder) / "config"),
                "XDG_DATA_HOME": str(Path(folder) / "data"),
                "XDG_CACHE_HOME": str(Path(folder) / "cache"),
                "XDG_RUNTIME_DIR": str(Path(folder) / "runtime"),
            }
            self.assertTrue(gui_test_safety.is_isolated_gui_test(env))
            for name, value in (
                ("WAYLAND_DISPLAY", "wayland-0"),
                ("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus"),
                ("GDK_BACKEND", "wayland"),
                ("SMOOTHCAST_GUI_TEST_ISOLATED", "0"),
                ("XAUTHORITY", "/nonexistent/smoothcast-xauthority"),
                ("XDG_CONFIG_HOME", ""),
            ):
                with self.subTest(name=name):
                    broken = dict(env, **{name: value})
                    self.assertFalse(gui_test_safety.is_isolated_gui_test(broken))

    def test_console_selftest_fails_before_importing_gtk(self):
        env = dict(os.environ)
        env.update(DISPLAY=":0", WAYLAND_DISPLAY="wayland-0",
                   SMOOTHCAST_GUI_TEST_ISOLATED="0",
                   SMOOTHCAST_TEST_CONTEXT="0",
                   PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run(
            [sys.executable, "-m", "cli", "--self-test"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing SmoothCast GUI self-test", result.stderr)
        self.assertNotIn("gi.repository", result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "Bash unavailable")
    def test_normal_shell_launcher_rejects_gui_test_before_bootstrap(self):
        result = subprocess.run(
            ["bash", str(ROOT / "smoothcast"), "--self-test"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("test_gui_isolated.py", result.stderr)
        self.assertNotIn("Installing", result.stdout)

    def test_one_shot_runner_never_inherits_user_display_or_bus(self):
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.dict(runner.os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}), \
             mock.patch.object(runner.sys, "platform", "linux"), \
             mock.patch.object(runner.shutil, "which",
                               side_effect=lambda name: f"/usr/bin/{name}"), \
             mock.patch.object(runner.subprocess, "Popen",
                               return_value=process) as spawn:
            self.assertEqual(runner.main(), 0)
            spawn.assert_called_once()
            command = spawn.call_args.args[0]
            env = spawn.call_args.kwargs["env"]
            self.assertEqual(command[0], "/usr/bin/xvfb-run")
            self.assertIn("-a", command)
            self.assertEqual(command[-1], "--self-test")
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            process.wait.assert_called_once_with(timeout=runner.MAX_SECONDS)
            for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                        "XAUTHORITY", "XDG_CURRENT_DESKTOP", "SMOOTHCAST_TEST_CONTEXT"):
                self.assertNotIn(key, env)
            self.assertEqual(env["GDK_BACKEND"], "x11")
            self.assertEqual(env["SMOOTHCAST_GUI_TEST_ISOLATED"], "1")
            self.assertEqual(env["GSETTINGS_BACKEND"], "memory")
            for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                         "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
                self.assertTrue(env[name].endswith(("home", "config", "data",
                                                    "cache", "runtime")))

    def test_runner_timeout_terminates_whole_process_group(self):
        process = mock.Mock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired("xvfb-run", 20), 0]
        with mock.patch.dict(runner.os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}), \
             mock.patch.object(runner.sys, "platform", "linux"), \
             mock.patch.object(runner.shutil, "which",
                               side_effect=lambda name: f"/usr/bin/{name}"), \
             mock.patch.object(runner.subprocess, "Popen",
                               return_value=process), \
             mock.patch.object(runner.os, "killpg") as kill:
            self.assertEqual(runner.main(), 124)
            kill.assert_called_once_with(12345, runner.signal.SIGKILL)
            self.assertEqual(process.wait.call_count, 2)

    def test_unavailable_xvfb_fails_closed_not_fallback_to_live_display(self):
        with mock.patch.dict(runner.os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}), \
             mock.patch.object(runner.sys, "platform", "linux"), \
             mock.patch.object(runner.shutil, "which", return_value=None), \
             mock.patch.object(runner.subprocess, "Popen") as spawn:
            self.assertEqual(runner.main(), 2)
            spawn.assert_not_called()

    def test_pytest_context_refuses_normal_gui_entry_before_gtk(self):
        env = dict(os.environ, SMOOTHCAST_TEST_CONTEXT="1",
                   PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run(
            [sys.executable, "-m", "cli", "--action", "about"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to start GTK from pytest", result.stderr)


    def test_smoke_application_has_no_network_polls_or_startup_cleanup(self):
        source = (ROOT / "src" / "cast_control.py").read_text("utf-8")
        ast.parse(source)
        self.assertIn("if selftest and not gui_test_safety.is_isolated_gui_test():",
                      source)
        self.assertIn("if not app.selftest:", source)
        self.assertIn("Gio.ApplicationFlags.NON_UNIQUE", source)
        self.assertIn("if not self.selftest:", source)
        self.assertIn("GLib.timeout_add(1500, self._selftest_quit)", source)


if __name__ == "__main__":
    unittest.main()
