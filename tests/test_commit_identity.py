"""Canonical commit identity: committer date plus deterministic weapon alias."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import commit_identity
import version

COMMIT_DATE = "2026-11-09T23:30:00-05:00"


class CodenameTests(unittest.TestCase):
    def test_weapon_pool_is_unique(self):
        self.assertEqual(len(commit_identity.WEAPON_NAMES), 64)
        self.assertEqual(len(set(commit_identity.WEAPON_NAMES)), 64)

    def test_pinned_codenames_detect_algorithm_drift(self):
        self.assertEqual(commit_identity.codename("0" * 40), "Halberd-Flail")
        self.assertEqual(commit_identity.codename("a" * 40), "Mace-Tomahawk")
        self.assertEqual(commit_identity.codename("f" * 40), "Dirk-Talwar")
        self.assertEqual(
            commit_identity.codename("0123456789abcdef0123456789abcdef01234567"),
            "Kukri-Stiletto",
        )

    def test_codename_is_two_distinct_weapons(self):
        pool = commit_identity.WEAPON_NAMES
        for seed in ("0" * 40, "1" * 40, "a" * 40, "f" * 40,
                     "0123456789abcdef0123456789abcdef01234567"):
            with self.subTest(seed=seed):
                first, separator, second = commit_identity.codename(seed).partition("-")
                self.assertEqual(separator, "-")
                self.assertIn(first, pool)
                self.assertIn(second, pool)
                self.assertNotEqual(first, second)

    def test_codename_is_case_insensitive_and_stable(self):
        sha = "abcdef0123456789" + "1" * 24
        self.assertEqual(commit_identity.codename(sha),
                         commit_identity.codename(sha.upper()))
        self.assertEqual(commit_identity.codename(sha),
                         commit_identity.codename(sha))

    def test_invalid_revision_has_no_codename(self):
        for revision in (None, "", "abc", "a" * 39, "a" * 41, "g" * 40,
                         "a" * 63, "a" * 65):
            with self.subTest(revision=revision):
                self.assertIsNone(commit_identity.codename(revision))

    def test_display_label_omits_anything_not_proven(self):
        sha = "a" * 40
        word = commit_identity.codename(sha)
        self.assertEqual(
            commit_identity.display_label(version.label(), sha, "2026-11-09"),
            f"{version.label()} - 2026-11-09 - {word}")
        self.assertEqual(
            commit_identity.display_label(version.label(), sha, None),
            f"{version.label()} - {word}")
        self.assertEqual(
            commit_identity.display_label(version.label(), sha, "2026-13-40"),
            f"{version.label()} - {word}")
        self.assertEqual(
            commit_identity.display_label(version.label(), None, "2026-11-09"),
            version.label())

    def test_display_label_includes_zero_padded_time_and_rejects_bad_times(self):
        sha = "a" * 40
        word = commit_identity.codename(sha)
        self.assertEqual(commit_identity.display_label("v2.1.5", sha, "2026-11-26 0726"),
                         f"v2.1.5 - 2026-11-26 0726 - {word}")
        for bad in ("2026-11-26 2400", "2026-11-26 0760", "2026-11-26 726",
                    "2026-02-30 0726", "2026-11-26 07:26"):
            self.assertEqual(commit_identity.display_label("v2.1.5", sha, bad),
                             f"v2.1.5 - {word}")

    def test_running_identity_uses_frozen_revision_and_date(self):
        with mock.patch.object(version, "RUNNING_REVISION", "a" * 40), \
             mock.patch.object(version, "RUNNING_COMMIT_DATE", "2026-11-09 2330"):
            self.assertEqual(
                version.identity_label(),
                commit_identity.display_label(
                    version.label(), "a" * 40, "2026-11-09 2330"))


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class CommitDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        (self.root / "file.txt").write_text("data\n", encoding="utf-8")
        self.git("add", "file.txt")
        env = dict(os.environ, GIT_AUTHOR_DATE=COMMIT_DATE, GIT_COMMITTER_DATE=COMMIT_DATE)
        self.git("commit", "-qm", "initial", env=env)
        self.sha = self.git("rev-parse", "HEAD")

    def git(self, *args, env=None):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, env=env,
        ).strip()

    def test_loose_commit_date_uses_the_commit_timezone(self):
        self.assertEqual(version.read_checkout_revision(self.root), self.sha)
        self.assertTrue(
            (self.root / ".git" / "objects" / self.sha[:2] / self.sha[2:]).is_file())
        # 23:30-05:00 is already the next day in UTC; the commit's own date wins.
        self.assertEqual(version.read_checkout_commit_date(self.root), "2026-11-09 2330")
        self.assertEqual(version.read_checkout_commit_date(self.root, self.sha),
                         "2026-11-09 2330")

    def test_packed_commit_date_survives_repack(self):
        self.git("repack", "-adq")
        self.git("prune-packed")
        self.assertFalse(
            (self.root / ".git" / "objects" / self.sha[:2] / self.sha[2:]).exists())
        self.assertEqual(version.read_checkout_commit_date(self.root), "2026-11-09 2330")
        self.assertEqual(version.read_checkout_commit_date(self.root, self.sha),
                         "2026-11-09 2330")

    def test_missing_and_malformed_revisions_fail_closed(self):
        self.assertIsNone(version.read_checkout_commit_date(self.root, "0" * 40))
        self.assertIsNone(version.read_checkout_commit_date(self.root, "invalid"))
        self.assertIsNone(version.read_checkout_commit_date(self.root / "absent"))

    def test_malformed_commit_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sha = "a" * 40
            loose = root / ".git" / "objects" / sha[:2] / sha[2:]
            loose.parent.mkdir(parents=True)
            payload = (b"commit 999\0committer Test <t@example.invalid> "
                       b"not-a-timestamp +0000\n\nmessage\n")
            loose.write_bytes(zlib.compress(payload))
            self.assertIsNone(version.read_checkout_commit_date(root, sha))


class IdentityDocumentationTests(unittest.TestCase):
    def test_canonical_identity_is_documented_as_critical(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        release_flow = (ROOT / "docs" / "RELEASE_FLOW.md").read_text(encoding="utf-8")
        for text in (readme, release_flow):
            lowered = text.lower()
            self.assertIn("weapon", lowered)
            self.assertIn("committer date", lowered)
        self.assertIn("vX.Y.Z - YYYY-MM-DD HHMM - Codename", release_flow)


if __name__ == "__main__":
    unittest.main()