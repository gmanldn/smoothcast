"""--demo must never accidentally launch the real GTK app (#523)."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli  # noqa: E402


class DemoCliSafetyTests(unittest.TestCase):
    def test_demo_request_rejects_before_import_or_live_gui_activation(self):
        for args in (["--demo"], ["--demo", "--self-test"],
                     ["--demo", "/tmp/some-film.mkv"]):
            with self.subTest(args=args):
                touched = []
                fake = types.ModuleType("cast_control")
                fake.main = lambda: touched.append("GUI") or 0
                stderr = StringIO()
                with mock.patch.object(sys, "argv", ["smoothcast", *args]), \
                     mock.patch.dict(sys.modules, {"cast_control": fake}), \
                     mock.patch.dict("os.environ", {"SMOOTHCAST_TEST_CONTEXT": "0"}), \
                     redirect_stderr(stderr):
                    result = cli._main()
                self.assertEqual(result, 2)
                self.assertEqual(touched, [])
                self.assertIn("Demo mode is not ready", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
