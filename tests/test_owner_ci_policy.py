"""Guard the owner's instant-develop / manual-main / lazy-CI policy.

No GitHub access, network, GTK, packages or subprocesses needed.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def triggers(text: str) -> str:
    """Top-level YAML on section, excluding comments and job-specific blocks."""
    match = re.search(r"(?m)^on:\n(.*?)(?=^[^\s#][^:]*:|\Z)", text, re.S | re.M)
    assert match, "workflow has no top-level event configuration"
    return match.group(1)


class OwnerCIPolicyTests(unittest.TestCase):
    def test_verify_only_runs_on_explicit_request(self):
        text = triggers(workflow("verify.yml"))
        self.assertIn("  workflow_dispatch:", text)
        self.assertNotIn("  push:", text)
        self.assertNotIn("  pull_request:", text)
        self.assertNotIn("  schedule:", text)

    def test_native_packages_are_never_built_for_develop_pushes(self):
        text = triggers(workflow("package.yml"))
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("  push:", text)
        self.assertIn("    tags: ['v*']", text)
        self.assertNotIn("    branches:", text)
        self.assertNotIn("  pull_request:", text)

    def test_weekly_codeql_is_not_per_commit(self):
        text = triggers(workflow("codeql.yml"))
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("  schedule:", text)
        self.assertNotIn("  push:", text)
        self.assertNotIn("  pull_request:", text)

    def test_portal_runs_only_for_safety_risks_and_full_gtk_is_deferred(self):
        text = workflow("portal-security.yml")
        events = triggers(text)
        self.assertIn("  workflow_dispatch:", events)
        self.assertIn("  pull_request:", events)
        self.assertIn("  push:", events)
        for path in ("src/portal.py", "src/portal_room.py",
                     "src/portal_commands.py", "src/portal_uploads.py"):
            self.assertIn(f"      - '{path}'", events)
        self.assertNotIn("src/design_tokens.py", events)
        self.assertRegex(text, r"(?m)^    if: github.event_name != 'push'$")
        self.assertIn("  cancel-in-progress: true", text)

    def test_no_scheduled_release_or_automatic_main_sync(self):
        text = triggers(workflow("sync-main.yml"))
        self.assertIn("  workflow_dispatch:", text)
        self.assertNotIn("  push:", text)
        self.assertNotIn("  pull_request:", text)
        verify = workflow("verify.yml")
        self.assertNotIn("gh pr merge", verify)
        self.assertNotIn("gh pr create", verify)
        self.assertNotIn("promote_release.py", verify)


if __name__ == "__main__":
    unittest.main()
