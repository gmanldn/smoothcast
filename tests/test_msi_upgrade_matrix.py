"""Portable tests for the A/B MSI upgrade matrix; never run Windows Installer (#535)."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import msi_upgrade_matrix as upgrade  # noqa: E402


class FixtureVersionTests(unittest.TestCase):
    def test_versions_increase_and_stay_in_bounds(self):
        self.assertEqual(upgrade.fixture_versions("2.0.40"), ("2.0.40", "2.0.41"))
        self.assertEqual(upgrade.fixture_versions("2.0.65535"), ("2.0.65535", "2.1.0"))
        self.assertEqual(upgrade.fixture_versions("2.255.65535"), ("2.255.65535", "3.0.0"))

    def test_bad_versions_are_refused(self):
        for bad in ("2.0", "2.0.1.2", "300.0.0", "255.255.65535", "x.y.z", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(upgrade.InstallerError):
                    upgrade.fixture_versions(bad)


class PlanTests(unittest.TestCase):
    def test_plan_installs_a_upgrades_b_then_rejects_downgrade(self):
        steps = upgrade.plan()
        names = [step["name"] for step in steps]
        self.assertEqual(names[0], "install_fixture_a")
        self.assertEqual(names[-1], "uninstall_fixture_b")
        reject = [step for step in steps if step["action"] == "reject"]
        self.assertEqual([step["fixture"] for step in reject], ["a"])
        self.assertTrue(any(step["action"] == "expect_version" for step in steps))


class ParseTests(unittest.TestCase):
    def test_registered_version_reads_the_first_nonblank_line(self):
        self.assertEqual(upgrade.parse_registered_version("\n  2.0.41  \n"), "2.0.41")
        self.assertEqual(upgrade.parse_registered_version(""), "")
        self.assertEqual(upgrade.parse_registered_version("   \n\n"), "")


class EvidenceTests(unittest.TestCase):
    def test_record_is_green_only_when_every_step_passes(self):
        steps = [upgrade.step_record(spec, ok=True, detail="") for spec in upgrade.plan()]

        def result(rows):
            return upgrade.record(commit="a", version="2.0.40", os_build="b", runner="r",
                                  started="s", duration=1.0, fixtures={}, steps=rows)["ok"]

        self.assertTrue(result(steps))
        self.assertFalse(result(steps[:-1]))
        self.assertFalse(result(list(reversed(steps))))
        self.assertFalse(result(steps + steps[:1]))
        self.assertFalse(result([steps[0]] * len(steps)))
        self.assertFalse(result([dict(steps[0], status="fail"), *steps[1:]]))

    def test_dry_run_contract_is_never_green(self):
        report = upgrade.dry_run("2.0.40", "2.0.41", {})
        self.assertFalse(report["ok"])
        self.assertTrue(report["steps"])
        self.assertTrue(all(step["status"] == "untested" for step in report["steps"]))

    def test_matrix_refuses_a_non_disposable_target(self):
        with mock.patch.object(upgrade, "require_disposable",
                               side_effect=upgrade.InstallerError("not disposable")):
            with self.assertRaises(upgrade.InstallerError):
                upgrade.run_matrix(Path("/tmp/a.msi"), Path("/tmp/b.msi"), "2.0.40", "2.0.41",
                                   report=Path("/tmp/r.json"), os_build="", runner="", commit="")


class MainTests(unittest.TestCase):
    def test_dry_run_writes_the_contract_and_exits_red(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "upgrade.json"
            argv = ["--fixture-a", "a", "--fixture-b", "b", "--report", str(report),
                    "--base-version", "2.0.40", "--dry-run"]
            with mock.patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(upgrade.main(argv), 1)
            body = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(body["schema"], upgrade.SCHEMA)
        self.assertFalse(body["ok"])

    def test_invalid_base_version_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "upgrade.json"
            argv = ["--fixture-a", "a", "--fixture-b", "b", "--report", str(report),
                    "--base-version", "nope", "--dry-run"]
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(upgrade.main(argv), 1)
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
