"""CI burst-control contract: frequent develop pushes cannot flood runners (#539).

No PyYAML, GTK, runner, network or GitHub API is needed; exercise the workflow
contracts from checked-in source. The regular CI syntax job runs these tests.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
BURST = ("verify.yml", "portal-security.yml", "codeql.yml", "package.yml")


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def events(source: str) -> str:
    return source.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]


def event(source: str, name: str) -> str:
    """Read a top-level event mapping without loading PyYAML."""
    section = events(source)
    match = re.search(r"(?m)^  " + re.escape(name)
                      + r":(?:[^\n]*)\n(?P<body>(?:^(?!  [a-z_]+:)[^\n]*\n)*)",
                      section)
    if match is None:
        return ""
    return match.group("body")


def group(source: str) -> str:
    match = re.search(r"(?m)^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)\n",
                      source)
    if match is None:
        raise AssertionError("Missing explicit concurrency contract")
    if match.group(2) != "false":
        raise AssertionError("Active checks must finish, not be cancelled")
    return match.group(1)


class BurstCiWorkflowTests(unittest.TestCase):
    def test_every_expensive_workflow_keeps_only_latest_pending_per_ref(self):
        seen = set()
        for filename in BURST:
            with self.subTest(workflow=filename):
                text = workflow(filename)
                value = group(text)
                self.assertIn("github.ref", value)
                self.assertNotIn("github.sha", value)
                self.assertNotIn(value, seen, "different workflows must not cancel each other")
                seen.add(value)

    def test_only_contributor_prs_targeting_develop_trigger_expensive_checks(self):
        for filename in BURST:
            with self.subTest(workflow=filename):
                body = event(workflow(filename), "pull_request")
                self.assertIn("branches: [develop]", body)
                self.assertNotIn("branches: [main", body)

    def test_develop_pushes_keep_verify_and_security_scan(self):
        for filename in ("verify.yml", "portal-security.yml", "codeql.yml"):
            with self.subTest(workflow=filename):
                push = event(workflow(filename), "push")
                self.assertIn("develop", push)
        self.assertIn("main", event(workflow("verify.yml"), "push"))
        self.assertIn("main", event(workflow("codeql.yml"), "push"))
        self.assertIn("cron:", event(workflow("codeql.yml"), "schedule"))

    def test_packaging_push_filters_match_pr_filters_and_release_tags_still_build(self):
        source = workflow("package.yml")
        self.assertIn("workflow_dispatch:", events(source))
        pull_request = event(source, "pull_request")
        push = event(source, "push")
        self.assertIn("branches: [develop]", push)
        self.assertIn("tags: ['v*']", push)
        for name in ("'packaging/**'", "'src/frozen_*'", "'src/streamer.py'",
                     "'scripts/build_release.py'", "'pyproject.toml'"):
            self.assertIn(name, push)
        def patterns(block: str) -> list[str]:
            return re.findall(r"(?m)^      - ('[^']+')$", block)
        self.assertEqual(patterns(pull_request), patterns(push))
        self.assertGreater(len(patterns(push)), 5)

    def test_coalesced_develop_uses_release_baseline_for_full_lane(self):
        source = workflow("verify.yml")
        scope = source.split("  scope:\n", 1)[1].split("  syntax:\n", 1)[0]
        self.assertIn('"$GITHUB_REF" = "refs/heads/develop"', scope)
        self.assertIn('git fetch origin main', scope)
        self.assertIn('BASE="$(git rev-parse origin/main)"', scope)
        self.assertIn('test_scope.py --base "$BASE" --head "$GITHUB_SHA"', scope)
        # A cancelled intermediate version bump must not make the latest run fast.
        self.assertIn("test_scope.py", source)

    def test_release_stays_exact_sha_and_gated_on_every_verification_job(self):
        source = workflow("verify.yml")
        release = source.split("  promote-release:\n", 1)[1]
        self.assertIn("github.event_name == 'push'", release)
        self.assertIn("github.ref == 'refs/heads/develop'", release)
        self.assertIn('--match-head-commit "$GITHUB_SHA"', release)
        self.assertIn('git rev-parse origin/develop', release)
        self.assertIn("needs.mesh-protocol-contract.result == 'success'", release)
        self.assertIn("needs.syntax.result == 'success'", release)
        self.assertIn("needs.dependency-audit.result == 'success'", release)
        self.assertIn("cancel-in-progress: false", release)


if __name__ == "__main__":
    unittest.main()
