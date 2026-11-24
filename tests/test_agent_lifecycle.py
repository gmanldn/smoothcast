"""P0 multi-agent lifecycle: isolated worktrees, races and durable handovers.

All Git tests use temporary repositories. No GUI, Chromecast, network or
personal checkout is touched. The local bare remote models origin/develop.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agent

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def run(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def seed_git(tmp: Path) -> tuple[Path, Path, Path]:
    remote, seed = tmp / "remote.git", tmp / "seed"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    seed.mkdir()
    run(seed, "init", "-q")
    run(seed, "config", "user.email", "test@example.invalid")
    run(seed, "config", "user.name", "SmoothCast Test")
    run(seed, "checkout", "-qb", "develop")
    (seed / "src").mkdir()
    (seed / "scripts/ci").mkdir(parents=True)
    (seed / "src/version.py").write_text("MAJOR = 1\nMINOR = 2\nPATCH = 51\n")
    shutil.copy2(SOURCE_ROOT / "scripts/ci/check_version_history.py",
                 seed / "scripts/ci/check_version_history.py")
    (seed / "base.txt").write_text("base\n")
    run(seed, "add", ".")
    run(seed, "commit", "-qm", "baseline")
    run(seed, "remote", "add", "origin", str(remote))
    run(seed, "push", "-q", "-u", "origin", "develop")
    a, b = tmp / "agent-a", tmp / "agent-b"
    for name in (a, b):
        subprocess.run(["git", "clone", "-q", "-b", "develop", str(remote), str(name)],
                       check=True)
        run(name, "config", "user.email", "test@example.invalid")
        run(name, "config", "user.name", "SmoothCast Test")
    return remote, a, b


def commit(cwd: Path, filename: str, body: str) -> None:
    path = cwd / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    run(cwd, "add", filename)
    run(cwd, "commit", "-qm", f"test: {filename} (Refs #584)")


def test_issue_packet_is_bounded_and_keeps_last_handover():
    comments = [{"id": 1, "body": "Progress: old\nHandover: old"},
                {"id": 3, "body": "Progress: latest\nHandover: one remaining test"}]
    packet = agent.issue_context_packet(
        584, {"title": "Coordinator", "body": "Edit src/cli.py\n" + "x" * 40000},
        comments, "a" * 40,
    )
    assert "issue #584" in packet
    assert "src/cli.py" in packet
    assert "one remaining test" in packet
    assert "old\nHandover: old" not in packet
    assert len(packet) < 38000


def test_start_rolls_back_lease_if_worktree_creation_fails(monkeypatch, tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    monkeypatch.setattr(agent, "ROOT", repo)
    monkeypatch.setattr(agent, "git", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(agent, "load_issue", lambda n: {
        "title": "One", "body": "Edit src/cli.py", "state": "open"})
    monkeypatch.setattr(agent, "cmd_claim", lambda args: 0)
    released = []
    monkeypatch.setattr(agent, "release", lambda n, note: released.append(n))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stderr="cannot add worktree", stdout=""))
    args = agent.build_parser().parse_args(["start", "584"])
    assert agent.cmd_start(args) == 4
    assert released == [584]


def test_start_creates_distinct_agent_ids_and_scoped_briefs(monkeypatch, tmp_path):
    _, first, _ = seed_git(tmp_path)
    monkeypatch.setattr(agent, "ROOT", first)
    monkeypatch.setattr(agent, "cmd_claim", lambda args: 0)
    monkeypatch.setattr(agent, "load_issue", lambda n: {
        "title": "Ticket for both", "body": "Edit src/cli.py", "state": "open"})
    monkeypatch.setattr(agent, "gh", lambda *args: [])
    cmd = agent.build_parser().parse_args(["start", "584"])
    assert agent.cmd_start(cmd) == 0
    assert agent.cmd_start(cmd) == 0
    folders = sorted(tmp_path.glob("smoothcast-issue-584-*"))
    assert len(folders) == 2
    ids = []
    for worktree in folders:
        admin = Path(run(worktree, "rev-parse", "--absolute-git-dir"))
        ids.append((admin / "sc-agent-id").read_text().strip())
        packet = (admin / "sc-agent-brief.md").read_text()
        assert "Ticket for both" in packet
        assert "Context route:" in packet
        assert "src/cli.py" in packet
    assert ids[0] != ids[1]


def test_claim_freshness_rejects_rival_and_reclaims_expired(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(agent, "utcnow", lambda: now)
    monkeypatch.setattr(agent, "agent_id", lambda: "ours")
    def event(who, minutes_ago):
        when = now - timedelta(minutes=minutes_ago)
        return {"id": 19, "created_at": when.isoformat(),
                "body": agent.claim_marker(who, ["src/a.py"], 90, when.timestamp())}
    monkeypatch.setattr(agent, "gh", lambda *args: [event("rival", 5)])
    task = {"issue": 584, "files": ["src/a.py"]}
    assert agent.ensure_live_task_claim(task) is False
    reclaimed = []
    monkeypatch.setattr(agent, "gh", lambda *args: [event("rival", 120)])
    monkeypatch.setattr(agent, "cmd_claim", lambda args: reclaimed.append(args.number) or 0)
    assert agent.ensure_live_task_claim(task) is True
    assert reclaimed == [584]


def test_ship_patch_assignment_is_explicitly_opt_in():
    default = agent.build_parser().parse_args(["ship"])
    requested = agent.build_parser().parse_args(["ship", "--assign-patch"])
    assert default.assign_patch is False
    assert requested.assign_patch is True


def test_private_auto_commit_only_tracks_known_files(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    run(work, "init", "-q")
    run(work, "config", "user.email", "test@example.invalid")
    run(work, "config", "user.name", "SmoothCast Test")
    (work / "existing.py").write_text("a = 1\n")
    run(work, "add", ".")
    run(work, "commit", "-qm", "baseline")
    (work / "existing.py").write_text("a = 2\n")
    (work / "untracked.py").write_text("not_auto_staged = True\n")
    monkeypatch.setattr(agent, "ROOT", work)
    monkeypatch.setattr(agent, "private_task", lambda: {"issue": 584})
    a = argparse.Namespace(message="fix: small change", dry_run=False, files="")
    assert agent.commit_private_slice(a) == 0
    assert "Refs #584" in run(work, "log", "-1", "--format=%s")
    assert "existing.py" in run(work, "show", "--format=", "--name-only", "HEAD")
    assert "untracked.py" not in run(work, "show", "--format=", "--name-only", "HEAD")
    a.files = "untracked.py"
    a.message = "test: add source"
    assert agent.commit_private_slice(a) == 0
    assert "untracked.py" in run(work, "show", "--format=", "--name-only", "HEAD")
    a.files = "../danger.py"
    assert agent.commit_private_slice(a) == 2
    for unsafe in (":(glob)**/*.py", "*.py", "existing.py?", "."):
        a.files = unsafe
        assert agent.commit_private_slice(a) == 2
    (work / "entire_directory").mkdir()
    (work / "entire_directory" / "untracked.py").write_text("x = 3\n")
    a.files = "entire_directory"
    assert agent.commit_private_slice(a) == 2
    assert not (work / "entire_directory" / "untracked.py").is_symlink()
    assert "entire_directory/untracked.py" not in run(
        work, "show", "--format=", "--name-only", "HEAD")


def test_dry_run_cannot_create_auto_commit(monkeypatch):
    monkeypatch.setattr(agent, "private_task", lambda: {"issue": 584})
    a = argparse.Namespace(message="fix: code", dry_run=True, files="")
    assert agent.commit_private_slice(a) == 2


def test_ship_records_true_multiline_handover_only_once(monkeypatch):
    seen = []
    comments = []
    def gh(*args):
        if args[0].endswith("/comments?per_page=100"):
            return list(comments)
        if args[:2] == ("-X", "POST"):
            body = args[-1][5:]
            comments.append({"body": body})
            seen.append(body)
            return {"id": 12}
        raise AssertionError(args)
    monkeypatch.setattr(agent, "gh", gh)
    sha = "a" * 40
    assert agent.publish_ship_handover({"issue": 584}, sha, ["src/a.py"],
                                       "compile passed", "more tests") is True
    assert agent.publish_ship_handover({"issue": 584}, sha, ["src/a.py"],
                                       "compile passed", "more tests") is True
    assert len(seen) == 1
    assert "\nHandover: more tests\nCommit: " in seen[0]
    assert f"<!-- sc-ship v1 sha={sha} -->" in seen[0]


def test_failed_post_recovers_durable_handover_after_remote_push(monkeypatch, tmp_path):
    """A finished code push must remain attributable after GitHub comment failure."""
    _, first, _ = seed_git(tmp_path)
    monkeypatch.setattr(agent, "ROOT", first)
    sha = run(first, "rev-parse", "HEAD")
    task = {"issue": 584, "files": ["src/a.py"],
            "pending_handover": {"sha": sha, "files": ["src/a.py"],
                                 "verification": "tests: 4 passed",
                                 "next": "review startup"}}
    assert agent.persist_private_task(task)
    admin = Path(run(first, "rev-parse", "--absolute-git-dir"))
    assert (admin / "sc-agent-task.json").exists()
    calls = []
    def flaky_post(*args):
        calls.append(args)
        return len(calls) > 1
    monkeypatch.setattr(agent, "publish_ship_handover", flaky_post)
    assert not agent.recover_pending_handover(task)
    assert "pending_handover" in task
    assert agent.recover_pending_handover(task)
    assert "pending_handover" not in task
    assert "pending_handover" not in (admin / "sc-agent-task.json").read_text()
    assert len(calls) == 2
    assert calls[0][1] == sha and calls[1][1] == sha


def test_unpublished_receipt_is_not_reported_as_shipped(monkeypatch, tmp_path):
    _, first, _ = seed_git(tmp_path)
    monkeypatch.setattr(agent, "ROOT", first)
    commit(first, "unpublished.txt", "not delivered\n")
    task = {"issue": 584, "pending_handover": {
        "sha": run(first, "rev-parse", "HEAD"), "files": ["unpublished.txt"],
        "verification": "none", "next": "push"}}
    monkeypatch.setattr(agent, "publish_ship_handover", lambda *a: (_ for _ in ()).throw(
        AssertionError("must never report an unpublished SHA")))
    assert agent.recover_pending_handover(task) is False
    assert "pending_handover" in task


def test_push_success_handover_failure_is_partial_success_not_zero(monkeypatch, tmp_path):
    """The Git SHA is durable even if its issue comment has not landed."""
    _, _a, worker = seed_git(tmp_path)
    commit(worker, "worker.txt", "delivered code\n")
    monkeypatch.setattr(agent, "ROOT", worker)
    task = {"issue": 584, "files": []}
    monkeypatch.setattr(agent, "private_task", lambda: task)
    monkeypatch.setattr(agent, "gh", lambda *args: {"state": "open"})
    monkeypatch.setattr(agent, "ensure_live_task_claim", lambda task: True)
    monkeypatch.setattr(agent, "persist_private_task", lambda task: True)
    monkeypatch.setattr(agent, "publish_ship_handover", lambda *args: False)
    args = agent.build_parser().parse_args(["ship", "--skip-checks"])
    assert agent.cmd_ship(args) == 7
    assert run(worker, "rev-parse", "HEAD") == run(worker, "rev-parse", "origin/develop")
    assert task["pending_handover"]["sha"] == run(worker, "rev-parse", "HEAD")


def test_start_ship_finish_complete_headless_cycle(monkeypatch, tmp_path):
    """One real worktree/remote cycle, with only GitHub REST stubbed offline."""
    _, first, _worker = seed_git(tmp_path)
    monkeypatch.setattr(agent, "ROOT", first)
    monkeypatch.setattr(agent, "load_issue", lambda n: {
        "title": "Add a source module", "body": "Edit src/new_feature.py", "state": "open"})
    comments = []
    def fake_gh(*args):
        if args == ("user",):
            return {"login": "ci-agent"}
        if len(args) == 1 and args[0].endswith("/issues/584"):
            return {"state": "open"}
        if len(args) == 1 and "/issues/584/comments?per_page=100" in args[0]:
            return list(comments)
        if args[:2] == ("-X", "POST") and args[2].endswith("/comments"):
            cid = len(comments) + 1
            comments.append({
                "id": cid, "issue": 584,
                "created_at": agent.utcnow().isoformat(),
                "body": args[-1].removeprefix("body="),
            })
            return {"id": cid}
        if args[:2] == ("-X", "POST") and args[2].endswith(("/labels", "/assignees")):
            return {}
        raise AssertionError(f"unexpected GitHub operation: {args!r}")

    monkeypatch.setattr(agent, "gh", fake_gh)
    monkeypatch.setattr(agent, "recent_comments", lambda *args, **kwargs: list(comments))
    real_subprocess = subprocess.run
    def no_network(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_subprocess(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", no_network)

    assert agent.cmd_start(agent.build_parser().parse_args(["start", "584"])) == 0
    trees = list(tmp_path.glob("smoothcast-issue-584-*"))
    assert len(trees) == 1
    worktree = trees[0]
    monkeypatch.setattr(agent, "ROOT", worktree)
    (worktree / "src/new_feature.py").write_text("VALUE = 42\n", encoding="utf-8")
    ship = agent.build_parser().parse_args([
        "ship", "--message", "feat: add source", "--files", "src/new_feature.py",
        "--next", "Review acceptance", "--skip-checks"])
    assert agent.cmd_ship(ship) == 0
    commit_sha = run(worktree, "rev-parse", "HEAD")
    assert commit_sha == run(worktree, "rev-parse", "origin/develop")
    assert "Refs #584" in run(worktree, "log", "-1", "--format=%s")
    assert any("sc-ship v1 sha=" in c["body"] for c in comments)
    assert any("Commit: " + commit_sha in c["body"] for c in comments)

    finish = agent.build_parser().parse_args([
        "finish", "--done", "Source slice delivered", "--next", "More testing",
        "--verification", "not run (unverified)"])
    assert agent.cmd_finish(finish) == 0
    bodies = "\n".join(c["body"] for c in comments)
    assert "Handover: More testing" in bodies
    assert "<!-- sc-release v1" in bodies
    assert not agent.active_claims(agent.parse_events(comments), agent.utcnow())
    assert run(worktree, "show", "origin/develop:src/new_feature.py") == "VALUE = 42"
    # An agent cycle must never create or promote main.
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
        cwd=worktree).returncode != 0


def test_two_independent_agents_rebase_without_losing_a_commit(monkeypatch, tmp_path):
    _remote, a, b = seed_git(tmp_path)
    commit(b, "b.txt", "B\n")
    commit(a, "a.txt", "A\n")
    run(a, "push", "-q", "origin", "HEAD:develop")
    monkeypatch.setattr(agent, "ROOT", b)
    monkeypatch.setattr(agent, "private_task", lambda: None)
    args = agent.build_parser().parse_args(["ship", "--skip-checks"])
    assert agent.cmd_ship(args) == 0
    run(b, "fetch", "-q", "origin", "develop")
    assert (b / "a.txt").read_text() == "A\n"
    assert (b / "b.txt").read_text() == "B\n"
    history = run(b, "log", "origin/develop", "--format=%s")
    assert "a.txt" in history and "b.txt" in history


def test_lost_push_ack_is_not_a_failed_or_duplicated_commit(monkeypatch, tmp_path):
    _remote, _a, b = seed_git(tmp_path)
    commit(b, "b.txt", "B\n")
    monkeypatch.setattr(agent, "ROOT", b)
    monkeypatch.setattr(agent, "private_task", lambda: None)
    real_run = subprocess.run
    pushes = []
    def lost_ack(command, **kwargs):
        if command[:2] == ["git", "push"]:
            ok = real_run(command, **kwargs)
            assert ok.returncode == 0
            pushes.append(1)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="connection lost")
        return real_run(command, **kwargs)
    monkeypatch.setattr(agent.subprocess, "run", lost_ack)
    args = agent.build_parser().parse_args(["ship", "--skip-checks"])
    assert agent.cmd_ship(args) == 0
    assert len(pushes) == 1
    assert run(b, "rev-parse", "HEAD") == run(b, "rev-parse", "origin/develop")


def test_competing_push_retries_and_keeps_both_changes(monkeypatch, tmp_path):
    _remote, a, b = seed_git(tmp_path)
    commit(a, "a.txt", "A\n")
    commit(b, "b.txt", "B\n")
    monkeypatch.setattr(agent, "ROOT", b)
    monkeypatch.setattr(agent, "private_task", lambda: None)
    real_run = subprocess.run
    pushes = []
    def contest(command, **kwargs):
        if command[:2] == ["git", "push"]:
            pushes.append(1)
            if len(pushes) == 1:
                run(a, "push", "-q", "origin", "HEAD:develop")
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="non-fast-forward")
        return real_run(command, **kwargs)
    monkeypatch.setattr(agent.subprocess, "run", contest)
    args = agent.build_parser().parse_args(["ship", "--skip-checks"])
    assert agent.cmd_ship(args) == 0
    assert len(pushes) == 2
    assert (b / "a.txt").read_text() == "A\n"
    assert (b / "b.txt").read_text() == "B\n"


def test_invalid_version_jump_is_blocked_even_with_skip_checks(monkeypatch, tmp_path):
    _remote, _a, b = seed_git(tmp_path)
    commit(b, "src/version.py", "MAJOR = 1\nMINOR = 2\nPATCH = 53\n")
    monkeypatch.setattr(agent, "ROOT", b)
    monkeypatch.setattr(agent, "private_task", lambda: None)
    args = agent.build_parser().parse_args(["ship", "--skip-checks"])
    assert agent.cmd_ship(args) == 6
    assert run(b, "rev-parse", "HEAD") != run(b, "rev-parse", "origin/develop")


def test_finish_requires_closed_criteria_and_idempotently_posts(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "private_task", lambda: {"issue": 584})
    monkeypatch.setattr(agent, "ensure_live_task_claim", lambda task: True)
    monkeypatch.setattr(agent, "git", lambda *args, **kwargs: "" if args[0] == "status" else "a" * 40)
    monkeypatch.setattr(agent, "ticket_commits", lambda n: ["a" * 40])
    def fake_subprocess(args, **kwargs):
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            return SimpleNamespace(returncode=0)
        raise AssertionError(args)
    monkeypatch.setattr(agent.subprocess, "run", fake_subprocess)
    state = []
    def gh(*args):
        if args[0].endswith("/comments?per_page=100"):
            return [{"body": body} for body in state]
        if args[:2] == ("-X", "POST"):
            state.append(args[-1][5:])
            return {"id": len(state)}
        raise AssertionError(args)
    monkeypatch.setattr(agent, "gh", gh)
    released = []
    closed = []
    monkeypatch.setattr(agent, "release", lambda n, note: released.append(n))
    monkeypatch.setattr(agent, "close_issue", lambda n: closed.append(n))
    incomplete = agent.build_parser().parse_args(
        ["finish", "--done", "implementation", "--next", "still testing", "--close"])
    assert agent.cmd_finish(incomplete) == 2
    complete = agent.build_parser().parse_args(
        ["finish", "--done", "completed", "--next", "none",
         "--verification", "tests: 10 passed", "--checklist", "all criteria", "--close"])
    assert agent.cmd_finish(complete) == 0
    assert agent.cmd_finish(complete) == 0
    assert len(state) == 1
    assert closed == [584, 584]  # REST closure itself is idempotent
    assert released == [584, 584]
