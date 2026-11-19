"""Offline branch-deletion safety: never touch a real remote or network."""
from __future__ import annotations

from unittest import mock
import shutil
import subprocess

import pytest
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


def test_merged_branch_reused_by_open_pr_is_never_deleted():
    with mock.patch.object(cleanup, "run_git",
                           side_effect=AssertionError("remote read forbidden")):
        assert cleanup.prune(
            17, BRANCH, SHA, fetch=lambda n: pr(), git=cleanup.run_git,
            open_refs={(cleanup.REPOSITORY, BRANCH)}, apply=True,
        ).startswith("SKIP")
    assert "still used by another open PR" in cleanup.prune(
        17, BRANCH, SHA, fetch=lambda n: pr(),
        open_refs={(cleanup.REPOSITORY, BRANCH)}, apply=True,
    )


def test_inventory_rejection_is_fail_closed():
    with mock.patch.object(cleanup, "urlopen") as get:
        get.return_value.__enter__.return_value.read.return_value = b'{"bad":"shape"}'
        with pytest.raises(ValueError, match="inventory"):
            cleanup.github_open_pr_refs()


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
    assert len(cleanup.event_candidates("push", {})) == 32
    assert cleanup.event_candidates("schedule", {}) == ()


def test_backfill_is_fixed_merged_refs_only_and_excludes_protected():
    assert len(cleanup.BACKFILL) == 32
    assert len(set(number for number, _, _ in cleanup.BACKFILL)) == 32
    for number, name, sha in cleanup.BACKFILL:
        assert number > 0 and cleanup._safe_branch(name)
        assert cleanup.SHA.fullmatch(sha)


def test_main_defaults_to_dry_run_and_verifies_repository(monkeypatch, capsys):
    recorded = []
    monkeypatch.setattr(cleanup, "run_git",
                        lambda *args: "https://github.com/gmanldn/smoothcast.git\n")
    monkeypatch.setattr(cleanup, "github_open_pr_refs", lambda token: set())
    monkeypatch.setattr(cleanup, "prune",
                        lambda number, branch, sha, **kwargs:
                        recorded.append(kwargs["apply"]) or "READY sample")
    assert cleanup.main(["--event", "backfill"]) == 0
    assert recorded == [False] * 32
    assert capsys.readouterr().out.count("READY sample") == 32


def test_main_refuses_other_remote(monkeypatch):
    monkeypatch.setattr(cleanup, "run_git",
                        lambda *args: "https://github.com/someone/other.git")
    with __import__("pytest").raises(RuntimeError, match="expected repository"):
        cleanup.main(["--event", "backfill", "--apply"])


@pytest.mark.skipif(not shutil.which("git"), reason="Git unavailable")
def test_real_git_lease_deletes_only_exact_remote_sha(tmp_path):
    """A concurrent remote update must defeat the compare-and-delete lease."""
    remote, checkout = tmp_path / "remote.git", tmp_path / "checkout"

    def git(*args, ok=True):
        result = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True, text=True, timeout=15,
        )
        if ok:
            assert result.returncode == 0, result.stderr
        return result

    subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                   capture_output=True, timeout=15)
    subprocess.run(["git", "init", str(checkout)], check=True,
                   capture_output=True, timeout=15)
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("remote", "add", "origin", str(remote))
    source = checkout / "marker.txt"
    source.write_text("first", encoding="utf-8")
    git("add", "marker.txt")
    git("commit", "-m", "first")
    git("push", "origin", "HEAD:refs/heads/fix/example")
    first = git("ls-remote", "--heads", "origin", "refs/heads/fix/example").stdout.split()[0]
    assert cleanup.SHA.fullmatch(first)

    # Simulate another agent updating the ref between eligibility read and push.
    source.write_text("second", encoding="utf-8")
    git("commit", "-am", "second")
    git("push", "origin", "HEAD:refs/heads/fix/example")
    second = git("ls-remote", "--heads", "origin", "refs/heads/fix/example").stdout.split()[0]
    assert first != second
    ref = "refs/heads/fix/example"
    denied = git("push", "--porcelain", f"--force-with-lease={ref}:{first}",
                 "origin", f":{ref}", ok=False)
    assert denied.returncode != 0
    assert git("ls-remote", "--heads", "origin", ref).stdout.split()[0] == second

    # The *current* exact SHA may be deleted, and no unrelated refs touched.
    git("push", "--porcelain", f"--force-with-lease={ref}:{second}",
        "origin", f":{ref}")
    assert not git("ls-remote", "--heads", "origin", ref).stdout.strip()
