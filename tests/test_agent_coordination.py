"""Agent coordination core: claims, conflicts, ranking, test selection (no network)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def comment(cid, issue, minutes_ago, body):
    return {"id": cid, "issue": issue, "created_at": iso(minutes_ago), "body": body}


def marker_comment(cid, issue, minutes_ago, who, files, ttl=90):
    return comment(cid, issue, minutes_ago, "Claim\n" + agent.claim_marker(who, files, ttl, (NOW - timedelta(minutes=minutes_ago)).timestamp()))


def claims(*comments):
    return agent.active_claims(agent.parse_events(list(comments)), NOW)


def test_structured_claim_is_live_until_ttl_then_expires():
    live = claims(marker_comment(1, 10, 20, "a1", ["src/x.py"], ttl=30))
    assert [(c["issue"], c["agent"]) for c in live] == [(10, "a1")]
    assert claims(marker_comment(1, 10, 40, "a1", ["src/x.py"], ttl=30)) == []


def test_release_marker_ends_only_that_agents_claim():
    release = comment(3, 10, 5, "Released\n<!-- sc-release v1 agent=a1 -->")
    live = claims(marker_comment(1, 10, 20, "a1", ["src/x.py"]),
                  marker_comment(2, 10, 19, "a2", ["src/y.py"]), release)
    assert [c["agent"] for c in live] == ["a2"]


def test_legacy_free_text_claims_and_releases_are_understood():
    text = "Claim: Claude on develop. Scope: `src/portal.py` and tests."
    live = claims(comment(1, 7, 10, text))
    assert live[0]["agent"] == "legacy" and "src/portal.py" in live[0]["files"]
    assert claims(comment(1, 7, 10, text), comment(2, 7, 5, "Work pushed. Claim released.")) == []
    assert claims(comment(1, 7, 50, text)) == []  # 45 min legacy lease
    assert claims(comment(1, 7, 3, "Claim released; first slice landed.")) == []


def test_conflicts_same_ticket_and_overlapping_files_but_not_shared_or_own():
    live = claims(marker_comment(1, 10, 5, "a1", ["src/a.py", "src/b.py"]))
    assert agent.conflicts(10, set(), "a2", live)
    assert agent.conflicts(11, {"src/b.py"}, "a2", live)
    assert not agent.conflicts(11, {"src/c.py"}, "a2", live)
    assert not agent.conflicts(10, {"src/a.py"}, "a1", live)  # my own claim never blocks me


def test_predicted_files_ignore_shared_docs_and_tests():
    body = "Edit `src/mesh_files.py`, tests/test_mesh_files.py, docs/MESH.md and pyproject.toml; also `portal.py`"
    assert agent.predicted_files(body) == {"src/mesh_files.py", "src/portal.py"}


def test_blockers_only_count_open_dependencies():
    assert agent.blockers("Depends on: #12, #15 and #99.", {12, 99}) == [12, 99]
    assert agent.blockers("no dependencies", {12}) == []


def issue(priority="P1", labels=()):
    return {"priority": priority, "labels": list(labels)}


def test_ranking_prefers_now_then_priority_ready_and_unfinished_work():
    now_p1 = agent.score(issue("P1", ["now", "agent-ready"]), set(), set(), False, 0)[0]
    next_p0 = agent.score(issue("P0", ["next"]), set(), set(), False, 0)[0]
    assert now_p1 > next_p0
    assert agent.score(issue("P1", ["now"]), set(), set(), False, 2)[0] > agent.score(issue("P1", ["now"]), set(), set(), False, 0)[0]
    assert agent.score(issue("P3", ["later"]), set(), set(), True, 0)[0] > 1000  # resume own claim first


def test_hot_files_demote_a_ticket_and_say_why():
    cold, _ = agent.score(issue(labels=["now"]), {"src/a.py"}, set(), False, 0)
    hot, why = agent.score(issue(labels=["now"]), {"src/a.py"}, {"src/a.py"}, False, 0)
    assert hot < cold and any("hot" in w for w in why)


def test_tests_for_selects_named_importing_and_ratchet_tests():
    tests = {"tests/test_widget.py": "x", "tests/test_other.py": "import widget\n", "tests/test_unrelated.py": "y",
             "tests/test_complexity_budget.py": "", "tests/test_a11y_inventory.py": "", "tests/test_no_silent_swallow.py": ""}
    got = agent.tests_for(["src/widget.py"], tests)
    assert "tests/test_widget.py" in got and "tests/test_other.py" in got
    assert "tests/test_unrelated.py" not in got and "tests/test_complexity_budget.py" in got
    assert agent.tests_for(["tests/test_unrelated.py"], tests) == ["tests/test_unrelated.py"]
    assert agent.tests_for(["README.md"], tests) == []


def test_claim_loses_race_to_earlier_claim_and_withdraws(monkeypatch):
    posted, deleted = [], []
    earlier = marker_comment(5, 42, 1, "other", ["src/a.py"])
    mine = {"id": 9}
    feed = [earlier]

    def fake_gh(*args):
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            posted.append(args)
            feed.append(marker_comment(9, 42, 0, "me", ["src/a.py"]))
            return mine
        if args[:2] == ("-X", "DELETE"):
            deleted.append(args[2])
        return None

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "me")
    monkeypatch.setattr(agent, "load_issue", lambda n: {"body": "touch `src/a.py`"})
    calls = {"n": 0}

    def fake_recent(*_a, **_k):
        calls["n"] += 1
        # first look: nothing yet (the rival posted a moment before our POST landed)
        return [] if calls["n"] == 1 else list(feed)

    monkeypatch.setattr(agent, "recent_comments", fake_recent)
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    args = agent.build_parser().parse_args(["claim", "42"])
    assert agent.cmd_claim(args) == 3
    assert posted and deleted and deleted[0].endswith("/comments/9")


def test_plan_checks_runs_mypy_only_for_gated_modules(monkeypatch):
    monkeypatch.setattr(agent, "mypy_gated", lambda: {"src/gated.py"})
    (agent.ROOT / "src").mkdir(exist_ok=True)
    labels = [name for name, _ in agent.plan_checks(["src/cast_ui.py"], {})]
    assert "mypy" not in labels and "ruff" in labels
    monkeypatch.setattr(agent, "mypy_gated", lambda: {"src/cast_ui.py"})
    assert "mypy" in [name for name, _ in agent.plan_checks(["src/cast_ui.py"], {})]


def test_failing_ids_parses_pytest_summary_and_ignores_noise():
    out = ("..F\nFAILED tests/test_a.py::test_x - AssertionError: boom\n"
           "ERROR tests/test_b.py::test_y\nFAILED tests/test_a.py::test_x - again\n3 failed")
    assert agent.failing_ids(out) == ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]
    assert agent.failing_ids("all passed") == []


def test_heartbeat_edit_cannot_resurrect_a_released_claim():
    # Heartbeat updates the old comment in place *after* the release was posted.
    # Its beat is now newer than release's timestamp, but its ID is older.
    old = marker_comment(1, 10, 30, "a1", ["src/a.py"])
    old["body"] = old["body"].replace(
        "beat=" + str(int((NOW - timedelta(minutes=30)).timestamp())),
        "beat=" + str(int((NOW - timedelta(minutes=1)).timestamp())),
    )
    released = comment(2, 10, 10, "Released\n<!-- sc-release v1 agent=a1 -->")
    assert claims(old, released) == []


def test_heartbeat_cannot_extend_expired_or_released_claim(monkeypatch):
    calls = []
    expired = marker_comment(1, 10, 120, "me", ["src/a.py"], ttl=90)
    released = marker_comment(2, 11, 20, "me", ["src/b.py"])
    release_event = comment(3, 11, 10, "Released\n<!-- sc-release v1 agent=me -->")
    def fake_gh(*args):
        calls.append(args)
        return [expired] if "/10/" in args[0] else [released, release_event]
    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "me")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    for number in (10, 11):
        assert agent.cmd_heartbeat(agent.build_parser().parse_args(["heartbeat", str(number)])) == 1
    assert not any(args[0] == "-X" for args in calls)


def test_unconfirmed_claim_is_withdrawn_without_assignee_or_label(monkeypatch):
    calls = []
    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            return {"id": 90}
        if args[0].endswith("/comments?per_page=100"):
            return []
        return None
    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "me")
    monkeypatch.setattr(agent, "load_issue", lambda n: {"body": "edit src/a.py"})
    monkeypatch.setattr(agent, "recent_comments", lambda: [])
    assert agent.cmd_claim(agent.build_parser().parse_args(["claim", "42"])) == 3
    assert any(args[:2] == ("-X", "DELETE") and args[2].endswith("/comments/90") for args in calls)
    assert not any("labels" in " ".join(args) or "assignees" in " ".join(args) for args in calls)


def test_mypy_file_selection_uses_python_310_standard_library():
    assert {"src/actions.py", "src/version.py"} <= agent.mypy_gated()


def test_close_issue_requires_explicit_rest_confirmation(monkeypatch):
    calls = []
    def ok(*args):
        calls.append(args)
        return {"state": "closed"}
    monkeypatch.setattr(agent, "gh", ok)
    agent.close_issue(42)
    assert calls == [("-X", "PATCH", "repos/gmanldn/smoothcast/issues/42",
                      "-f", "state=closed", "-f", "state_reason=completed")]
    monkeypatch.setattr(agent, "gh", lambda *_args: {"state": "open"})
    import pytest
    with pytest.raises(agent.td.DigestError, match="did not confirm"):
        agent.close_issue(42)


def test_history_preview_is_id_ordered_and_does_not_reuse_stale_handover():
    comments = [
        comment(4, 42, 2, "Implementation: abc5678. Why: final fix."),
        comment(1, 42, 30, "Implementation: abc1234. Why: first slice."),
        comment(3, 42, 10, "Progress: source tests passed\nHandover: fix cleanup"),
    ]
    slices, progress, handover = agent.summarize_history(comments)
    assert slices == 2
    assert progress == "abc5678. Why: final fix."
    assert handover == ""  # never pair older pending work with newer implementation


def test_history_preview_preserves_latest_progress_and_remaining_work():
    comments = [
        comment(1, 42, 20, "Progress: basic transport landed\nHandover: untested cancellation"),
        comment(2, 42, 10, "Claim released."),
        comment(3, 42, 3, "Progress: cancellation handling landed\nHandover: test receiver restart"),
    ]
    assert agent.summarize_history(comments) == (
        0, "cancellation handling landed", "test receiver restart"
    )


def test_progress_is_durable_and_optionally_releases_only_after_confirmation(monkeypatch):
    posted, released = [], []
    def fake_gh(*args):
        posted.append(args)
        return {"id": 1234}
    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "release", lambda n, note: released.append((n, note)))
    args = agent.build_parser().parse_args([
        "progress", "42", "--done", "guard landed", "--next", "receiver soak",
        "--commit", "abc123", "--verification", "pytest: 3 passed",
        "--files", "src/portal.py", "--release",
    ])
    assert agent.cmd_progress(args) == 0
    body = posted[0][-1]
    assert "Progress: guard landed" in body
    assert "Handover: receiver soak" in body
    assert "Commit: abc123" in body
    assert "Verification: pytest: 3 passed" in body
    assert released == [(42, "Handover recorded in comment 1234.")]


def test_progress_does_not_release_when_post_is_unconfirmed(monkeypatch):
    released = []
    monkeypatch.setattr(agent, "gh", lambda *args: {})
    monkeypatch.setattr(agent, "release", lambda *args: released.append(args))
    args = agent.build_parser().parse_args([
        "progress", "42", "--done", "investigation", "--next", "write fix", "--release"
    ])
    import pytest
    with pytest.raises(agent.td.DigestError, match="did not confirm"):
        agent.cmd_progress(args)
    assert released == []


def test_ticket_commits_requires_an_exact_issue_number(monkeypatch):
    calls = []
    def fake_git(*args):
        calls.append(args)
        return "a" * 40 + "\n" + "b" * 40 + "\n"
    monkeypatch.setattr(agent, "git", fake_git)
    assert agent.ticket_commits(511) == ["a" * 40, "b" * 40]
    assert calls == [("log", "--extended-regexp",
                      "--grep=(^|[^0-9])#511([^0-9]|$)", "--format=%H",
                      "origin/develop")]


def test_done_requires_a_published_ticket_commit_and_explicit_close_evidence(monkeypatch):
    from argparse import Namespace
    from types import SimpleNamespace
    monkeypatch.setattr(agent, "git", lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(agent.subprocess, "run", lambda *_args, **_kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(agent, "ticket_commits", lambda n: [])
    monkeypatch.setattr(agent, "gh", lambda *_args: (_ for _ in ()).throw(AssertionError("no API write")))
    monkeypatch.setattr(agent, "release", lambda *_args: (_ for _ in ()).throw(AssertionError("no release")))
    base = Namespace(number=511, why="reason", checklist="not done",
                     verification="not run (unverified)", close=False)
    assert agent.cmd_done(base) == 2  # no published commit for this exact issue
    base.close = True
    assert agent.cmd_done(base) == 2  # cannot close with default unverified evidence
