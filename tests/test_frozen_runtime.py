"""Headless frozen-runtime regression tests; never start GUI or a real receiver."""
from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import castctl
import cli
import frozen_runtime
import startup_cleanup
import streamer


class FrozenRuntimeTests(unittest.TestCase):
    def test_source_commands_preserve_existing_contract(self):
        server_script = Path("/tmp/smoothcast/server.py")
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=False):
            self.assertEqual(
                frozen_runtime.server_command(server_script),
                [sys.executable, str(server_script)],
            )
            self.assertEqual(
                frozen_runtime.catt_command("/opt/bin/catt", ["scan", "-j"]),
                ["/opt/bin/catt", "scan", "-j"],
            )
            self.assertIsNone(frozen_runtime.dispatch_frozen_helper([frozen_runtime.SERVER_FLAG]))

    def test_frozen_children_reexec_our_executable(self):
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True):
            self.assertEqual(
                frozen_runtime.server_command(Path("/nonexistent/server.py")),
                [sys.executable, frozen_runtime.SERVER_FLAG],
            )
            with mock.patch.object(frozen_runtime, "companion_executable", return_value=Path("/tmp/SmoothCastCLI")):
                self.assertEqual(
                    frozen_runtime.catt_command("/untrusted/catt", ["-d", "TV", "play"]),
                    [str(Path("/tmp/SmoothCastCLI")), frozen_runtime.CATT_FLAG, "-d", "TV", "play"],
                )

    def test_frozen_catt_requires_console_companion(self):
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.object(frozen_runtime.sys, "executable", "/tmp/SmoothCast"):
            with mock.patch.object(Path, "is_file", return_value=False):
                with self.assertRaisesRegex(FileNotFoundError, "console helper"):
                    frozen_runtime.catt_command("catt", ["scan", "-j"])

    def test_frozen_catt_helper_identity_is_exact(self):
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.object(frozen_runtime, "companion_executable", return_value=Path("/tmp/SmoothCastCLI")):
            self.assertTrue(frozen_runtime.is_our_catt_helper("/tmp/SmoothCastCLI"))
            self.assertFalse(frozen_runtime.is_our_catt_helper("/tmp/NotSmoothCastCLI"))

    def test_frozen_server_dispatch_does_not_import_gtk(self):
        fake_server = types.ModuleType("server")
        fake_server.main = mock.Mock()
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.dict(sys.modules, {"server": fake_server}):
            self.assertEqual(frozen_runtime.dispatch_frozen_helper([frozen_runtime.SERVER_FLAG]), 0)
            self.assertEqual(
                frozen_runtime.dispatch_frozen_helper(
                    [frozen_runtime.SERVER_FLAG, "--bind", "192.168.1.23"]
                ), 0,
            )
            # develop always launches the server with --port (fallback ports).
            self.assertEqual(
                frozen_runtime.dispatch_frozen_helper(
                    [frozen_runtime.SERVER_FLAG, "--port", "8768"]
                ), 0,
            )
            self.assertEqual(
                frozen_runtime.dispatch_frozen_helper(
                    [frozen_runtime.SERVER_FLAG, "--port", "8768", "--bind", "192.168.1.23"]
                ), 0,
            )
            for bad in (
                ["junk"],
                ["--extra", "not-allowed"],
                ["--port"],
                ["--port", "8768", "--port", "8769"],
                ["--bind", "192.168.1.23", "--bind", "10.0.0.2"],
                ["--port", "8768", "--extra", "x"],
                ["--port", "8768", "stray"],
            ):
                with self.subTest(bad=bad):
                    self.assertEqual(
                        frozen_runtime.dispatch_frozen_helper(
                            [frozen_runtime.SERVER_FLAG, *bad]), 2)
        self.assertEqual(
            [call.args for call in fake_server.main.call_args_list],
            [([],), (["--bind", "192.168.1.23"],), (["--port", "8768"],),
             (["--port", "8768", "--bind", "192.168.1.23"],)],
        )

    def test_catt_child_receives_unmodified_args_and_restores_parent_argv(self):
        fake_package = types.ModuleType("catt")
        fake_package.__path__ = []
        fake_cli = types.ModuleType("catt.cli")
        calls = []

        def fake_main():
            calls.append(list(sys.argv))
            return 0

        fake_cli.main = fake_main
        old = sys.argv
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.dict(sys.modules, {"catt": fake_package, "catt.cli": fake_cli}):
            self.assertEqual(
                frozen_runtime.dispatch_frozen_helper([frozen_runtime.CATT_FLAG, "-d", "Living Room TV", "play"]),
                0,
            )
        self.assertEqual(calls, [["catt", "-d", "Living Room TV", "play"]])
        self.assertIs(sys.argv, old)

    def test_main_dispatches_before_any_gui_import(self):
        with mock.patch.object(frozen_runtime, "dispatch_frozen_helper", return_value=0), \
             mock.patch.object(sys, "argv", ["SmoothCast", frozen_runtime.SERVER_FLAG]):
            self.assertEqual(cli.main(), 0)

    def test_media_probe_flag_prints_json_and_reports_failure_in_the_exit_code(self):
        import io
        import media_tools
        for ok, expected in ((True, 0), (False, 1)):
            report = {"strict": False, "tools": {}, "ok": ok}
            with mock.patch.object(frozen_runtime, "dispatch_frozen_helper", return_value=None), \
                 mock.patch.object(media_tools, "report", return_value=report), \
                 mock.patch.object(sys, "argv", ["SmoothCastCLI", "--_smoothcast-media-probe"]), \
                 mock.patch("sys.stdout", new=io.StringIO()) as out:
                self.assertEqual(cli.main(), expected)
            self.assertEqual(__import__("json").loads(out.getvalue())["ok"], ok)

    def test_source_package_check_rejects_without_gtk(self):
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=False), \
             mock.patch.object(frozen_runtime, "dispatch_frozen_helper", return_value=None), \
             mock.patch.object(sys, "argv", ["SmoothCast", "--_smoothcast-package-check"]):
            self.assertEqual(cli.main(), 2)

    def test_streamer_uses_child_dispatch_without_starting_processes(self):
        fake_process = mock.Mock()
        fake_process.poll.return_value = None
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.object(streamer, "_port_open", return_value=False), \
             mock.patch.object(streamer, "_server_healthy", return_value=True), \
             mock.patch.object(streamer.subprocess, "Popen", return_value=fake_process) as spawn:
            session = streamer.Session()
            session._start_server()
        self.assertEqual(
            spawn.call_args.args[0],
            [sys.executable, frozen_runtime.SERVER_FLAG, "--port", str(session.port)],
        )
        self.assertIs(session.server, fake_process)

    def test_streamer_direct_and_hls_catt_calls_share_frozen_command(self):
        with mock.patch.object(frozen_runtime, "is_frozen", return_value=True), \
             mock.patch.object(frozen_runtime, "companion_executable", return_value=Path("/tmp/SmoothCastCLI")), \
             mock.patch.object(castctl.subprocess, "run") as runner:
            castctl._run(["scan", "-j"])
        self.assertEqual(
            runner.call_args.args[0],
            [str(Path("/tmp/SmoothCastCLI")), frozen_runtime.CATT_FLAG, "scan", "-j"],
        )

    def test_cleanup_recognises_only_our_frozen_server_signature(self):
        # Strict process_identity recognizes the real shipped executable,
        # never a generic Python or foreign process with an injected flag.
        command = ("/opt/SmoothCast", frozen_runtime.SERVER_FLAG)
        self.assertEqual(startup_cleanup.process_kind(command), "server")
        self.assertIsNone(startup_cleanup.process_kind(("/usr/bin/unrelated", frozen_runtime.SERVER_FLAG)))
        self.assertIsNone(startup_cleanup.process_kind((sys.executable, frozen_runtime.SERVER_FLAG)))

    def test_package_workflow_uses_immutable_upstream_action_refs(self):
        root = Path(__file__).resolve().parents[1]
        yaml = (root / ".github" / "workflows" / "package.yml").read_text("utf-8")
        refs = [line.strip().removeprefix("- uses: ").strip()
                for line in yaml.splitlines() if "- uses:" in line]
        self.assertEqual(len(refs), 7)
        for ref in refs:
            self.assertRegex(ref, r"^[\w./-]+@[a-f0-9]{40} # v\d+$")

    def test_package_workflow_smokes_frozen_cli_off_the_developer_path(self):
        # #528: the payload manifest gate is blocking, and the frozen CLI is
        # run with developer Python/MSYS2 removed from PATH from a temporary
        # directory whose name has spaces and non-ASCII characters.
        repo = Path(__file__).resolve().parents[1]
        yaml = (repo / ".github" / "workflows" / "package.yml").read_text("utf-8")
        manifest = yaml.split("- name: Record and verify Windows payload manifest", 1)[1]
        self.assertNotIn("continue-on-error", manifest.split("- name:", 1)[0])
        smoke = yaml.split("- name: Smoke frozen CLI off the developer PATH", 1)[1]
        smoke = smoke.split("- name:", 1)[0]
        self.assertIn("--version", smoke)
        self.assertIn("--_smoothcast-package-check", smoke)
        self.assertIn("env -u PYTHONPATH -u MSYSTEM", smoke)
        self.assertIn("/c/Windows/System32", smoke)
        self.assertIn("SmoothCast smoke \u2713", smoke)

    def test_spec_and_packaging_driver_are_versioned(self):
        repo = Path(__file__).resolve().parents[1]
        spec = (repo / "packaging" / "SmoothCast.spec").read_text(encoding="utf-8")
        driver = (repo / "scripts" / "build_release.py").read_text(encoding="utf-8")
        self.assertIn('collect_all("catt")', spec)
        self.assertIn('"gi.repository.Adw"', spec)
        self.assertIn('console_exe = EXE(', spec)
        self.assertIn('BUNDLE(', spec)
        self.assertIn('verify(ROOT / "dist")', driver)
        workflow = (repo / ".github" / "workflows" / "package.yml").read_text("utf-8")
        # MSYS2 UCRT64 cannot build upstream psutil from PyPI using pip's
        # native Windows extension toolchain: use the distro binary wheel.
        self.assertIn("mingw-w64-ucrt-x86_64-python-psutil", workflow)
        self.assertIn("venv --system-site-packages", workflow)


if __name__ == "__main__":
    unittest.main()
