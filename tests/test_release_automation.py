"""develop -> main promotion, version bump and branch guard (real temporary git repos)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
import bump_version as bv  # noqa: E402
import guard_branch as gb  # noqa: E402
import promote_release as pr  # noqa: E402

VERSION = "MAJOR = 1\nMINOR = 0\nPATCH = {}\n"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, env=ENV, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files: dict[str, str], message: str = "c") -> str:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")


class PromotionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(Path(tmp.name))
        self.repo.commit({"src/version.py": VERSION.format(1), "a.txt": "a"}, "release 1.0.1")
        self.repo.git("branch", "develop")
        self.repo.git("checkout", "-q", "develop")

    def decide(self, sha=None):
        return pr.decide(self.repo.path, sha or self.repo.git("rev-parse", "develop"), "main")

    def test_newer_version_on_develop_is_promoted_with_its_tag(self):
        self.repo.commit({"src/version.py": VERSION.format(2), "a.txt": "b"})
        self.assertEqual(self.decide(), "v1.0.2")

    def test_same_version_is_not_promoted(self):
        self.repo.commit({"a.txt": "more work, no release"})
        self.assertEqual(self.decide(), "")

    def test_older_version_is_never_promoted(self):
        self.repo.commit({"src/version.py": VERSION.format(0)})
        self.assertEqual(self.decide(), "")

    def test_version_comparison_is_numeric_not_textual(self):
        self.assertTrue(pr.needs_promotion((1, 0, 10), (1, 0, 9)))
        self.assertTrue(pr.needs_promotion((1, 10, 0), (1, 9, 99)))
        self.assertTrue(pr.needs_promotion((2, 0, 0), (1, 99, 99)))
        self.assertFalse(pr.needs_promotion((1, 0, 9), (1, 0, 9)))

    def test_main_that_only_holds_earlier_merge_commits_still_promotes(self):
        # The state after an earlier release: main = merge of an older develop.
        self.repo.commit({"src/version.py": VERSION.format(2), "a.txt": "x"}, "release 1.0.2")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge PR", "develop")
        self.repo.git("checkout", "-q", "develop")
        self.repo.commit({"src/version.py": VERSION.format(3), "a.txt": "y"}, "release 1.0.3")
        self.assertEqual(self.decide(), "v1.0.3")

    def test_hotfix_on_main_that_develop_lacks_is_refused(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.commit({"hotfix.txt": "only on main"}, "hotfix")
        self.repo.git("checkout", "-q", "develop")
        self.repo.commit({"src/version.py": VERSION.format(2)})
        with self.assertRaisesRegex(pr.PromoteError, "main holds changes"):
            self.decide()

    def test_conflicting_content_is_refused_not_merged(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.commit({"a.txt": "main edit"}, "main edit")
        self.repo.git("checkout", "-q", "develop")
        self.repo.commit({"src/version.py": VERSION.format(2), "a.txt": "develop edit"})
        with self.assertRaisesRegex(pr.PromoteError, "cannot merge cleanly"):
            self.decide()

    def test_unreadable_version_is_refused(self):
        self.repo.commit({"src/version.py": "raise SystemExit\n"})
        with self.assertRaises(pr.PromoteError):
            self.decide()

    def test_version_is_read_as_text_and_never_executed(self):
        evil = "import os\nos.system('exit 99')\n" + VERSION.format(7)
        self.assertEqual(pr.parse_version(evil), (1, 0, 7))

    def test_cli_exit_codes(self):
        self.repo.commit({"a.txt": "no release"})
        sha = self.repo.git("rev-parse", "HEAD")
        base = ["check", sha, "--main", "main", "--repo", str(self.repo.path)]
        self.assertEqual(pr.main(base), pr.NOTHING_TO_PROMOTE)
        self.repo.commit({"src/version.py": VERSION.format(2)})
        sha = self.repo.git("rev-parse", "HEAD")
        self.assertEqual(pr.main(["check", sha, "--main", "main", "--repo", str(self.repo.path)]), 0)
        self.assertEqual(pr.main(["check", "deadbeef", "--main", "main", "--repo", str(self.repo.path)]), 1)


class BumpTests(unittest.TestCase):
    SRC = '"""doc"""\nMAJOR = 1\nMINOR = 4\nPATCH = 9\n\n__version__ = f"{MAJOR}.{MINOR}.{PATCH}"\n'

    def test_patch_minor_major(self):
        self.assertEqual(bv.bump(self.SRC, "patch")[1], "1.4.10")
        self.assertEqual(bv.bump(self.SRC, "minor")[1], "1.5.0")
        self.assertEqual(bv.bump(self.SRC, "major")[1], "2.0.0")

    def test_only_the_three_assignments_change(self):
        text, _ = bv.bump(self.SRC, "patch")
        self.assertEqual(text, self.SRC.replace("PATCH = 9", "PATCH = 10"))

    def test_malformed_sources_are_rejected(self):
        for bad in ("MAJOR = 1\nMINOR = 2\n", self.SRC + "PATCH = 1\n", ""):
            with self.assertRaises(ValueError):
                bv.bump(bad)
        with self.assertRaises(ValueError):
            bv.bump(self.SRC, "huge")

    def test_cli_writes_the_file_and_dry_run_does_not(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "version.py"
            path.write_text(self.SRC)
            self.assertEqual(bv.main(["--dry-run", "--file", str(path)]), 0)
            self.assertEqual(path.read_text(), self.SRC)
            self.assertEqual(bv.main(["patch", "--file", str(path)]), 0)
            self.assertIn("PATCH = 10", path.read_text())

    def test_bumped_real_file_round_trips_through_the_release_tooling(self):
        text, version = bv.bump((ROOT / "src" / "version.py").read_text("utf-8"))
        self.assertEqual("v" + version, pr.label(pr.parse_version(text)))


class GuardTests(unittest.TestCase):
    def test_main_is_refused_but_develop_detached_and_other_branches_pass(self):
        with tempfile.TemporaryDirectory() as work:
            repo = Repo(Path(work))
            repo.commit({"f": "1"})
            self.assertEqual(gb.main([work]), 1)           # on main
            repo.git("checkout", "-q", "-b", "develop")
            self.assertEqual(gb.main([work]), 0)
            repo.git("checkout", "-q", "--detach")
            self.assertIsNone(gb.current_branch(Path(work)))
            self.assertEqual(gb.main([work]), 0)           # detached worktree flow

    def test_non_repository_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertEqual(gb.main([work]), 0)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
        self.job = self.workflow.split("  promote-release:", 1)[1]

    def test_promotion_runs_last_only_on_develop_and_needs_every_other_job(self):
        import re
        section = self.workflow.split("\njobs:\n", 1)[1]
        jobs = re.findall(r"^  ([a-z-]+):$", section, re.MULTILINE)
        self.assertEqual(jobs[-1], "promote-release")
        needs = self.job.split("needs: [", 1)[1].split("]", 1)[0].replace(" ", "").split(",")
        self.assertEqual(sorted(needs), sorted(jobs[:-1]))
        self.assertIn("github.ref == 'refs/heads/develop'", self.job)
        self.assertIn("github.event_name == 'push'", self.job)

    def test_merge_is_pinned_to_the_verified_commit_with_minimal_permissions(self):
        self.assertIn('--match-head-commit "$GITHUB_SHA"', self.job)
        self.assertIn("--merge", self.job)
        self.assertNotIn("--auto", self.job)       # repo auto-merge is disabled
        self.assertNotIn("--admin", self.job)      # never bypass the ruleset
        self.assertIn("contents: write", self.job)
        self.assertIn("pull-requests: write", self.job)
        self.assertIn("promote_release.py check", self.job)

    def test_setup_prerequisite_failure_explains_itself(self):
        # Seen on GitHub: "GitHub Actions is not permitted to create or approve
        # pull requests". The log must say which setting to enable.
        self.assertIn("::error title=Release promotion needs a repository setting::", self.job)
        self.assertIn("Allow GitHub Actions to create and approve pull requests", self.job)
        self.assertIn("::error title=Release promotion could not merge::", self.job)

    def test_nothing_else_in_ci_writes_to_main(self):
        for name in ("verify.yml", "codeql.yml", "release.yml", "prune-merged-branches.yml"):
            text = (ROOT / ".github/workflows" / name).read_text("utf-8")
            self.assertNotIn("push origin main", text, name)
            self.assertNotIn("git push origin HEAD:main", text, name)

    def test_precommit_guard_is_wired(self):
        config = (ROOT / ".pre-commit-config.yaml").read_text("utf-8")
        self.assertIn("scripts/ci/guard_branch.py", config)


if __name__ == "__main__":
    unittest.main()
