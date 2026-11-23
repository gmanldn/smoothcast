"""Patch pushes use the fast lane; MINOR/MAJOR bumps run the full matrix."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "smoothcast_test_scope", ROOT / "scripts" / "ci" / "test_scope.py"
)
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


def test_scope_job_selects_patch_fast_lane_and_minor_major_full_lane():
    workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
    assert "scripts/ci/test_scope.py --base" in workflow
    assert "needs.scope.outputs.lane == 'full'" in workflow
    assert "SMOOTHCAST_TEST_CONTEXT: '1'" in workflow
    assert "python -m pytest -q tests" in workflow
    for job in (
        "reliability-benchmark:", "portable-tests:", "portable-tests-native:",
        "media-integration:", "setup-contract:", "installed-artifact:",
        "search-performance:",
    ):
        match = re.search(
            rf"^  {re.escape(job)}(.*?)(?=^  [a-z])", workflow, re.MULTILINE | re.DOTALL
        )
        assert match is not None
        block = match.group(1)
        assert "needs: [scope]" in block
        assert "needs.scope.outputs.lane == 'full'" in block


def test_promotion_accepts_a_skipped_patch_lane_but_not_a_failure():
    workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
    promote = workflow.split("  promote-release:", 1)[1]
    assert "(needs.portable-tests.result == 'success' || needs.portable-tests.result == 'skipped')" in promote
    assert "needs.lint.result == 'success'" in promote
    assert "needs.syntax.result == 'success'" in promote
    assert "scope, syntax, reliability-benchmark, lint, typecheck" in promote
    assert "(needs.reliability-benchmark.result == 'success' || needs.reliability-benchmark.result == 'skipped')" in promote


def test_classifier_is_fast_for_patches_and_full_for_minor_or_major():
    assert scope.classify((1, 0, 63), (1, 0, 64)) == "fast"
    assert scope.classify((1, 0, 63), (1, 0, 63)) == "fast"
    assert scope.classify((1, 0, 63), (1, 1, 0)) == "full"
    assert scope.classify((1, 2, 9), (2, 0, 0)) == "full"
    assert scope.classify((1, 1, 0), (1, 1, 1)) == "fast"
    assert scope.classify(None, (1, 0, 64)) == "full"
    assert scope.classify((1, 0, 64), None) == "full"
    assert scope.classify((1, 0, 64), (1, 0, 63)) == "full"


def test_develop_integration_branch_is_canonical_in_agent_documentation():
    workflow = (ROOT / "docs/agents/workflow.md").read_text("utf-8")
    guide = (ROOT / "AGENTS.md").read_text("utf-8")
    assert "develop" in workflow
    assert "release" in workflow.lower()
    assert "develop" in guide
