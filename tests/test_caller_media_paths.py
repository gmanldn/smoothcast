"""Caller-relative media loading contracts without a GTK display or actual app."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import launch


def command_line_method():
    """Extract the real GApplication handler but never import gi or start GTK."""
    source = (ROOT / "src" / "cast_control.py").read_text("utf-8")
    tree = ast.parse(source)
    app = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "CastControlApp")
    method = next(n for n in app.body
                  if isinstance(n, ast.FunctionDef) and n.name == "do_command_line")
    # Only this method's source is needed; GTK-independent fake window.
    text = ast.get_source_segment(source, method)
    code = "class TestApp:\n" + textwrap.indent(textwrap.dedent(text), "    ")
    namespace = {"os": os, "pathlib": __import__("pathlib"), "GLib": mock.MagicMock()}
    exec(compile(code, "<real-command-line-handler>", "exec"), namespace)
    return namespace["TestApp"]


class CallerMediaPathTests(unittest.TestCase):
    def test_argument_translation_precedes_launcher_chdir(self):
        with tempfile.TemporaryDirectory() as folder:
            # macOS temp roots can be symlinks (for example /var -> /private/var).
            base = Path(folder).resolve()
            caller, checkout = base / "caller", base / "checkout"
            caller.mkdir()
            checkout.mkdir()
            (caller / "film.mkv").write_text("correct")
            (checkout / "film.mkv").write_text("wrong")
            observed = {}

            def subprocess_call(command, *, cwd, env):
                observed["args"] = command
                observed["cwd_at_exec"] = os.getcwd()
                observed["child_cwd"] = cwd
                return 0

            with mock.patch.object(launch, "ROOT", checkout), \
                 mock.patch.object(launch, "python_path", return_value=Path("/venv/python")), \
                 mock.patch.object(launch, "runtime_environment", return_value={}), \
                 mock.patch.object(launch.subprocess, "call",
                                   side_effect=subprocess_call), \
                 mock.patch.object(launch.os, "chdir") as chdir, \
                 mock.patch.object(launch, "ensure_single_instance", return_value=None), \
                 mock.patch.object(launch.Path, "cwd", return_value=caller), \
                 mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}):
                launch.main(["film.mkv"])
            self.assertEqual(observed["args"][-1], str((caller / "film.mkv").resolve()))
            self.assertEqual(observed["child_cwd"], checkout)
            chdir.assert_not_called()
            self.assertNotEqual(observed["args"][-1], str((checkout / "film.mkv").resolve()))

    def test_missing_caller_media_must_not_fall_back_to_checkout_decoy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            caller, checkout = root / "caller", root / "checkout"
            caller.mkdir()
            checkout.mkdir()
            (checkout / "missing.mkv").touch()
            result = launch.media_arguments_from_caller(
                ["missing.mkv"], caller,
            )
            self.assertEqual(result, [str(caller / "missing.mkv")])

    def test_action_option_and_uri_are_preserved(self):
        cwd = Path(tempfile.gettempdir()).resolve() / "another directory"
        args = ["--action", "stop", "file:///tmp/test.mkv", "--whatever", "film.mp4"]
        got = launch.media_arguments_from_caller(args, cwd)
        self.assertEqual(got[:4], args[:4])
        self.assertEqual(got[-1], str((cwd / "film.mp4").resolve()))

    def test_forwarded_command_line_uses_callers_cwd_not_running_process(self):
        cls = command_line_method()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            caller, other = root / "called from", root / "already running"
            caller.mkdir()
            other.mkdir()
            (caller / "film.mkv").touch()
            (other / "film.mkv").touch()
            app = cls()
            app.activate = mock.Mock()
            window = mock.Mock()
            app._window = lambda: window
            command = mock.Mock()
            command.get_arguments.return_value = ["smoothcast", "film.mkv"]
            for passed_cwd in (str(caller), os.fsencode(str(caller))):
                with self.subTest(cwd_type=type(passed_cwd).__name__):
                    command.get_cwd.return_value = passed_cwd
                    with mock.patch.object(Path, "cwd", return_value=other):
                        self.assertEqual(app.do_command_line(command), 0)
                    window.open_paths.assert_called_with([str(caller / "film.mkv")])
            self.assertEqual(window.open_paths.call_count, 2)
            self.assertEqual(app.activate.call_count, 2)

    def test_forwarded_missing_caller_file_does_not_use_decoy(self):
        cls = command_line_method()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            caller, checkout = root / "caller", root / "checkout"
            caller.mkdir()
            checkout.mkdir()
            (checkout / "film.mkv").touch()
            app = cls()
            app.activate = mock.Mock()
            window = mock.Mock()
            app._window = lambda: window
            command = mock.Mock()
            command.get_arguments.return_value = ["smoothcast", "film.mkv"]
            command.get_cwd.return_value = str(caller)
            with mock.patch.object(Path, "cwd", return_value=checkout):
                self.assertEqual(app.do_command_line(command), 0)
            window.open_paths.assert_not_called()


if __name__ == "__main__":
    unittest.main()
