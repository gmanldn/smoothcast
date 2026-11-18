"""Prove the Python floor runs full portable tests without starting GTK."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortableMatrixTests(unittest.TestCase):
    def test_published_floor_and_primary_python_run_all_pytest(self):
        workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
        portable = workflow.split("  portable-tests:", 1)[1].split(
            "  media-integration:", 1
        )[0]
        self.assertIn("python-version: ['3.10', '3.13']", portable)
        self.assertIn("python-version: ${{ matrix.python-version }}", portable)
        self.assertIn("run: python -m pytest -q tests", portable)
        self.assertIn("run: python -m compileall -q src scripts setup tests", portable)
        self.assertIn("fail-fast: false", portable)
        self.assertIn("SMOOTHCAST_TEST_CONTEXT: '1'", workflow)
        self.assertNotIn("test_gui_isolated.py", portable)

    def test_setup_unittest_is_distinct_and_gtk_smoke_opt_in(self):
        workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
        setup = workflow.split("  setup-contract:", 1)[1]
        self.assertIn("unittest discover -s tests -p", setup)
        self.assertIn("test_setup_bootstrap.py", setup)
        guide = (ROOT / "README.md").read_text("utf-8")
        self.assertIn("Python **3.10**", guide)
        self.assertIn("Python **3.13**", guide)
        self.assertIn("python3 scripts/test_gui_isolated.py", guide)
        self.assertIn("never uses the desktop's", guide)


if __name__ == "__main__":
    unittest.main()
