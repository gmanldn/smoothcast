"""Headless tests for the Windows MSI lifecycle harness (#535)."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_windows_msi_lifecycle", ROOT / "scripts" / "ci" / "windows_msi_lifecycle.py"
)
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


class FixtureVersionTests(unittest.TestCase):
    def test_fixture_versions_increase_within_bounds(self):
        self.assertEqual(lifecycle.fixture_versions("2.0.34"), ("2.0.34", "2.0.35"))
        self.assertEqual(lifecycle.fixture_versions("2.0.65535"), ("2.0.65535", "2.1.0"))
        self.assertEqual(lifecycle.fixture_versions("2.255.65535"), ("2.255.65535", "3.0.0"))

    def test_fixture_versions_reject_bad_input(self):
        for bad in ("2.0", "2.0.1.2", "300.0.0", "2.0.70000", "x.y.z", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(lifecycle.LifecycleError):
                    lifecycle.fixture_versions(bad)


class PlanTests(unittest.TestCase):
    def test_plan_is_ordered_install_to_uninstall(self):
        names = [step["name"] for step in lifecycle.plan()]
        self.assertEqual(names[0], "install_fixture_a")
        self.assertEqual(names[-1], "install_dir_gone")
        self.assertIn("upgrade_to_fixture_b", names)
        self.assertIn("uninstall_fixture_b", names)

    def test_every_step_accepts_only_documented_exit_codes(self):
        for step in lifecycle.plan():
            self.assertTrue(step["accept"])
            self.assertTrue(set(step["accept"]) <= {0, lifecycle.REBOOT_REQUIRED})

    def test_msiexec_command_is_non_interactive_and_no_restart(self):
        command = lifecycle.msiexec_command("install", Path("C:/a.msi"), Path("C:/a.log"))
        self.assertEqual(command[:2], ["msiexec", "/i"])
        self.assertIn("/qn", command)
        self.assertIn("/norestart", command)
        self.assertEqual(lifecycle.msiexec_command("repair", Path("a"), Path("l"))[1], "/fa")
        self.assertEqual(lifecycle.msiexec_command("uninstall", Path("a"), Path("l"))[1], "/x")


class EvidenceTests(unittest.TestCase):
    def test_scrub_redacts_user_and_temp_paths(self):
        text = (r"C:\Users\alice\AppData\Local\Temp\sc-123\out.log "
                r"and C:\Users\alice\setup")
        scrubbed = lifecycle.scrub(text)
        self.assertNotIn("alice", scrubbed)
        self.assertIn("<user>", scrubbed)
        self.assertIn("<temp>", scrubbed)

    def test_record_is_green_only_when_every_step_passes(self):
        passed = lifecycle.step_record({"name": "x", "action": "install", "accept": [0]},
                                       exit_code=0, command=["msiexec"], log="", status="pass")
        self.assertTrue(lifecycle.record(commit="a", version="2.0.34", os_build="b",
                                         runner="r", started="s", duration=1.0,
                                         fixtures={}, steps=[passed])["ok"])
        for status in ("fail", "untested"):
            step = lifecycle.step_record({"name": "x", "action": "install", "accept": [0]},
                                         exit_code=None, command=[], log="", status=status)
            self.assertFalse(lifecycle.record(commit="a", version="2.0.34", os_build="b",
                                              runner="r", started="s", duration=1.0,
                                              fixtures={}, steps=[step])["ok"])

    def test_dry_run_contract_is_never_green(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "SmoothCast-2.0.34-x64.msi"
            fixture.write_bytes(b"not a real msi")
            report = lifecycle.dry_run({"a": fixture, "b": fixture}, version="2.0.34",
                                       runner="local")
            digest = lifecycle.sha256(fixture)
        self.assertFalse(report["ok"])
        self.assertTrue(report["steps"])
        self.assertTrue(all(step["status"] == "untested" for step in report["steps"]))
        self.assertEqual(report["fixtures"]["a"], digest)

    def test_real_matrix_refuses_to_run_off_windows(self):
        with mock.patch.object(lifecycle.sys, "platform", "linux"):
            with self.assertRaises(lifecycle.LifecycleError):
                lifecycle.run_matrix({}, install_dir=Path("/tmp/x"), logs=Path("/tmp/l"),
                                     os_build="", runner="", commit="", version="2.0.34")


class MainTests(unittest.TestCase):
    def test_dry_run_writes_the_evidence_file_and_exits_red(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "SmoothCast-2.0.34-x64.msi"
            fixture.write_bytes(b"fake")
            output = Path(folder) / "results.json"
            stdout = io.StringIO()
            argv = ["--fixture-a", str(fixture), "--fixture-b", str(fixture),
                    "--install-dir", folder, "--version", "2.0.34", "--dry-run",
                    "--output", str(output)]
            with mock.patch("sys.stdout", new=stdout):
                self.assertEqual(lifecycle.main(argv), 1)
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], lifecycle.SCHEMA)
        self.assertFalse(report["ok"])

    def test_invalid_version_is_a_prerequisite_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "results.json"
            argv = ["--fixture-a", "a", "--fixture-b", "b", "--install-dir", folder,
                    "--version", "not-a-version", "--dry-run", "--output", str(output)]
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(lifecycle.main(argv), 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
