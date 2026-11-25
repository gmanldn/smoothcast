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
            fake_proc(root, "4250", ("/usr/bin/python3", "-u", APP))
            fake_proc(root, "4251", ("/usr/bin/python3.13", "-I", "-B", APP))
            fake_proc(root, "4252", ("/usr/bin/python3", "-m", APP))
            fake_proc(root, "4253", ("/usr/bin/python3", "-X", "dev", APP))
            fake_proc(root, "4254", ("/usr/bin/python3", "-u", "/tmp/check.py", APP))
            fake_proc(root, "4257", ("/usr/bin/python3", "-W", "ignore", APP))
            fake_proc(root, "4258", ("/usr/bin/python3", "-Xdev", "-Wignore", APP))
            fake_proc(root, "4259", ("/usr/bin/python3", "-X", APP))
            fake_proc(root, "4260", ("/usr/bin/python3", "-W", APP))
            fake_proc(root, "4261", ("/usr/bin/python3", "-W", "ignore", "/tmp/check.py", APP))
            fake_proc(root, "4262", ("/usr/bin/python3", "-X", "-c", APP))
            fake_proc(root, "4255", ("/usr/bin/python3", "-c", "print(1)", APP))
            fake_proc(root, "4256", ("/usr/bin/python-foreign", APP))
            (root / "uptime").write_text("1\n")
            self.assertEqual(sorted(launch.gui_instances(root)), [4242, 4250, 4251, 4253, 4257, 4258])

    @unittest.skipIf(os.name == "nt", "POSIX /proc process-table contract")
    def test_exclusions_never_report_own_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_proc(root, str(os.getpid()), ("/usr/bin/python3", APP))
            fake_proc(root, "4245", ("/usr/bin/python3", APP))
            self.assertEqual(launch.gui_instances(root), [4245])
            self.assertEqual(launch.gui_instances(root, {4245}), [])

    @unittest.skipIf(os.name == "nt", "POSIX /proc process-table contract")
    def test_recognised_other_installation_is_detected_only_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            other = root / "other install"
            (other / "src").mkdir(parents=True)
            (other / "setup").mkdir()
            script = other / "src" / "cast_control.py"
            script.touch()
            (other / "setup" / "launch.py").touch()
            (other / "pyproject.toml").write_text('name = "smoothcast"', encoding="utf-8")
            fake_proc(root, "4242", ("/usr/bin/python3", str(script)))
            fake_proc(root, "4243", ("/usr/bin/python3", "/unrelated/src/cast_control.py"))
            fake_proc(root, "4244", ("/usr/bin/python3", "-c", str(script)))
            self.assertEqual(launch.gui_instances(root), [])
            self.assertEqual(launch.gui_instances(root, all_installations=True), [4242])

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
        return outcome, args

    def test_no_running_instance_launches_normally(self):
        self.assertEqual(self.guard([], None, []), (None, []))

    @unittest.skipIf(os.name == "nt", "POSIX process signaling contract")
    def test_second_launch_asks_the_primary_to_reload_services(self):
        # A confirmed primary is asked to bounce its services in place; the
        # command line is forwarded so GApplication never starts a second GUI.
        self.assertEqual(self.guard([101], True, []),
                         (None, [launch.RELOAD_SERVICES_ARG]))

    def test_media_arguments_are_still_forwarded(self):
        # GApplication must forward the file, so let the GTK instance handle it.
        self.assertEqual(self.guard([101], True, ["/films/a.mkv"]),
                         (None, ["/films/a.mkv", launch.RELOAD_SERVICES_ARG]))

    @unittest.skipIf(os.name == "nt", "POSIX process signaling contract")
    def test_unresponsive_instance_refuses_duplicate_without_killing(self):
        self.assertEqual(self.guard([101, 102], False, []), (3, []))

    @unittest.skipIf(os.name == "nt", "POSIX /proc and session bus contract")
    def test_unprobeable_instance_is_left_alone(self):
        # No session bus or no gdbus: fail closed, never spawn a second GUI.
        self.assertEqual(self.guard([101], None, []), (3, []))

    @unittest.skipIf(os.name == "nt", "POSIX launcher guard")
    def test_wrong_install_activation_is_not_reported_as_selected_startup(self):
        with mock.patch.object(launch, "gui_instances", side_effect=[[101], []]), \
             mock.patch.object(launch, "activate_existing", return_value=True):
            self.assertEqual(launch.ensure_single_instance([]), 3)

    @unittest.skipIf(os.name == "nt", "POSIX launcher guard")
    def test_primary_exiting_during_activation_permits_clean_launch(self):
        with mock.patch.object(launch, "gui_instances", side_effect=[[101], [101], []]), \
             mock.patch.object(launch, "activate_existing", return_value=False):
            self.assertIsNone(launch.ensure_single_instance([]))

    def test_no_pid_only_termination_helper_survives(self):
        self.assertFalse(hasattr(launch, "stop_instances"))
        self.assertFalse(hasattr(launch, "_alive"))


class MediaArgumentForwardingTests(unittest.TestCase):
    def test_remote_uris_keep_their_original_scheme_and_query(self):
        caller = Path("/tmp/smoothcast-invoker")
        args = [
            "https://example.org/video?id=5&quality=high",
            "magnet:?xt=urn:btih:0123456789abcdef&dn=clip",
            "rtsp://example.org/stream",
            "smb://example.org/share/film.mkv",
            "file:///tmp/film%20name.mkv",
            "--action", "queue", "relative-film.mkv",
        ]
        result = launch.media_arguments_from_caller(args, caller)
        self.assertEqual(result[:-1], args[:-1])
        self.assertEqual(result[-1], str((caller / "relative-film.mkv").resolve()))

    def test_flags_and_action_value_are_not_rewritten_as_files(self):
        caller = Path("/tmp/smoothcast-invoker")
        result = launch.media_arguments_from_caller(
            ["--action", "play", "--no-gui", "subfolder/film.mkv"], caller,
        )
        self.assertEqual(result[:3], ["--action", "play", "--no-gui"])
        self.assertEqual(result[-1], str((caller / "subfolder/film.mkv").resolve()))

    def test_windows_drive_style_is_not_mistaken_for_uri(self):
        self.assertIsNone(launch._URI_ARGUMENT.match(r"C:\\Films\\video.mkv"))


class EarlyActivationTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX launcher activates through D-Bus")
    def test_existing_primary_is_checked_before_missing_runtime(self):
        # A moved/broken venv must not prevent a live primary being activated,
        # and a failed activation must not create a second competing GUI.
        for outcome in (0, 3):
            with self.subTest(outcome=outcome), \
                 mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": ""}), \
                 mock.patch.object(launch, "ensure_single_instance", return_value=outcome), \
                 mock.patch.object(launch, "python_path",
                                   side_effect=AssertionError("do not probe missing venv")):
                self.assertEqual(launch.main([], prechecked=False), outcome)


    def test_canonical_launcher_checks_singleton_before_runtime_bootstrap(self):
        source = (ROOT / "sc.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_main")
        body = ast.get_source_segment(source, fn)
        # The demo branch also probes the runtime but never the real singleton.
        self.assertLess(body.index("launch.ensure_single_instance(args)"),
                        body.rindex("launch.runtime_ready()"))
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
