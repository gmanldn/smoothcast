"""The isolated GUI smoke must not report failure on a scratch-cleanup race.

A Mesa shader-cache helper can still be writing as the run finishes; that must
never turn a successful SELFTEST into a non-zero exit.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "test_gui_isolated.py"
SCRATCH = "/tmp/smoothcast-xvfb-selftest"


def load_runner():
    spec = importlib.util.spec_from_file_location("smoke_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScratchCleanupTests(unittest.TestCase):
    def setUp(self):
        self.runner = load_runner()

    def test_late_writer_is_retried_then_accepted(self):
        with mock.patch.object(
            self.runner.shutil, "rmtree",
            side_effect=[OSError("Directory not empty"), OSError("busy"), None],
        ) as rmtree:
            self.runner.discard_scratch(SCRATCH)
        self.assertEqual(rmtree.call_count, 3)

    def test_persistent_writer_falls_back_to_ignore_errors(self):
        # A real rmtree(ignore_errors=True) never raises; the mock cannot honour
        # that, so the call is expected to surface while the arguments are not.
        with mock.patch.object(
            self.runner.shutil, "rmtree", side_effect=OSError("Directory not empty"),
        ) as rmtree:
            with self.assertRaises(OSError):
                self.runner.discard_scratch(SCRATCH)
        self.assertEqual(rmtree.call_count, 4)
        self.assertTrue(rmtree.call_args_list[-1].kwargs.get("ignore_errors"))

    def test_missing_scratch_directory_is_fine(self):
        with mock.patch.object(self.runner.shutil, "rmtree",
                               side_effect=FileNotFoundError) as rmtree:
            self.runner.discard_scratch("/tmp/smoothcast-xvfb-gone")
        self.assertEqual(rmtree.call_count, 1)

    def test_runner_uses_the_tolerant_cleanup(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn('tempfile.mkdtemp(prefix="smoothcast-xvfb-")', source)
        self.assertIn("finally:\n        discard_scratch(folder)", source)


if __name__ == "__main__":
    unittest.main()
