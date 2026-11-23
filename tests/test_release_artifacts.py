"""Tagged-release rules (issue #257): offline, GTK-free."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
import release_artifacts as ra  # noqa: E402

SCRIPT = ROOT / "scripts" / "ci" / "release_artifacts.py"


class TagTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "version.py"
        self.file.write_text("MAJOR = 2\nMINOR = 3\nPATCH = 4\n")

    def test_matching_tag_returns_bare_version(self):
        self.assertEqual(ra.check_tag("v2.3.4", self.file), "2.3.4")

    def test_mismatch_and_malformed_tags_are_rejected(self):
        for tag in ("v2.3.5", "2.3.4", "v2.3", "v2.3.4-rc1", "v2.3.4.1", "", "vx.y.z", "v02.3.4x"):
            with self.subTest(tag=tag), self.assertRaises(ra.ReleaseError):
                ra.check_tag(tag, self.file)

    def test_unreadable_version_file_is_rejected(self):
        self.file.write_text("raise SystemExit")
        with self.assertRaises(ra.ReleaseError):
            ra.check_tag("v2.3.4", self.file)

    def test_the_real_repository_version_is_taggable(self):
        self.assertEqual(ra.expected_tag(), "v" + ra.check_tag(ra.expected_tag()))

    def test_cli_exit_codes(self):
        good = subprocess.run([sys.executable, str(SCRIPT), "check-tag", ra.expected_tag()],
                              capture_output=True, text=True)
        bad = subprocess.run([sys.executable, str(SCRIPT), "check-tag", "v0.0.1"],
                             capture_output=True, text=True)
        self.assertEqual(good.returncode, 0)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("does not match", bad.stderr)


class ChecksumTests(unittest.TestCase):
    def test_sha256sums_matches_sha256sum_format_and_covers_both_artifacts(self):
        with tempfile.TemporaryDirectory() as work:
            dist = Path(work)
            (dist / "smoothcast-1.0.0.tar.gz").write_bytes(b"sdist")
            (dist / "smoothcast-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
            (dist / "notes.txt").write_text("ignored")
            lines = ra.checksums(dist).read_text().splitlines()
            self.assertEqual(lines, [
                f"{hashlib.sha256(b'wheel').hexdigest()}  smoothcast-1.0.0-py3-none-any.whl",
                f"{hashlib.sha256(b'sdist').hexdigest()}  smoothcast-1.0.0.tar.gz",
            ])

    def test_missing_wheel_or_sdist_refuses_to_checksum(self):
        with tempfile.TemporaryDirectory() as work:
            dist = Path(work)
            with self.assertRaises(ra.ReleaseError):
                ra.checksums(dist)
            (dist / "only.tar.gz").write_bytes(b"x")
            with self.assertRaises(ra.ReleaseError):
                ra.checksums(dist)


class NotesTests(unittest.TestCase):
    def test_notes_list_subjects_and_state_the_verification_limits(self):
        text = ra.notes("v1.2.3", "v1.2.2", subjects=["fix: a", "", "feat: b"])
        self.assertIn("# SmoothCast v1.2.3", text)
        self.assertIn("since v1.2.2", text)
        self.assertIn("- fix: a\n- feat: b", text)
        self.assertIn("sha256sum -c SHA256SUMS", text)
        self.assertIn("not native receiver", text)

    def test_empty_history_is_stated_not_blank(self):
        self.assertIn("No changes recorded", ra.notes("v1.0.0", subjects=[]))

    def test_notes_read_real_git_history_between_tags_without_merges(self):
        with tempfile.TemporaryDirectory() as work:
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

            def git(*args):
                subprocess.run(["git", *args], cwd=work, env=env, check=True,
                               capture_output=True)
            git("init", "-q")
            for index, subject in enumerate(("first", "second", "third")):
                Path(work, f"f{index}").write_text(subject)
                git("add", "-A")
                git("commit", "-q", "-m", subject)
                if subject == "first":
                    git("tag", "v0.0.1")
            with unittest.mock.patch.object(ra, "ROOT", Path(work)), \
                 unittest.mock.patch.dict(os.environ, env):
                text = ra.notes("v0.0.2", "v0.0.1", ref="HEAD")
            self.assertIn("- third\n- second", text)
            self.assertNotIn("first", text.split("Changes", 1)[1])


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/release.yml").read_text("utf-8")

    def test_tag_match_main_ancestry_and_checksums_are_enforced(self):
        for needle in ("release_artifacts.py check-tag", "merge-base --is-ancestor",
                       "release_artifacts.py checksums dist", "--verify-tag",
                       "python -m build", "verify_installed_artifact.py"):
            self.assertIn(needle, self.workflow)

    def test_default_is_a_dry_run_and_writes_only_for_the_release_job(self):
        self.assertIn("default: false", self.workflow)
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("if: env.PUBLISH == 'true'", self.workflow)
        self.assertNotIn("test_gui_isolated", self.workflow)

    def test_procedure_is_documented(self):
        doc = (ROOT / "docs/RELEASE_FLOW.md").read_text("utf-8")
        self.assertIn("owner", doc)       # main promotion is documented as an owner-only manual step


if __name__ == "__main__":
    unittest.main()
