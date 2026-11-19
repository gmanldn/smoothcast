"""Issue #256: GitHub Actions must not execute movable third-party tags.

This offline contract scans all workflow YAML on every supported Python,
including workflows added by future PRs. No network or GH token is used.
"""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

USE_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(?:\s+#\s*(\S+))?\s*$")
IMMUTABLE_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
                              r"(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"v[0-9]+(?:\.[0-9]+)*\Z")


def test_workflows_pin_every_remote_action_to_sha_with_version_comment():
    files = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    assert files, "No GitHub Actions workflows found"
    checked = 0
    for path in files:
        content = path.read_text(encoding="utf-8")
        for number, line in enumerate(content.splitlines(), 1):
            match = USE_LINE.fullmatch(line)
            if not match:
                # Make this test fail when an author adds a comment/whitespace
                # variation that hides a 'uses:' directive from our regex.
                if re.search(r"^\s*(?:-\s*)?uses\s*:", line):
                    raise AssertionError(f"{path}:{number}: unreadable action reference")
                continue
            ref, documented_version = match.groups()
            if ref.startswith("./"):
                continue  # Local action is committed in this checkout.
            assert IMMUTABLE_ACTION.fullmatch(ref), (
                f"{path}:{number}: remote action is not pinned to a 40-char commit SHA: {ref}"
            )
            assert documented_version and VERSION_COMMENT.fullmatch(documented_version), (
                f"{path}:{number}: record original major/tag version as '# vN'"
            )
            checked += 1
    assert checked >= 15, "Expected action references from lint, setup and release workflows"


def test_codeql_init_and_analyze_share_the_same_audited_commit():
    content = (WORKFLOWS / "codeql.yml").read_text(encoding="utf-8")
    commits = re.findall(
        r"github/codeql-action/(?:init|analyze)@([0-9a-f]{40})", content
    )
    assert len(commits) == 2
    assert commits[0] == commits[1]


def test_dependabot_updates_github_actions_against_develop_weekly():
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    match = re.search(
        r"package-ecosystem:\s*['\"]?github-actions['\"]?"
        r"(?:(?!package-ecosystem:).)*?"
        r"target-branch:\s*develop"
        r"(?:(?!package-ecosystem:).)*?"
        r"interval:\s*weekly",
        config, re.DOTALL,
    )
    assert match is not None


def test_contract_detects_new_unpinned_tag_or_missing_version_comment(tmp_path, monkeypatch):
    sample = tmp_path / "new.yml"
    sample.write_text(
        "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
    )
    assert USE_LINE.fullmatch(sample.read_text().splitlines()[1]).group(1) == (
        "actions/checkout@v4"
    )
    assert IMMUTABLE_ACTION.fullmatch("actions/checkout@v4") is None
    assert VERSION_COMMENT.fullmatch("v4")
