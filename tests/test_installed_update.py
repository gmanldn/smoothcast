"""Offline coverage for cold-start develop updates."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

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
