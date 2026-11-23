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

    def test_development_build_identity_preserves_package_semver(self):
        sha = "abcdef0123456789" + "1" * 24
        self.assertEqual(version.build_label(sha),
                         f"v{version.__version__}+g{sha[:12]}")
        self.assertEqual(version.build_label(None), version.label())
        self.assertEqual(version.build_label("invalid"), version.label())

    def test_build_id_cli_stays_headless_and_reports_checkout(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                   SMOOTHCAST_TEST_CONTEXT="1")
        expected = version.build_label(version.read_checkout_revision(ROOT))
        result = subprocess.run(
            [sys.executable, "-m", "cli", "--build-id"],
            env=env, text=True, capture_output=True, timeout=10, check=True,
        )
        self.assertEqual(result.stdout.strip(), f"SmoothCast {expected}")
        self.assertEqual(result.stderr.strip(), "")

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

    def test_checkout_revision_from_loose_and_detached_git_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitdir = root / ".git"
            branch = gitdir / "refs" / "heads" / "develop"
            branch.parent.mkdir(parents=True)
            branch.write_text("a" * 40 + "\n", encoding="ascii")
            (gitdir / "HEAD").write_text("ref: refs/heads/develop\n", encoding="ascii")
            self.assertEqual(version.read_checkout_revision(root), "a" * 40)
            (gitdir / "HEAD").write_text("B" * 40 + "\n", encoding="ascii")
            self.assertEqual(version.read_checkout_revision(root), "b" * 40)

    def test_checkout_revision_from_packed_refs_and_linked_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            worktree = root / "worktree"
            common = repo / ".git"
            internal = common / "worktrees" / "test1"
            internal.mkdir(parents=True)
            worktree.mkdir()
            (worktree / ".git").write_text(
                f"gitdir: {internal}\n", encoding="ascii"
            )
            (internal / "commondir").write_text("../..\n", encoding="ascii")
            (internal / "HEAD").write_text(
                "ref: refs/heads/develop\n", encoding="ascii"
            )
            (common / "packed-refs").write_text(
                "# pack-refs with: peeled\n" + "c" * 40
                + " refs/heads/develop\n" + "d" * 40
                + " refs/heads/main\n", encoding="ascii"
            )
            self.assertEqual(version.read_checkout_revision(worktree), "c" * 40)

    def test_checkout_revision_rejects_invalid_and_unbounded_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitdir = root / ".git"
            gitdir.mkdir()
            head = gitdir / "HEAD"
            for content in ("ref: refs/heads/../secret", "ref: refs/heads//develop",
                            "ref: refs/heads/../../outside", "not a ref",
                            "f" * 39, "x" * 2000):
                head.write_text(content, encoding="ascii")
                self.assertIsNone(version.read_checkout_revision(root), content)
            head.write_text("ref: refs/heads/develop\n", encoding="ascii")
            (gitdir / "packed-refs").write_text("c" * (2 * 1024 * 1024 + 5),
                                                encoding="ascii")
            self.assertIsNone(version.read_checkout_revision(root))
            self.assertIsNone(version.read_checkout_revision(root / "absent"))

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
        self.assertIn(' · restart to apply', source)
        self.assertIn(' · update information', source)

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
