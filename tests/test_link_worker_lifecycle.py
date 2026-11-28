"""Real-process lifecycle of the isolated worker runner (#588); no network."""
from __future__ import annotations

import os
import time

import pytest

import link_acquisition as acquisition

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups")


@pytest.fixture(autouse=True)
def _small_quotas(monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_BYTES", 1024 * 1024)
    monkeypatch.setattr(acquisition, "FREE_RESERVE", 1024)


def _provider(tmp_path):
    launcher = tmp_path / "launcher"
    launcher.write_text('#!/bin/sh\nexec "$@"\n')
    launcher.chmod(0o700)
    provider = acquisition.CommandProvider(launcher=str(launcher))
    assert provider.launcher == str(launcher)
    return provider


def _work(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    return work


def _run(provider, tmp_path, script, *, cancelled=lambda: False, seconds=10):
    work = _work(tmp_path)
    deadline = time.monotonic() + seconds
    provider._run("/bin/sh", ["-c", script], work, cancelled, lambda d, t: None, deadline)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _gone(pid):
    for _ in range(40):
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_worker_crash_is_a_plain_failure(tmp_path):
    with pytest.raises(acquisition.LinkError) as err:
        _run(_provider(tmp_path), tmp_path, "exit 3")
    assert err.value.status == 502


def test_over_quota_stops_and_kills_the_whole_process_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "MAX_BYTES", 1024)
    pidfile = tmp_path / "child.pid"
    script = f"sleep 60 & echo $! > {pidfile}; head -c 4096 /dev/zero > blob; wait"
    with pytest.raises(acquisition.LinkError) as err:
        _run(_provider(tmp_path), tmp_path, script)
    assert err.value.status == 507
    assert _gone(int(pidfile.read_text()))


def test_deadline_stops_and_kills_the_whole_process_tree(tmp_path):
    pidfile = tmp_path / "child.pid"
    with pytest.raises(acquisition.LinkError) as err:
        _run(_provider(tmp_path), tmp_path, f"sleep 60 & echo $! > {pidfile}; wait", seconds=1)
    assert err.value.status == 504
    assert _gone(int(pidfile.read_text()))


def test_cancel_stops_and_kills_the_whole_process_tree(tmp_path):
    pidfile = tmp_path / "child.pid"
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 3 and pidfile.exists()

    with pytest.raises(acquisition.LinkError) as err:
        _run(_provider(tmp_path), tmp_path, f"sleep 60 & echo $! > {pidfile}; wait",
             cancelled=cancelled)
    assert err.value.status == 409
    assert _gone(int(pidfile.read_text()))
