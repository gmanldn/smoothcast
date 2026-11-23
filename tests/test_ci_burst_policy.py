"""CI burst-control contract: frequent develop pushes cannot flood runners (#539, #511).

Owner policy (#511, #579): Verify, CodeQL and packaging are opt-in/scheduled; only the
risk-scoped portal security check reacts to develop pushes. Main is never promoted.

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
    def test_every_expensive_workflow_keeps_one_group_per_ref(self):
        seen = set()
        for filename in BURST:
            with self.subTest(workflow=filename):
                match = re.search(r"(?m)^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)\n",
                                  workflow(filename))
                self.assertIsNotNone(match, "Missing explicit concurrency contract")
                value, cancel = match.group(1), match.group(2)
                self.assertIn("github.ref", value)
                self.assertNotIn("github.sha", value)
                self.assertNotIn(value, seen, "different workflows must not cancel each other")
                seen.add(value)
                # Only the cheap, risk-scoped portal check may drop a superseded run;
                # full verification, scans and packaging always finish.
                self.assertEqual(cancel, "true" if filename == "portal-security.yml" else "false")

    def test_only_the_portal_security_check_reacts_to_branch_pushes_and_prs(self):
        for filename in ("verify.yml", "codeql.yml", "package.yml"):
            with self.subTest(workflow=filename):
                self.assertEqual(event(workflow(filename), "pull_request"), "")
                self.assertNotIn("branches:", event(workflow(filename), "push"))
        portal = workflow("portal-security.yml")
        self.assertIn("branches: [develop]", event(portal, "push"))
        self.assertIn("branches: [develop]", event(portal, "pull_request"))
        self.assertNotIn("branches: [main", portal)

    def test_verify_is_manual_codeql_is_weekly_and_packaging_builds_release_tags(self):
        self.assertEqual(events(workflow("verify.yml")).strip(), "workflow_dispatch:")
        codeql = workflow("codeql.yml")
        self.assertIn("workflow_dispatch:", events(codeql))
        self.assertIn("cron:", event(codeql, "schedule"))
        self.assertEqual(event(codeql, "push"), "")
        package = workflow("package.yml")
        self.assertIn("workflow_dispatch:", events(package))
        self.assertIn("tags: ['v*']", event(package, "push"))

    def test_portal_security_push_filter_is_risk_scoped_and_matches_nothing_cosmetic(self):
        push = event(workflow("portal-security.yml"), "push")
        paths = re.findall(r"(?m)^      - ('[^']+')$", push)
        self.assertGreater(len(paths), 5)
        for name in ("'src/portal.py'", "'src/portal_commands.py'", "'src/portal_uploads.py'"):
            self.assertIn(name, paths)
        self.assertFalse([p for p in paths if p.startswith(("'docs/", "'README"))])

    def test_scope_never_reads_main_as_a_development_baseline(self):
        source = workflow("verify.yml")
        scope = source.split("  scope:\n", 1)[1].split("  syntax:\n", 1)[0]
        self.assertIn('test_scope.py --base "$BASE" --head "$GITHUB_SHA"', scope)
        self.assertNotIn("git fetch origin main", scope)
        self.assertNotIn("rev-parse origin/main", scope)

    def test_verify_cannot_promote_or_publish_main(self):
        source = workflow("verify.yml")
        self.assertNotIn("promote-release", source)
        self.assertNotIn("--match-head-commit", source)
        self.assertIn("contents: read", source.split("\njobs:", 1)[0])


if __name__ == "__main__":
    unittest.main()
