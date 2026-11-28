"""Offline coverage for cold-start develop updates."""
from pathlib import Path
import os
import subprocess
import sys
from unittest.mock import ANY, Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import installed_update as updater

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/cmdline").is_file(), reason="Linux source refresh"
)
TIP = "b" * 40


@pytest.mark.parametrize("state", ["current", "signed", "unsigned", "offline", "moved"])
def test_only_pinned_signed_tip_reaches_installer(tmp_path, monkeypatch, state):
    monkeypatch.setattr(updater.checkout_refresh, "installed_revision",
                        lambda _: TIP if state == "current" else "a" * 40)
    apply = Mock(return_value=0)
    monkeypatch.setattr(updater.checkout_refresh, "refresh", apply)

    def git(repo, action, *args, timeout=30):
        assert repo.resolve() != tmp_path.resolve()
        if action == "ls-remote":
            assert args == ("--exit-code", updater.ORIGIN, updater.BRANCH)
            if state == "offline":
                raise subprocess.TimeoutExpired(action, timeout)
            return f"{TIP}\t{updater.BRANCH}"
        if action == "clone":
            assert "--no-checkout" in args
        if action == "rev-parse":
            return "c" * 40 if state == "moved" else TIP
        if action == "verify-commit" and state == "unsigned":
            raise subprocess.CalledProcessError(1, action)
        return ""

    command = Mock(side_effect=git)
    monkeypatch.setattr(updater, "_git", command)
    assert updater.refresh(tmp_path, "linux", lambda: []) == 0
    assert apply.call_count == (state == "signed")
    if state in {"current", "offline"}:
        command.assert_called_once()
    if state in {"unsigned", "moved"}:
        assert all("reset" not in call.args for call in command.call_args_list)


def test_current_remote_tip_is_reported_as_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.checkout_refresh, "installed_revision", lambda _: TIP)
    monkeypatch.setattr(updater, "_git", lambda _repo, *_args, **_kwargs:
                        f"{TIP}\t{updater.BRANCH}")
    monkeypatch.setenv(updater.LATEST_TIP_ENV, "")

    assert updater.refresh(tmp_path, "linux", lambda: []) == 0
    assert os.environ[updater.LATEST_TIP_ENV] == TIP


def test_unsigned_tip_uses_only_registered_local_checkout_at_pinned_tip(tmp_path, monkeypatch):
    source = tmp_path / "registered-source"
    revisions = iter(("a" * 40, TIP))
    monkeypatch.setattr(updater.checkout_refresh, "installed_revision", lambda _: next(revisions))
    monkeypatch.setattr(updater, "_local_source_at_tip", lambda _root, tip:
                        source if tip == TIP else None)
    apply = Mock(return_value=0)
    monkeypatch.setattr(updater.checkout_refresh, "refresh", apply)
    monkeypatch.setenv(updater.LATEST_TIP_ENV, "")

    def git(_repo, action, *args, timeout=30):
        if action == "ls-remote":
            return f"{TIP}\t{updater.BRANCH}"
        if action == "rev-parse":
            return TIP
        if action == "verify-commit":
            raise subprocess.CalledProcessError(1, action)
        if action == "tag":
            return ""
        return ""

    monkeypatch.setattr(updater, "_git", git)
    assert updater.refresh(tmp_path, "linux", lambda: []) == 0
    apply.assert_called_once_with(source, tmp_path, "linux", ANY, verified_tip=TIP)
    assert os.environ[updater.LATEST_TIP_ENV] == TIP


@pytest.mark.parametrize("state", ["valid", "dirty", "wrong-branch", "wrong-origin", "wrong-tip"])
def test_local_source_fallback_requires_exact_clean_official_develop_tip(
        tmp_path, monkeypatch, state):
    source = tmp_path / "checkout"
    installed = tmp_path / "installed"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "setup").mkdir()
    (source / "setup" / "bootstrap.py").write_text("", encoding="utf-8")
    (source / "pyproject.toml").write_text('name = "smoothcast"\n', encoding="utf-8")
    installed.mkdir()
    monkeypatch.setattr(updater.checkout_refresh.install_location, "_clean_source_revision",
                        lambda _source: "x" * 40 if state == "dirty" else TIP)

    def git(_repo, action, *_args, **_kwargs):
        if action == "symbolic-ref":
            return "main" if state == "wrong-branch" else "develop"
        if action == "remote":
            return "https://example.invalid/attacker/smoothcast.git" if state == "wrong-origin" else updater.ORIGIN
        if action == "rev-parse":
            return "c" * 40 if state == "wrong-tip" else TIP
        raise AssertionError(action)

    monkeypatch.setattr(updater, "_git", git)
    result = updater._source_at_tip(source, installed, TIP)
    assert (result == source) is (state == "valid")


def test_invoking_checkout_is_selected_without_using_the_callers_working_directory(
        tmp_path, monkeypatch):
    source = tmp_path / "checked-out-develop"
    monkeypatch.setenv("SMOOTHCAST_LAUNCH_SOURCE", str(source))
    monkeypatch.setattr(updater.checkout_refresh, "installed_source", lambda _root: None)
    monkeypatch.setattr(updater, "_source_at_tip", lambda candidate, _installed, _tip:
                        candidate if candidate == source else None)

    assert updater._local_source_at_tip(tmp_path / "installed", TIP) == source
    assert "SMOOTHCAST_LAUNCH_SOURCE" not in os.environ
