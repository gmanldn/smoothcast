"""End-to-end isolated git races for the private per-shipment PATCH allocator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/ci"))
import ship_patch


class PatchShipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / "origin.git"
        self.git(self.root, "init", "--bare", str(self.bare))
        self.worker1 = self.clone("one")
        (self.worker1 / "src").mkdir()
        (self.worker1 / "src/version.py").write_text(
            "MAJOR = 1\nMINOR = 2\nPATCH = 51\n", encoding="utf-8")
        self.git(self.worker1, "add", "src/version.py")
        self.git(self.worker1, "commit", "-m", "baseline")
        self.git(self.worker1, "branch", "-M", "develop")
        self.git(self.worker1, "push", "-u", "origin", "develop")
        self.worker2 = self.clone("two")
        self.git(self.worker2, "checkout", "-b", "develop", "origin/develop")

    @staticmethod
    def git(folder, *args):
        r = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(f"git {args} failed: {r.stderr}")
        return r.stdout.strip()

    def clone(self, name):
        directory = self.root / name
        self.git(self.root, "clone", str(self.bare), str(directory))
        self.git(directory, "config", "user.email", "test@example.invalid")
        self.git(directory, "config", "user.name", name)
        return directory

    def pending_code(self, worker, name):
        (worker / f"{name}.txt").write_text(name + "\n", encoding="utf-8")
        self.git(worker, "add", f"{name}.txt")
        self.git(worker, "commit", "-m", f"fix: {name}")

    def fetch(self, worker):
        self.git(worker, "fetch", "origin", "develop")
        return self.git(worker, "rev-parse", "origin/develop")

    def test_both_agents_ship_distinct_patches_without_lost_code(self):
        self.pending_code(self.worker1, "first")
        self.pending_code(self.worker2, "second")
        a = self.fetch(self.worker1)
        b = self.fetch(self.worker2)
        self.assertEqual(a, b)
        ship_patch.assign_private_patch(self.worker1, a, 583)
        ship_patch.assign_private_patch(self.worker2, b, 584)
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        rejected = subprocess.run(
            ["git", "push", "origin", "HEAD:develop"], cwd=self.worker2,
            capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        new_head = self.fetch(self.worker2)
        self.assertTrue(ship_patch.recover_private_patch(self.worker2, new_head))
        self.git(self.worker2, "rebase", "origin/develop")
        ship_patch.assign_private_patch(self.worker2, new_head, 584)
        self.git(self.worker2, "push", "origin", "HEAD:develop")
        self.assertEqual(self.git(self.worker2, "show", "HEAD:src/version.py").splitlines()[-1],
                         "PATCH = 53")
        self.assertEqual(self.git(self.worker2, "log", "--format=%s", "origin/develop").count(
            "[sc-auto-patch]"), 2)
        self.assertTrue((self.worker2 / "first.txt").exists())
        self.assertTrue((self.worker2 / "second.txt").exists())

    def test_same_issue_race_reuses_first_assignment_without_losing_code(self):
        self.pending_code(self.worker1, "first")
        self.pending_code(self.worker2, "second")
        a = self.fetch(self.worker1)
        b = self.fetch(self.worker2)
        first = ship_patch.assign_private_patch(self.worker1, a, 583)
        ship_patch.assign_private_patch(self.worker2, b, 583)
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        rejected = subprocess.run(
            ["git", "push", "origin", "HEAD:develop"], cwd=self.worker2,
            capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        remote = self.fetch(self.worker2)
        self.assertTrue(ship_patch.recover_private_patch(self.worker2, remote))
        self.git(self.worker2, "rebase", "origin/develop")
        self.assertIsNone(ship_patch.assign_private_patch(self.worker2, remote, 583))
        self.git(self.worker2, "push", "origin", "HEAD:develop")
        tip = self.fetch(self.worker2)
        self.assertEqual(ship_patch.published_assignment(self.worker2, tip, 583), first)
        self.assertEqual(ship_patch.parsed((self.worker2 / "src/version.py").read_text()),
                         (1, 2, 52))
        self.assertTrue((self.worker2 / "first.txt").exists())
        self.assertTrue((self.worker2 / "second.txt").exists())
        self.assertIsNone(ship_patch.published_assignment(self.worker2, tip, 58))

    def test_numbered_historical_subject_is_reused(self):
        remote = self.fetch(self.worker1)
        ship_patch.assign_private_patch(self.worker1, remote, 583)
        self.git(self.worker1, "commit", "--amend", "-m",
                 "chore(version): PATCH 1.2.52 for issue #583 [sc-auto-patch]")
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        remote = self.fetch(self.worker1)
        self.assertEqual(ship_patch.published_assignment(self.worker1, remote, 583), remote)
        self.assertIsNone(ship_patch.assign_private_patch(self.worker1, remote, 583))
        self.assertIsNone(ship_patch.published_assignment(self.worker1, remote, 58))
        self.assertEqual(ship_patch.parsed((self.worker1 / "src/version.py").read_text()),
                         (1, 2, 52))

    def test_numbered_subject_must_match_actual_version(self):
        remote = self.fetch(self.worker1)
        ship_patch.assign_private_patch(self.worker1, remote, 583)
        self.git(self.worker1, "commit", "--amend", "-m",
                 "chore(version): PATCH 1.2.99 for issue #583 [sc-auto-patch]")
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.published_assignment(self.worker1, self.fetch(self.worker1), 583)

    def test_published_marker_with_wrong_diff_fails_closed(self):
        self.pending_code(self.worker1, "not-a-version")
        self.git(self.worker1, "commit", "--amend", "-m",
                 "chore(version): PATCH for issue #583 [sc-auto-patch]")
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.published_assignment(self.worker1, self.fetch(self.worker1), 583)

    def test_never_drop_a_patch_already_on_remote_after_ack_loss(self):
        self.pending_code(self.worker1, "safe")
        remote = self.fetch(self.worker1)
        sha = ship_patch.assign_private_patch(self.worker1, remote, 583)
        self.git(self.worker1, "push", "origin", "HEAD:develop")
        self.assertFalse(ship_patch.recover_private_patch(self.worker1, self.fetch(self.worker1)))
        self.assertEqual(self.git(self.worker1, "rev-parse", "HEAD"), sha)
        self.assertIsNone(ship_patch.assign_private_patch(
            self.worker1, self.fetch(self.worker1), 583))

    def test_fail_closed_on_dirty_or_malformed_staged_state(self):
        self.pending_code(self.worker1, "safe")
        remote = self.fetch(self.worker1)
        (self.worker1 / "src/version.py").write_text("PATCH = 55\n", encoding="utf-8")
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.assign_private_patch(self.worker1, remote, 583)
        (self.worker1 / "src/version.py").write_text(
            "MAJOR = 1\nMINOR = 2\nPATCH = 51\n", encoding="utf-8")
        (self.worker1 / "scratch.txt").write_text("not staged\n", encoding="utf-8")
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.assign_private_patch(self.worker1, remote, 583)

    def test_explicit_valid_bump_does_not_double_increment(self):
        self.pending_code(self.worker1, "manual")
        p = self.worker1 / "src/version.py"
        p.write_text(ship_patch.patch_source(p.read_text()), encoding="utf-8")
        self.git(self.worker1, "add", "src/version.py")
        self.git(self.worker1, "commit", "-m", "chore: owner-approved bump")
        self.assertIsNone(ship_patch.assign_private_patch(
            self.worker1, self.fetch(self.worker1), 583))
        self.assertEqual(ship_patch.parsed(p.read_text()), (1, 2, 52))

    def test_patch_parser_and_bounds(self):
        self.assertEqual(ship_patch.parsed("MAJOR = 1\nMINOR = 2\nPATCH = 7\n"),
                         (1, 2, 7))
        self.assertIn("PATCH = 8", ship_patch.patch_source(
            "MAJOR = 1\nMINOR = 2\nPATCH = 7\n"))
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.parsed("MAJOR = 1\nPATCH = 7\n")
        with self.assertRaises(ship_patch.PatchAllocationError):
            ship_patch.patch_source("MAJOR = 1\nMINOR = 2\nPATCH = 2147483647\n")


if __name__ == "__main__":
    unittest.main()
