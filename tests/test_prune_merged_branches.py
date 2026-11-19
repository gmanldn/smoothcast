"""Offline branch-deletion safety: never touch a real remote or network."""
from __future__ import annotations

from unittest import mock

from scripts.ci import prune_merged_branches as cleanup


SHA = "a" * 40
BRANCH = "fix/confirmed-merged"


def pr(*, merged=True, repo=cleanup.REPOSITORY, branch=BRANCH,
       sha=SHA, base="develop"):
    return {
        "merged_at": "2026-11-19T12:00:00Z" if merged else None,
        "merged": merged,
        "base": {"ref": base},
        "head": {"ref": branch, "sha": sha,
                 "repo": {"full_name": repo}},
    }


def git_fixture(*, sha=SHA, branch=BRANCH):
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == "ls-remote":
            return f"{sha}\trefs/heads/{branch}\n" if sha else ""
        if args[0] == "push":
            return "To github.com:... - [deleted]\n"
        raise AssertionError(args)
    return calls, run


def test_verified_merged_ref_is_dry_run_by_default():
    calls, git = git_fixture()
    result = cleanup.prune(17, BRANCH, SHA, fetch=lambda n: pr(), git=git)
    assert result.startswith("READY ")
    assert calls == [("ls-remote", "--heads", "origin", "refs/heads/" + BRANCH)]


def test_apply_uses_atomic_force_with_lease_and_no_shell():
    calls, git = git_fixture()
    result = cleanup.prune(17, BRANCH, SHA, fetch=lambda n: pr(), git=git, apply=True)
    assert result.startswith("DELETED ")
    assert calls[-1] == (
        "push", "--porcelain", f"--force-with-lease=refs/heads/{BRANCH}:{SHA}",
        "origin", f":refs/heads/{BRANCH}",
    )


def test_ref_advanced_after_merge_must_never_be_deleted():
    calls, git = git_fixture(sha="b" * 40)
    result = cleanup.prune(17, BRANCH, SHA, fetch=lambda n: pr(), git=git, apply=True)
    assert "advanced" in result
    assert not any(row[0] == "push" for row in calls)


def test_missing_remote_branch_is_harmless():
    calls, git = git_fixture(sha="")
    assert "already absent" in cleanup.prune(
        17, BRANCH, SHA, fetch=lambda n: pr(), git=git, apply=True)
    assert len(calls) == 1


def test_unmerged_fork_or_mismatched_head_never_runs_git():
    for payload in (
        pr(merged=False),
        pr(repo="another-user/smoothcast"),
        pr(branch="fix/unrelated"),
        pr(sha="b" * 40),
        pr(base="untrusted-branch"),
        {**pr(), "head": None},
    ):
        with mock.patch.object(cleanup, "run_git", side_effect=AssertionError("touching git")):
            result = cleanup.prune(17, BRANCH, SHA, fetch=lambda n, p=payload: p,
                                   git=cleanup.run_git, apply=True)
            assert result.startswith("SKIP")


def test_ref_validation_blocks_protected_and_injected_names_before_api():
    bad = ("main", "develop", "test", "release/v1", "refs/heads/main",
           "-bad", "a..b", "a//b", "foo.lock", "foo/", "a b", "x; rm -rf .")
    for name in bad:
        assert cleanup.prune(17, name, SHA,
                             fetch=lambda n: (_ for _ in ()).throw(AssertionError(name)),
                             apply=True).startswith("SKIP")
    assert cleanup.prune(True, BRANCH, SHA, apply=True).startswith("SKIP")
    assert cleanup.prune(17, BRANCH, "not-a-sha", apply=True).startswith("SKIP")


def test_closed_pr_event_only_accepts_merged_develop_source():
    good = {"pull_request": {**pr(), "number": 17}}
    assert cleanup.event_candidates("pull_request", good) == ((17, BRANCH, SHA),)
    for changed in (
        {"pull_request": {**pr(merged=False), "number": 17}},
        {"pull_request": {**pr(base="main"), "number": 17}},
        {},
    ):
        assert cleanup.event_candidates("pull_request", changed) == ()
    assert len(cleanup.event_candidates("push", {})) == 8
    assert cleanup.event_candidates("schedule", {}) == ()


def test_backfill_is_fixed_merged_refs_only_and_excludes_protected():
    assert len(cleanup.BACKFILL) == 8
    assert len(set(number for number, _, _ in cleanup.BACKFILL)) == 8
    for number, name, sha in cleanup.BACKFILL:
        assert number > 0 and cleanup._safe_branch(name)
        assert cleanup.SHA.fullmatch(sha)


def test_main_defaults_to_dry_run_and_verifies_repository(monkeypatch, capsys):
    recorded = []
    monkeypatch.setattr(cleanup, "run_git",
                        lambda *args: "https://github.com/gmanldn/smoothcast.git\n")
    monkeypatch.setattr(cleanup, "prune",
                        lambda number, branch, sha, **kwargs:
                        recorded.append(kwargs["apply"]) or "READY sample")
    assert cleanup.main(["--event", "backfill"]) == 0
    assert recorded == [False] * 8
    assert capsys.readouterr().out.count("READY sample") == 8


def test_main_refuses_other_remote(monkeypatch):
    monkeypatch.setattr(cleanup, "run_git",
                        lambda *args: "https://github.com/someone/other.git")
    with __import__("pytest").raises(RuntimeError, match="expected repository"):
        cleanup.main(["--event", "backfill", "--apply"])
