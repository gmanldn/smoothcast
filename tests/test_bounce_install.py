"""Bounce must verify the installed build rather than trust checkout HEAD."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location("bounce_install", Path(__file__).resolve().parents[1] / "bounce.py")
bounce = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bounce)
TARGET = "b" * 40


@pytest.mark.parametrize("state,ok,calls", [
    ("updated", True, 1), ("stale", False, 1), ("failed", False, 1),
    ("running", False, 0), ("managed_stale", False, 0), ("managed_current", True, 0),
])
def test_prepare_install_verifies_target(tmp_path, monkeypatch, state, ok, calls):
    source, installed = tmp_path / "source", tmp_path / "installed"
    active = installed / "releases" / TARGET
    revision = ["a" * 40]

    def refresh(root, destination, platform, running):
        assert (root, destination, platform) == (source, installed, "linux")
        assert not running()
        if state == "updated":
            revision[0] = TARGET
        return int(state == "failed")

    apply = Mock(side_effect=refresh)
    monkeypatch.setattr(bounce, "ROOT", source)
    monkeypatch.setattr(bounce, "_saved_playback", lambda: False)
    monkeypatch.setitem(sys.modules, "sc", SimpleNamespace(_target=lambda: "linux", _installed_root=lambda _: installed))
    monkeypatch.setitem(sys.modules, "launch", SimpleNamespace(gui_instances=lambda *, all_installations: [1] if state == "running" else []))
    monkeypatch.setitem(sys.modules, "checkout_refresh", SimpleNamespace(refresh=apply,
        installed_revision=lambda _: TARGET if state == "managed_current" else revision[0],
        read_version=lambda _: (2, 3, 248)))
    monkeypatch.setitem(sys.modules, "managed_startup", SimpleNamespace(activated=lambda _: state.startswith("managed"),
        active_launch=lambda _: (active / "python", active / "src" / "cast_control.py")))
    assert bounce._prepare_install(TARGET) is ok
    assert apply.call_count == calls


def test_running_checkout_does_not_claim_running_latest():
    _, message = bounce.decide(head=TARGET, target=TARGET, dirty=False, ancestor=True, running=True)
    assert "running build unverified" in message


def test_running_checks_other_installations(monkeypatch):
    scan = Mock(return_value=[42])
    monkeypatch.setitem(sys.modules, "launch", SimpleNamespace(gui_instances=scan))
    assert bounce._running()
    scan.assert_called_once_with(all_installations=True)
