"""Agent pickup packet stays bounded while retaining completion instructions."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent


def test_large_issue_pickup_is_one_screen_and_keeps_checklist_and_latest_handover(monkeypatch):
    import agent_context
    monkeypatch.setattr(agent_context, "route_hint", lambda _paths: "docs/agents/workflow.md")
    body = ("Objective: fix the room.\n" + "Old context.\n" * 5000 +
            "Acceptance: all room commands fenced and civil.\n")
    comments = [
        {"id": 1, "body": "Progress: legacy work.\nHandover: old next step"},
        {"id": 2, "body": "Progress: modern fix done.\nHandover: check final receiver path"},
    ]
    packet = agent.issue_context_packet(584, {"title": "Scoped work", "body": body},
                                        comments, "a" * 40)
    assert len(packet) < 8600
    assert "Objective: fix the room." in packet
    assert "Acceptance: all room commands fenced" in packet
    assert "Handover: check final receiver path" in packet
    assert "Handover: old next step" not in packet
    assert "https://github.com/gmanldn/smoothcast/issues/584" in packet
    assert "background abbreviated" in packet


def test_short_issues_are_never_abbreviated(monkeypatch):
    import agent_context
    monkeypatch.setattr(agent_context, "route_hint", lambda _paths: "read source")
    body = "Implement #512. Files: src/errors.py. Tests: 3 failures."
    packet = agent.issue_context_packet(512, {"title": "Errors", "body": body},
                                        [], "f" * 40)
    assert body in packet
    assert "background abbreviated" not in packet
    assert "No prior handover" in packet
