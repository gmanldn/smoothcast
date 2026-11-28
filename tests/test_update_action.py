import pytest

import update_action as ua


def fake_git(**answers):
    def run(repo, args, timeout=30):
        key = " ".join(args)
        for k, v in answers.items():
            if key.startswith(k.replace("_", " ")):
                return v
        return ""
    return run


def runner(tmp_path, **kw):
    g = kw.pop("git", None) or fake_git(rev_parse__is_inside_work_tree="true")
    return ua.UpdateRunner(tmp_path, git=g, **kw)


def git_table(behind="2", branch="develop", dirty="", fetch="", merge=""):
    def run(repo, args, timeout=30):
        a = " ".join(args)
        table = {"rev-parse --is-inside-work-tree": "true", "rev-parse --abbrev-ref HEAD": branch,
                 "status --porcelain": dirty, "fetch --quiet origin develop": fetch,
                 "rev-list --count HEAD..origin/develop": behind,
                 "merge --ff-only origin/develop": merge}
        return table.get(a)
    return run


def test_available_then_apply_restarts(tmp_path):
    log = []
    r = ua.UpdateRunner(tmp_path, git=git_table(), relaunch=lambda: log.append("relaunch") or True,
                        quit_app=lambda: log.append("quit"))
    assert r.check()["can_update"] and r.snapshot()["behind"] == 2
    assert r.apply()["ok"] and log == ["relaunch", "quit"] and r.state == "restarting"


def test_up_to_date_and_dirty_checkout_never_offer_update(tmp_path):
    assert not ua.UpdateRunner(tmp_path, git=git_table(behind="0")).check()["can_update"]
    r = ua.UpdateRunner(tmp_path, git=git_table(dirty=" M x"))
    snap = r.check()
    assert not snap["can_update"] and "local changes" in snap["message"]
    assert "not on the develop" in ua.UpdateRunner(tmp_path, git=git_table(branch="topic")).check()["message"]


@pytest.mark.parametrize("behind", [None, "", "unknown", "-1"])
def test_unreadable_remote_comparison_is_a_failure_not_up_to_date(tmp_path, behind):
    r = ua.UpdateRunner(tmp_path, git=git_table(behind=behind))
    snapshot = r.check()
    assert snapshot["state"] == "failed"
    assert not snapshot["can_update"]
    assert "Could not confirm which build is latest" in snapshot["message"]
    assert not r.apply()["ok"]


def test_playing_requires_confirmation(tmp_path):
    r = ua.UpdateRunner(tmp_path, git=git_table(), busy=lambda: True, relaunch=lambda: True)
    r.check()
    first = r.apply()
    assert first["needs_confirmation"] and r.state == "available"
    assert r.apply(confirmed=True)["ok"]


def test_failures_are_reported_and_not_restarted(tmp_path):
    quits = []
    r = ua.UpdateRunner(tmp_path, git=git_table(fetch=None), quit_app=lambda: quits.append(1))
    assert r.check()["state"] == "failed"
    r = ua.UpdateRunner(tmp_path, git=git_table(merge=None), quit_app=lambda: quits.append(1))
    r.check()
    assert not r.apply()["ok"] and r.state == "failed" and not quits
    assert not ua.UpdateRunner(tmp_path, git=git_table()).apply()["ok"]


def test_relaunch_failure_does_not_quit(tmp_path):
    quits = []
    r = ua.UpdateRunner(tmp_path, git=git_table(), relaunch=lambda: False, quit_app=lambda: quits.append(1))
    r.check()
    assert not r.apply()["ok"] and not quits and "reopen" in r.message


def test_spawn_relaunch_needs_launcher(tmp_path):
    assert ua.spawn_relaunch(tmp_path) is False


def test_spawn_relaunch_detaches_through_canonical_launcher(tmp_path, monkeypatch):
    from pathlib import Path
    import sys

    launcher = tmp_path / "sc.py"
    launcher.write_text("# test launcher\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(ua.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert ua.spawn_relaunch(tmp_path, delay=0.25)
    assert len(calls) == 1
    args, options = calls[0]
    assert args[0] == ["sh", "-c", 'sleep 0.25; exec "$0" "$1"', sys.executable, str(launcher)]
    assert options["cwd"] == Path(tmp_path)
    assert options["start_new_session"] is True
    assert options["stdin"] is ua.subprocess.DEVNULL
    assert options["stdout"] is ua.subprocess.DEVNULL
    assert options["stderr"] is ua.subprocess.DEVNULL


def test_portal_page_has_update_button_and_routes():
    import portal
    import portal_update_http
    src = open(portal.__file__).read()
    assert 'id="updateBtn"' in src and "portal_update_http.route" in src
    assert portal_update_http.PATHS == {"/api/update"}


def test_dirty_or_off_branch_checkout_is_blocked_with_a_reason_not_silently_current(tmp_path):
    dirty = ua.UpdateRunner(tmp_path, git=git_table(dirty=" M x")).check()
    assert dirty["state"] == "blocked" and not dirty["can_update"]
    assert "local changes" in dirty["message"] and "stash" in dirty["message"]
    off = ua.UpdateRunner(tmp_path, git=git_table(branch="topic")).check()
    assert off["state"] == "blocked" and "not on the develop branch" in off["message"]


def test_installer_managed_copy_stays_quietly_current(tmp_path):
    def not_a_checkout(repo, args, timeout=30):
        return None
    snap = ua.UpdateRunner(tmp_path, git=not_a_checkout).check()
    assert snap["state"] == "current" and "installer" in snap["message"]


def test_blocked_checkout_recovers_when_the_tree_is_clean(tmp_path):
    state = {"dirty": " M x"}

    def run(repo, args, timeout=30):
        return git_table(dirty=state["dirty"])(repo, args, timeout)
    r = ua.UpdateRunner(tmp_path, git=run)
    assert r.check()["state"] == "blocked"
    state["dirty"] = ""
    assert r.check()["state"] == "available"
