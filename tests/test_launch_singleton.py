"""Single-instance launch guard: a launch always ends with a visible window.

A previous instance that cannot show its window (a failed activation, or a
hung process) would otherwise keep the application id and swallow every later
launch. The launcher asks a running instance to present itself and clears it
when it cannot.
"""
from __future__ import annotations

from pathlib import Path
import ast
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))

import launch  # noqa: E402  (setup/launch.py is GTK-free by design)

APP = str((ROOT / "src" / "cast_control.py").resolve())
CONTROL = ROOT / "src" / "cast_control.py"


def fake_proc(root: Path, pid: str, argv: tuple[str, ...]) -> None:
    directory = root / pid
    directory.mkdir()
    (directory / "cmdline").write_bytes(b"\0".join(part.encode() for part in argv))


class ProcScanTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX /proc process-table contract")
    def test_matches_only_this_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_proc(root, "4242", ("/usr/bin/python3", APP))
            fake_proc(root, "4243", ("/usr/bin/python3", "/elsewhere/src/cast_control.py"))
            fake_proc(root, "4244", ("/usr/bin/ffplay", APP))
            fake_proc(root, "4246", ("/usr/bin/cat", APP))
            fake_proc(root, "4247", ("/usr/bin/python3", "/tmp/check.py", APP))
            fake_proc(root, "4248", ("/usr/bin/python3", "-c", APP))
            fake_proc(root, "4249", ("/usr/bin/python3", "/tmp/test.py", "--file", APP))
            (root / "uptime").write_text("1\n")
            self.assertEqual(sorted(launch.gui_instances(root)), [4242])

    @unittest.skipIf(os.name == "nt", "POSIX /proc process-table contract")
    def test_exclusions_never_report_own_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_proc(root, str(os.getpid()), ("/usr/bin/python3", APP))
            fake_proc(root, "4245", ("/usr/bin/python3", APP))
            self.assertEqual(launch.gui_instances(root), [4245])
            self.assertEqual(launch.gui_instances(root, {4245}), [])

    def test_identity_comes_from_the_app_source(self):
        app_id, object_path = launch.app_identity()
        self.assertIn(f'APP_ID = "{app_id}"', (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8"))
        # Dots become path separators, dashes underscores (verified against the
        # object tree the running GTK app exports).
        self.assertEqual((app_id, object_path), ("local.cast-control", "/local/cast_control"))


class GuardBehaviourTests(unittest.TestCase):
    def guard(self, instances, activated, args):
        with mock.patch.object(launch, "gui_instances", return_value=instances), \
                mock.patch.object(launch, "activate_existing", return_value=activated), \
                mock.patch.object(launch.os, "kill",
                                  side_effect=AssertionError("never signal from a stale PID")):
            outcome = launch.ensure_single_instance(args)
        return outcome, []

    def test_no_running_instance_launches_normally(self):
        self.assertEqual(self.guard([], None, []), (None, []))

    @unittest.skipIf(os.name == "nt", "POSIX process signaling contract")
    def test_second_launch_presents_and_does_not_start_again(self):
        self.assertEqual(self.guard([101], True, []), (0, []))

    def test_media_arguments_are_still_forwarded(self):
        # GApplication must forward the file, so let the GTK instance handle it.
        self.assertEqual(self.guard([101], True, ["/films/a.mkv"]), (None, []))

    @unittest.skipIf(os.name == "nt", "POSIX process signaling contract")
    def test_unresponsive_instance_refuses_duplicate_without_killing(self):
        self.assertEqual(self.guard([101, 102], False, []), (3, []))

    @unittest.skipIf(os.name == "nt", "POSIX /proc and session bus contract")
    def test_unprobeable_instance_is_left_alone(self):
        # No session bus or no gdbus: fail closed, never spawn a second GUI.
        self.assertEqual(self.guard([101], None, []), (3, []))

    def test_no_pid_only_termination_helper_survives(self):
        self.assertFalse(hasattr(launch, "stop_instances"))
        self.assertFalse(hasattr(launch, "_alive"))


class EarlyActivationTests(unittest.TestCase):
    def test_canonical_launcher_checks_singleton_before_runtime_bootstrap(self):
        source = (ROOT / "smoothcast").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "main")
        body = ast.get_source_segment(source, fn)
        self.assertLess(body.index("launch.ensure_single_instance(args)"),
                        body.index("launch.runtime_ready()"))
        self.assertLess(body.index("launch.ensure_single_instance(args)"),
                        body.index("_bootstrap(target)"))
        self.assertIn("launch.main(args, prechecked=True)", body)

    @unittest.skipIf(os.name == "nt", "POSIX exec launcher")
    def test_secondary_launcher_skips_recheck_when_prechecked(self):
        with mock.patch.object(launch, "python_path", return_value=Path("/fake/python")), \
             mock.patch.object(launch, "media_arguments_from_caller", return_value=[]), \
             mock.patch.object(launch, "runtime_environment", return_value={}), \
             mock.patch.object(launch, "ensure_single_instance",
                               side_effect=AssertionError("guard must run once")), \
             mock.patch.object(launch.os, "chdir"), \
             mock.patch.object(launch.os, "execvpe", side_effect=OSError("stubbed exec")):
            with mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": ""}):
                self.assertEqual(launch.main([], prechecked=True), 1)


class AppFailureTests(unittest.TestCase):
    """The windowless-primary state must be impossible to reach."""

    def methods(self, class_name: str) -> dict[str, str]:
        source = CONTROL.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return {member.name: ast.get_source_segment(source, member)
                        for member in node.body
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))}
        raise AssertionError(f"{class_name} not found")

    def test_activation_always_presents_the_window(self):
        for handler in ("do_activate", "do_open", "do_command_line"):
            segment = self.methods("CastControlApp")[handler]
            self.assertIn("window.present()", segment)

    def test_window_failure_is_fatal(self):
        methods = self.methods("CastControlApp")
        window = methods["_window"]
        self.assertIn("self.fatal = True", window)
        self.assertIn("GLib.idle_add(self._quit_fatal)", window)
        self.assertIn("self.quit()", methods["_quit_fatal"])
        main = ast.get_source_segment(
            CONTROL.read_text(encoding="utf-8"),
            next(node for node in ast.parse(CONTROL.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef) and node.name == "main"),
        )
        self.assertIn("if app.fatal:", main)
        self.assertIn("return 1", main)

    def test_present_clears_minimised_window(self):
        from gui_source import main_window_methods
        present = main_window_methods()["present"]
        self.assertIn("self.unminimize()", present)
        self.assertIn("super().present()", present)


if __name__ == "__main__":
    unittest.main()
