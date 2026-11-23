"""Mocked native GTK CI provisioning; never installs packages or opens GTK."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_gtk_ci", ROOT / "scripts" / "ci" / "install_gtk_import_deps.py"
)
assert SPEC is not None and SPEC.loader is not None
deps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deps)


def completed(command, code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, code, stdout, stderr)


class GtkCiBootstrapTests(unittest.TestCase):
    def simulate(self, *, installed=(), fail_first=False, fail_update=False,
                 fail_retry=False, fail_import=False):
        calls = []
        installs = 0

        def fake(command, **kwargs):
            nonlocal installs
            calls.append(command)
            self.assertFalse(kwargs.get("shell", False))
            if command[0] == "dpkg-query":
                return completed(command, 0, "install ok installed"
                                 ) if command[-1] in installed else completed(
                                     command, 1, stderr="not installed")
            if command[:3] == ["sudo", "apt-get", "install"]:
                installs += 1
                fail = fail_first and installs == 1 or fail_retry and installs > 1
                return completed(command, 1 if fail else 0, stderr="apt error" if fail else "")
            if command[:3] == ["sudo", "apt-get", "update"]:
                return completed(command, 1 if fail_update else 0,
                                 stderr="index unavailable" if fail_update else "")
            if command[0] == deps.SYSTEM_PYTHON:
                return completed(command, 1 if fail_import else 0,
                                 stderr="gi unavailable" if fail_import else "")
            self.fail(f"unexpected subprocess: {command}")

        with mock.patch.object(deps.subprocess, "run", side_effect=fake):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                status = deps.main()
        return status, calls

    def test_preinstalled_packages_skip_apt_and_still_run_real_import_probe(self):
        status, calls = self.simulate(installed=deps.PACKAGES)
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), len(deps.PACKAGES) + 1)
        self.assertEqual(calls[-1][0], deps.SYSTEM_PYTHON)
        self.assertFalse(any(c[0] == "sudo" for c in calls))

    def test_partial_missing_installs_only_missing_packages(self):
        status, calls = self.simulate(installed=deps.PACKAGES[:3])
        self.assertEqual(status, 0)
        commands = [c for c in calls if c[:3] == ["sudo", "apt-get", "install"]]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][-1], "python3-psutil")
        self.assertNotIn("python3-gi", commands[0])
        self.assertIn("--no-install-recommends", commands[0])
        self.assertFalse(any(c[:3] == ["sudo", "apt-get", "update"] for c in calls))

    def test_failed_first_install_refreshes_once_and_retries(self):
        status, calls = self.simulate(fail_first=True)
        self.assertEqual(status, 0)
        apt = [c[2] for c in calls if c[0] == "sudo"]
        self.assertEqual(apt, ["install", "update", "install"])
        self.assertEqual(calls[-1][0], deps.SYSTEM_PYTHON)

    def test_failed_update_stops_without_retry_or_import(self):
        status, calls = self.simulate(fail_first=True, fail_update=True)
        self.assertEqual(status, 1)
        self.assertEqual([c[2] for c in calls if c[0] == "sudo"],
                         ["install", "update"])
        self.assertNotEqual(calls[-1][0], deps.SYSTEM_PYTHON)

    def test_failed_second_install_stops_without_import(self):
        status, calls = self.simulate(fail_first=True, fail_retry=True)
        self.assertEqual(status, 1)
        self.assertEqual([c[2] for c in calls if c[0] == "sudo"],
                         ["install", "update", "install"])
        self.assertNotEqual(calls[-1][0], deps.SYSTEM_PYTHON)

    def test_broken_system_interpreter_fails_even_with_installed_packages(self):
        status, calls = self.simulate(installed=deps.PACKAGES, fail_import=True)
        self.assertEqual(status, 1)
        self.assertEqual(calls[-1][0], "/usr/bin/python3")

    def test_process_timeout_fails_closed(self):
        with mock.patch.object(
            deps.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(["dpkg-query"], timeout=15),
        ):
            with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                self.assertEqual(deps.main(), 1)

    def test_workflow_never_skips_actual_import_budget(self):
        workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
        start = workflow.split("  import-budget:\n", 1)[1].split("  lint:\n", 1)[0]
        self.assertIn("python3 scripts/ci/install_gtk_import_deps.py", start)
        self.assertIn("/usr/bin/python3 scripts/ci/import_budget.py", start)
        self.assertNotIn("apt-get update &&", start)


if __name__ == "__main__":
    unittest.main()
