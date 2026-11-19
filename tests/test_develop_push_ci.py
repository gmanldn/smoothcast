"""Every integration commit must be verified, not just release/main commits."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_develop_and_main_pushes_both_trigger_full_headless_verification():
    workflow = (ROOT / ".github/workflows/verify.yml").read_text("utf-8")
    assert "  push:\n    branches: [main, develop]\n" in workflow
    assert "  pull_request:" in workflow
    assert "SMOOTHCAST_TEST_CONTEXT: '1'" in workflow
    assert "python -m pytest -q tests" in workflow


def test_develop_integration_branch_is_canonical_in_agent_documentation():
    workflow = (ROOT / "docs/agents/workflow.md").read_text("utf-8")
    guide = (ROOT / "AGENTS.md").read_text("utf-8")
    assert "develop" in workflow
    assert "release" in workflow.lower()
    assert "develop" in guide
