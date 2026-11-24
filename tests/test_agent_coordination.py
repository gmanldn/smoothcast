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


def test_malformed_claim_ttl_is_conservative_bounded_and_nonfatal():
    """One malformed GitHub comment must not abort every agent pick/ship."""
    assert agent.safe_claim_ttl(None) == 90
    assert agent.safe_claim_ttl("garbled") == agent.TTL_MAX
    assert agent.safe_claim_ttl("9" * 5000) == agent.TTL_MAX
    assert agent.safe_claim_ttl("-999") == agent.TTL_MIN
    malformed = marker_comment(1, 10, 150, "misconfigured", ["src/x.py"])
    malformed["body"] = malformed["body"].replace("ttl=90", "ttl=not-a-number")
    live = claims(malformed)
    assert len(live) == 1 and live[0]["ttl"] == agent.TTL_MAX
    expired = marker_comment(2, 10, 190, "misconfigured", ["src/x.py"])
    expired["body"] = expired["body"].replace("ttl=90", "ttl=not-a-number")
    assert claims(expired) == []


def test_client_future_heartbeat_cannot_create_permanent_claim():
    stale = marker_comment(13, 584, 120, "clock-skewed", ["src/a.py"], ttl=90)
    future = int((NOW + timedelta(days=180)).timestamp())
    stale["body"] = stale["body"].replace(
        "beat=" + str(int((NOW - timedelta(minutes=120)).timestamp())),
        f"beat={future}"
    )
    assert claims(stale) == []  # GitHub created_at wins over client beat.

    renewed = dict(stale, updated_at=iso(2))
    assert [x["agent"] for x in claims(renewed)] == ["clock-skewed"]

    published_release = comment(
        14, 584, 5, "Released\n<!-- sc-release v1 agent=clock-skewed -->")
    assert claims(renewed, published_release) == []  # Comment-ID order wins.


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


def test_existing_task_lease_fences_other_issue_claiming_same_production_file(monkeypatch):
    # The issue-local ledger alone cannot reveal another ticket's source claim.
    mine = marker_comment(21, 584, 3, "ours", ["src/streaming.py"])
    rival = marker_comment(22, 810, 1, "other", ["src/streaming.py"])
    monkeypatch.setattr(agent, "gh", lambda *args: [mine])
    monkeypatch.setattr(agent, "recent_comments", lambda *args: [rival])
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    assert not agent.ensure_live_task_claim(
        {"issue": 584, "files": ["src/streaming.py"]})


def test_existing_task_lease_allows_independent_other_issue(monkeypatch):
    mine = marker_comment(21, 584, 3, "ours", ["src/streaming.py"])
    unrelated = marker_comment(22, 810, 1, "other", ["src/portal.py"])
    monkeypatch.setattr(agent, "gh", lambda *args: [mine])
    monkeypatch.setattr(agent, "recent_comments", lambda *args: [unrelated])
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    assert agent.ensure_live_task_claim({"issue": 584, "files": ["src/streaming.py"]})


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


def test_ranked_candidates_count_dependencies_in_later_or_icebox(monkeypatch):
    """An open prerequisite cannot vanish because its priority tier differs."""
    ready = {"number": 100, "title": "[P1] Work now", "state": "open",
             "labels": [{"name": "now"}], "body": "Depends on #900"}
    prerequisite = {"number": 900, "title": "[P3] Waiting", "state": "open",
                    "labels": [{"name": "icebox"}], "body": ""}
    monkeypatch.setattr(agent, "gh", lambda *args: [ready, prerequisite])
    monkeypatch.setattr(agent, "recent_comments", lambda: [])
    monkeypatch.setattr(agent, "hot_files", lambda: set())
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    args = agent.build_parser().parse_args(["next"])
    ranked, skipped, _, _, _ = agent.ranked_candidates(args)
    assert not skipped
    assert len(ranked) == 1
    assert ranked[0][1] == 100 and ranked[0][4] == (900,)


def test_open_issue_snapshot_paginates_and_refuses_incomplete_data(monkeypatch):
    import pytest

    first_page = [
        {"number": i, "title": "[P3] Deferred", "state": "open",
         "labels": [{"name": "icebox"}], "body": ""}
        for i in range(1, 101)
    ]
    selected = {"number": 150, "title": "[P1] Work", "state": "open",
                "labels": [{"name": "now"}], "body": "Depends on #1"}
    def pages(*args):
        return first_page if args[0].endswith("per_page=100") else [selected]

    monkeypatch.setattr(agent, "gh", pages)
    pool, open_nums = agent.all_open_issue_pool({"now", "next"})
    assert list(pool) == [150]
    assert {1, 100, 150} <= open_nums
    monkeypatch.setattr(agent, "gh", lambda *args: first_page)
    with pytest.raises(agent.td.DigestError, match="incomplete dependency detection"):
        agent.all_open_issue_pool({"now"}, max_pages=2)
    monkeypatch.setattr(agent, "gh", lambda *args: None)
    with pytest.raises(agent.td.DigestError, match="complete open issue list"):
        agent.all_open_issue_pool({"now"})


def test_start_refuses_automatic_selection_of_blocked_ticket(monkeypatch):
    args = agent.build_parser().parse_args(["start"])
    ticket = {"title": "[P0] Blocked", "body": "Depends on #9"}
    monkeypatch.setattr(agent, "git", lambda *args, **kw: "")
    monkeypatch.setattr(agent, "ranked_candidates",
                        lambda args: ([(1000, 42, ticket, set(), (9,))], [], [], set(), "ours"))
    monkeypatch.setattr(agent, "cmd_claim", lambda *args: (_ for _ in ()).throw(
        AssertionError("blocked ticket must not be claimed")))
    assert agent.cmd_start(args) == 3


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


def test_quiet_claim_feed_is_complete_not_an_error(monkeypatch):
    """An entirely quiet repository must still permit picking up work."""
    monkeypatch.setattr(agent, "gh", lambda *args: [])
    assert agent.recent_comments() == []


def test_recent_claim_feed_empty_second_page_is_complete(monkeypatch):
    comments = [marker_comment(i, i, 1, f"a{i}", ["src/x.py"]) for i in range(1, 101)]
    requested = []

    def fake_gh(*args):
        requested.append(args[0])
        return comments if "&page=1&" in args[0] else []

    monkeypatch.setattr(agent, "gh", fake_gh)
    assert len(agent.recent_comments(pages=2)) == 100
    assert len(requested) == 2


def test_recent_claim_feed_invalid_response_fails_closed(monkeypatch):
    import pytest
    monkeypatch.setattr(agent, "gh", lambda *args: None)
    with pytest.raises(agent.td.DigestError, match="invalid global claim feed"):
        agent.recent_comments()


def test_claim_withdraws_its_posted_comment_when_followup_read_fails(monkeypatch):
    """HTTP failure after POST must not strand a live ownership lease."""
    removed = []
    mine = marker_comment(55, 584, 0, "ours", ["src/a.py"])

    def fake_gh(*args):
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            return {"id": 55}
        if args[0].endswith("/comments?per_page=100"):
            raise agent.td.DigestError("GitHub read timed out")
        if args[:2] == ("-X", "DELETE"):
            removed.append(args[2])
            return {}
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "load_issue", lambda n: {"body": "edit src/a.py"})
    monkeypatch.setattr(agent, "recent_comments", lambda: [mine])
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)

    import pytest
    with pytest.raises(agent.td.DigestError, match="read timed out"):
        agent.cmd_claim(agent.build_parser().parse_args(["claim", "584"]))
    assert removed == [f"repos/{agent.REPO}/issues/comments/55"]


def test_closed_ticket_cannot_be_claimed_after_selection(monkeypatch):
    monkeypatch.setattr(agent, "load_issue", lambda n: {
        "state": "closed", "body": "edit src/a.py"})
    monkeypatch.setattr(agent, "agent_id", lambda: "worker")
    monkeypatch.setattr(agent, "gh", lambda *args: (_ for _ in ()).throw(
        AssertionError("must never publish a lease for a closed issue")))
    assert agent.cmd_claim(agent.build_parser().parse_args(["claim", "584"])) == 3


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
        if args[0].endswith("/comments?per_page=100"):
            return list(feed)
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


def test_comment_ledger_paginates_and_detects_live_successor(monkeypatch):
    """A live claim beyond GitHub's first 100 comments must fence stale workers."""
    earlier = [comment(i, 584, 70, f"unrelated note {i}") for i in range(1, 101)]
    successor = marker_comment(101, 584, 5, "successor", ["src/a.py"])
    requested = []

    def fake_gh(*args):
        requested.append(args[0])
        if "/issues/comments?" in args[0]:
            return []  # Complete global feed; rival is in issue page 2.
        if args[0].endswith("/comments?per_page=100"):
            return earlier
        if args[0].endswith("/comments?per_page=100&page=2"):
            return [successor]
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    assert not agent.ensure_live_task_claim({"issue": 584, "files": ["src/a.py"]})
    assert len(requested) == 3  # Two issue pages and one global scan.
    assert any("page=2" in path for path in requested)
    assert any("/issues/comments?" in path for path in requested)


def test_comment_ledger_refuses_truncated_or_unavailable_history(monkeypatch):
    import pytest

    def saturated(*args):
        return [comment(i, 584, 1, "note") for i in range(1, 101)]

    monkeypatch.setattr(agent, "gh", saturated)
    with pytest.raises(agent.td.DigestError, match="incomplete lease history"):
        agent.issue_comments(584, max_pages=2)
    with pytest.raises(agent.td.DigestError, match="incomplete conflict check"):
        agent.recent_comments(pages=2)

    monkeypatch.setattr(agent, "gh", lambda *args: None)
    with pytest.raises(agent.td.DigestError, match="complete comments"):
        agent.issue_comments(584)


def test_claim_post_confirmation_rechecks_issue_even_when_global_feed_has_self(monkeypatch):
    """A busy repo can truncate a rival from the global feed; issue ledger wins."""
    earlier = marker_comment(9, 584, 2, "rival", ["src/a.py"])
    ours = marker_comment(10, 584, 0, "self", ["src/a.py"])
    removed = []

    def fake_gh(*args):
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            return {"id": 10}
        if args[0].endswith("/comments?per_page=100"):
            return [earlier, ours]
        if args[:2] == ("-X", "DELETE"):
            removed.append(args[2])
            return {}
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "self")
    monkeypatch.setattr(agent, "load_issue", lambda n: {"body": "edit src/a.py"})
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    monkeypatch.setattr(agent, "recent_comments", lambda: [ours])
    assert agent.cmd_claim(agent.build_parser().parse_args(["claim", "584"])) == 3
    assert removed == [f"repos/{agent.REPO}/issues/comments/10"]


def test_confirmed_claim_survives_advisory_label_failure(monkeypatch):
    """GitHub metadata 403 must not convert a real claim into a false failure."""
    mine = marker_comment(50, 584, 0, "ours", ["src/a.py"])
    calls = []

    def fake_recent():
        calls.append("recent")
        return [] if len(calls) == 1 else [mine]

    def fake_gh(*args):
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            return {"id": 50}
        if args[0].endswith("/comments?per_page=100"):
            return [mine]
        if args[:2] == ("-X", "POST") and args[2].endswith("/labels"):
            raise agent.td.DigestError("advisory labels 403")
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "recent_comments", fake_recent)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    monkeypatch.setattr(agent, "load_issue", lambda n: {"body": "edit src/a.py"})
    assert agent.cmd_claim(agent.build_parser().parse_args(["claim", "584"])) == 0


def test_release_confirmation_prevents_false_advisory_cleanup(monkeypatch):
    """When GitHub's comment read lags, keep advisory labels until visible."""
    posted = []

    def fake_gh(*args):
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            posted.append(args)
            return {"id": 87}
        if args[0].endswith("/comments?per_page=100"):
            return [marker_comment(23, 584, 1, "ours", ["src/a.py"])]
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must never delete labels before release is visible")))
    agent.release(584, "finish.")
    assert len(posted) == 1

    monkeypatch.setattr(agent, "gh", lambda *args: {})
    import pytest
    with pytest.raises(agent.td.DigestError, match="did not confirm release"):
        agent.release(584, "finish.")


def test_heartbeat_requires_server_confirmation(monkeypatch):
    claim = marker_comment(10, 584, 1, "ours", ["src/a.py"])

    def fake_gh(*args):
        if args[0].endswith("/comments?per_page=100"):
            return [claim]
        if args[:2] == ("-X", "PATCH"):
            return {}  # Unknown server outcome must not be accepted as refreshed.
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "utcnow", lambda: NOW)
    import pytest
    with pytest.raises(agent.td.DigestError, match="did not confirm heartbeat"):
        agent.cmd_heartbeat(agent.build_parser().parse_args(["heartbeat", "584"]))


def test_scope_expansion_fences_new_source_files_and_persists_metadata(monkeypatch, tmp_path):
    import json
    task = {"issue": 584, "files": ["src/first.py"]}
    acquired = []
    monkeypatch.setattr(agent, "cmd_claim",
                        lambda args: acquired.append(args) or 0)
    monkeypatch.setattr(agent, "git", lambda *args, **kwargs: str(tmp_path))
    assert agent.ensure_task_scope(
        task, ["src/first.py", "src/second.py", "tests/test_second.py"]
    )
    assert len(acquired) == 1
    assert acquired[0].number == 584
    assert acquired[0].files == "src/first.py,src/second.py"
    assert task["files"] == ["src/first.py", "src/second.py"]
    assert json.loads((tmp_path / "sc-agent-task.json").read_text())["files"] == task["files"]
    # No duplicate lease or work when a subsequent ship touches the same files.
    assert agent.ensure_task_scope(task, ["src/second.py"])
    assert len(acquired) == 1


def test_scope_expansion_collision_preserves_old_claim_and_worktree(monkeypatch, tmp_path):
    task = {"issue": 584, "files": ["src/first.py"]}
    monkeypatch.setattr(agent, "cmd_claim", lambda args: 3)
    monkeypatch.setattr(agent, "git", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("should not write private state after losing a claim")))
    assert agent.ensure_task_scope(task, ["src/first.py", "src/other.py"]) is False
    assert task["files"] == ["src/first.py"]
    assert not (tmp_path / "sc-agent-task.json").exists()


def test_scope_expansion_does_not_claim_merge_friendly_tests_or_docs(monkeypatch):
    monkeypatch.setattr(agent, "cmd_claim", lambda *args: (_ for _ in ()).throw(
        AssertionError("tests and docs are merge-friendly shared paths")))
    assert agent.ensure_task_scope(
        {"issue": 584, "files": []},
        ["tests/test_widget.py", "docs/COORDINATION.md", "pyproject.toml"]
    )


def test_plan_checks_runs_mypy_only_for_gated_modules(monkeypatch):
    monkeypatch.setattr(agent, "mypy_gated", lambda: {"src/gated.py"})
    (agent.ROOT / "src").mkdir(exist_ok=True)
    labels = [name for name, _ in agent.plan_checks(["src/cast_ui.py"], {})]
    assert "mypy" not in labels and "ruff" in labels
    monkeypatch.setattr(agent, "mypy_gated", lambda: {"src/cast_ui.py"})
    assert "mypy" in [name for name, _ in agent.plan_checks(["src/cast_ui.py"], {})]


def test_missing_optional_checker_returns_unverified_instead_of_crashing(monkeypatch):
    import subprocess

    check, reason = agent.run_headless_check(["smoothcast-does-not-exist-584"])
    assert check is None and "unavailable" in reason

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(agent.subprocess, "run", timed_out)
    check, reason = agent.run_headless_check(["pytest", "-q"], timeout=3)
    assert check is None and "exceeded 3s" in reason


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


def test_next_reads_paginated_history_not_stale_first_comment_page(monkeypatch, capsys):
    ticket = {"title": "[P1] Review transport", "priority": "P1", "labels": ["now"]}
    monkeypatch.setattr(agent, "ranked_candidates",
                        lambda args: ([(250, 42, ticket, set(), ())], [], [], set(), "ours"))
    old = [comment(i, 42, 70, "Progress: historical work\nHandover: stale") 
           for i in range(1, 101)]
    latest = comment(101, 42, 2, "Progress: just landed\nHandover: verify reconnect")
    fetched = []

    def fake_gh(*args):
        fetched.append(args[0])
        if args[0].endswith("comments?per_page=100"):
            return old
        if args[0].endswith("comments?per_page=100&page=2"):
            return [latest]
        raise AssertionError(args)

    monkeypatch.setattr(agent, "gh", fake_gh)
    assert agent.cmd_next(agent.build_parser().parse_args(["next"])) == 0
    out = capsys.readouterr().out
    assert "just landed" in out and "verify reconnect" in out
    assert "stale" not in out
    assert len(fetched) == 2


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


def test_legacy_done_close_refused_even_when_evidence_claims_success(monkeypatch):
    from argparse import Namespace
    monkeypatch.setattr(agent, "git", lambda *args: (_ for _ in ()).throw(
        AssertionError("closure must be rejected before Git operations")))
    monkeypatch.setattr(agent, "gh", lambda *args: (_ for _ in ()).throw(
        AssertionError("legacy done must never close an issue")))
    args = Namespace(number=584, why="completed", checklist="everything",
                     verification="100 tests passed", close=True)
    assert agent.cmd_done(args) == 2


def test_legacy_done_posts_evidence_without_releasing_successor(monkeypatch):
    from argparse import Namespace
    from types import SimpleNamespace

    monkeypatch.setattr(agent, "git", lambda *args, **kwargs:
                        "a" * 40 if args[0] == "rev-parse" else "src/a.py")
    monkeypatch.setattr(agent.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(agent, "ticket_commits", lambda number: ["a" * 40])
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    monkeypatch.setattr(agent, "issue_comments",
                        lambda number: [marker_comment(90, number, 1, "successor",
                                                       ["src/a.py"])])
    posted = []
    monkeypatch.setattr(agent, "gh", lambda *args: (
        posted.append(args) or {"id": 123}) if args[:2] == ("-X", "POST") else {})
    monkeypatch.setattr(agent, "release", lambda *args: (_ for _ in ()).throw(
        AssertionError("must never release another worker's claim")))
    args = Namespace(number=584, why="fixed retry", checklist="remaining hardware",
                     verification="not run (unverified)", close=False)
    assert agent.cmd_done(args) == 0
    assert len(posted) == 1
    assert "Implementation:" in posted[0][-1]


def test_legacy_done_never_releases_after_unconfirmed_handover(monkeypatch):
    from argparse import Namespace
    from types import SimpleNamespace
    import pytest

    monkeypatch.setattr(agent, "git", lambda *args, **kwargs:
                        "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(agent.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(agent, "ticket_commits", lambda number: ["a" * 40])
    monkeypatch.setattr(agent, "gh", lambda *args: {})
    monkeypatch.setattr(agent, "release", lambda *args: (_ for _ in ()).throw(
        AssertionError("unconfirmed report must not release ownership")))
    monkeypatch.setattr(agent, "issue_comments", lambda number: (_ for _ in ()).throw(
        AssertionError("do not check ownership after failed evidence post")))
    args = Namespace(number=584, why="partial", checklist="needs testing",
                     verification="not run (unverified)", close=False)
    with pytest.raises(agent.td.DigestError, match="did not confirm legacy handover"):
        agent.cmd_done(args)


def test_doc_guard_runs_the_tests_that_pin_changed_docs_and_workflows():
    tests = {"tests/test_quality_gates.py": 'read("AGENTS.md") and "verify.yml"',
             "tests/test_unrelated.py": "nothing here",
             "tests/test_complexity_budget.py": "", "tests/test_a11y_inventory.py": ""}
    steps = agent.doc_guard_steps(["AGENTS.md", ".github/workflows/verify.yml"], tests)
    assert len(steps) == 1 and steps[0][1][-1] == "tests/test_quality_gates.py"
    assert "tests/test_unrelated.py" not in steps[0][1]
    assert agent.doc_guard_steps(["src/widget.py", "tests/test_x.py"], tests) == []
    assert agent.doc_guard_steps(["docs/NOBODY_MENTIONS_ME.md"], tests) == []


def test_conflict_help_explains_ours_theirs_and_names_the_other_owner():
    live = claims(marker_comment(1, 77, 5, "a-other", ["AGENTS.md"]))
    text = agent.conflict_help(["AGENTS.md", "pyproject.toml"], live)
    assert "rebase aborted" in text and "`--ours` is origin/develop" in text
    assert "sync_pyproject.py" in text
    assert "#77 (a-other)" in text
    assert "Live claims" not in agent.conflict_help(["src/x.py"], live)
