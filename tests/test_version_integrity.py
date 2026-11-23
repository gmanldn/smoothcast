"""Canonical SmoothCast version verification; no GTK dependency."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui_source import combined_source

import version


class CanonicalVersionTests(unittest.TestCase):
    def test_single_semantic_version_source(self):
        self.assertEqual(
            version.__version__,
            f"{version.MAJOR}.{version.MINOR}.{version.PATCH}",
        )
        self.assertRegex(version.__version__, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(version.label(), f"v{version.__version__}")

    def test_package_metadata_matches_the_canonical_release(self):
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', metadata)
        self.assertIn('version = {attr = "version.__version__"}', metadata)
        self.assertNotRegex(metadata, r'(?m)^version\s*=\s*"\d+\.\d+\.\d+"')
        self.assertIn('smoothcast = "cli:main"', metadata)

    def test_on_disk_version_does_not_overwrite_running_version(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "version.py"
            filename.write_text(
                "MAJOR = 9\nMINOR = 8\nPATCH = 7\n", encoding="utf-8",
            )
            self.assertEqual(version.read_checkout_version(filename), "9.8.7")
            self.assertEqual(
                version.__version__,
                f"{version.MAJOR}.{version.MINOR}.{version.PATCH}",
            )

    def test_candidate_release_source_is_parsed_without_execution(self):
        source = (
            "MAJOR = 4\nMINOR = 5\nPATCH = 6\n"
            "raise AssertionError('untrusted source was executed')\n"
        )
        self.assertEqual(version.parse_version_text(source), "4.5.6")
        self.assertIsNone(version.parse_version_text("MAJOR = 1\nMINOR = True\nPATCH = 4\n"))
        self.assertIsNone(version.parse_version_text("def bad(:\n"))
        self.assertIsNone(version.parse_version_text("MAJOR = 1\nMINOR = 2\n"))

    def test_checkout_version_parsing_never_executes_arbitrary_code(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sentinel = folder / "should-not-exist"
            bad_file = folder / "version.py"
            bad_file.write_text(
                f"__import__('pathlib').Path({str(sentinel)!r}).touch()\n"
                "MAJOR = 1\nMINOR = 0\nPATCH = 99\n",
                encoding="utf-8",
            )
            self.assertEqual(version.read_checkout_version(bad_file), "1.0.99")
            self.assertFalse(sentinel.exists())
            bad_file.write_text("MAJOR = True\nMINOR = 0\nPATCH = 1\n")
            self.assertIsNone(version.read_checkout_version(bad_file))
            self.assertIsNone(version.read_checkout_version(folder / "absent.py"))

    def test_cli_version_bypasses_gtk_and_venv(self):
        # Portable test: no installed script, GTK or X11 is needed.
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run(
            [sys.executable, "-m", "cli", "--version"],
            env=env, text=True, capture_output=True, timeout=10,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), f"SmoothCast {version.label()}")
        self.assertFalse(result.stderr.strip())

    def test_python_module_cli_uses_the_same_release(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "version.py")],
            text=True, capture_output=True, timeout=10, check=True,
        )
        self.assertEqual(result.stdout.strip(), f"SmoothCast {version.label()}")

    def test_gtk_header_title_about_and_cli_share_the_module(self):
        source = combined_source()
        self.assertIn('self.set_title(f"{APP_NAME} {version.label()}")', source)
        self.assertIn('title=f"{APP_NAME} {version.label()}"', source)
        self.assertIn('version=version.__version__', source)
        self.assertIn('print(f"{APP_NAME} {version.label()}")', source)
        self.assertIn('window.update_notice = notice', source)
        self.assertIn('subtitle += " · restart to update"', source)

    def test_no_duplicated_current_release_in_agent_docs(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotRegex(agents, r"(?im)\bCurrent:\s*[`v]*\d+\.\d+\.\d+")
        self.assertIn("src/version.py", agents)
        self.assertIn("--version", agents)
        self.assertIn("Git commit SHA", agents)

    def test_diagnostics_document_actual_running_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("smoothcast --version", readme)
        self.assertIn("running version", readme.lower())


if __name__ == "__main__":
    unittest.main()
