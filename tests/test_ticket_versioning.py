"""Pure-stdlib regression for ticket-aware and stale-safe semantic version bumps."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_bump_version", ROOT / "scripts" / "ci" / "bump_version.py"
)
assert SPEC is not None and SPEC.loader is not None
bump_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump_version)
SOURCE = "MAJOR = 1\nMINOR = 2\nPATCH = 25\n"


class TicketVersioningTests(unittest.TestCase):
    def run_cli(self, path: Path, *args: str):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bump_version.main(["patch", "--file", str(path), *args])
        return code, out.getvalue(), err.getvalue()

    def test_existing_api_still_increments_patch_minor_and_major(self):
        self.assertEqual(bump_version.current_version(SOURCE), "1.2.25")
        updated, version = bump_version.bump(SOURCE)
        self.assertEqual(version, "1.2.26")
        self.assertEqual(bump_version.current_version(updated), version)
        self.assertEqual(bump_version.bump(SOURCE, "minor")[1], "1.3.0")
        self.assertEqual(bump_version.bump(SOURCE, "major")[1], "2.0.0")

    def test_missing_and_duplicate_version_parts_are_not_accepted(self):
        for text in ("", "PATCH = 25\n", SOURCE + "PATCH = 26\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    bump_version.current_version(text)

    def test_dry_run_and_issue_reference_leave_stdout_machine_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version.py"
            path.write_text(SOURCE, encoding="utf-8")
            code, out, err = self.run_cli(
                path, "--issue", "541", "--expect", "1.2.25", "--dry-run"
            )
            self.assertEqual((code, out), (0, "1.2.26\n"))
            self.assertIn("Refs #541", err)
            self.assertEqual(path.read_text(encoding="utf-8"), SOURCE)
            code, out, err = self.run_cli(
                path, "--issue", "541", "--expect", "1.2.25"
            )
            self.assertEqual((code, out), (0, "1.2.26\n"))
            self.assertEqual(bump_version.current_version(path.read_text()), "1.2.26")

    def test_stale_expected_and_bad_issue_numbers_never_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version.py"
            path.write_text(SOURCE, encoding="utf-8")
            code, out, err = self.run_cli(path, "--expect", "1.2.24", "--issue", "541")
            self.assertEqual((code, out), (1, ""))
            self.assertIn("stale version:", err)
            self.assertEqual(path.read_text(), SOURCE)
            code, out, err = self.run_cli(path, "--issue", "0")
            self.assertEqual((code, out), (1, ""))
            self.assertIn("positive", err)
            self.assertEqual(path.read_text(), SOURCE)

    def test_legacy_command_remains_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version.py"
            path.write_text(SOURCE, encoding="utf-8")
            self.assertEqual(self.run_cli(path), (0, "1.2.26\n", ""))
            self.assertEqual(bump_version.current_version(path.read_text()), "1.2.26")


if __name__ == "__main__":
    unittest.main()
