"""bounce.py decision table and no-mutation guarantees (#626). No GUI, no network."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location("bounce", Path(__file__).resolve().parents[1] / "bounce.py")
bounce = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bounce)

A, B = "a" * 40, "b" * 40


def plan(**kw):
    base = dict(head=A, target=B, dirty=False, ancestor=True, running=False)
    base.update(kw)
    return bounce.decide(**base)[0]


@pytest.mark.parametrize("kw,action", [
    ({}, "update"),
    ({"running": True}, "defer"),
    ({"target": A}, "start"),
    ({"target": A, "running": True}, "noop"),
    ({"target": A, "running": True, "restart": True}, "defer"),
    ({"dirty": True}, "refuse"),
    ({"dirty": None}, "refuse"),
    ({"ancestor": False}, "refuse"),
    ({"ancestor": None}, "refuse"),
    ({"head": None}, "refuse"),
    ({"target": None}, "refuse"),
])
def test_decision_table(kw, action):
    assert plan(**kw) == action


def test_running_primary_is_never_stopped():
    assert "waiting for the running SmoothCast" in bounce.decide(
        head=A, target=B, dirty=False, ancestor=True, running=True)[1]


def _git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def test_dry_run_changes_nothing_and_does_not_launch(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    monkeypatch.setattr(bounce, "ROOT", repo)
    monkeypatch.setattr(bounce, "_running", lambda: False)
    launched = []
    monkeypatch.setattr(bounce, "_launch", lambda: launched.append(1))
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert bounce.main(["--local", "--dry-run"]) == 0
    assert not launched
    assert head in subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)
    assert "starting SmoothCast" in capsys.readouterr().out


def test_offline_fetch_leaves_everything_alone(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    monkeypatch.setattr(bounce, "ROOT", repo)
    launched = []
    monkeypatch.setattr(bounce, "_launch", lambda: launched.append(1))
    assert bounce.main([]) == 1
    assert not launched
    assert "untouched" in capsys.readouterr().out
