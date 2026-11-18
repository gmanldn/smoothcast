"""Offline integrity and execution-gating tests for pinned Homebrew setup.

No actual Homebrew, Bash, network, sudo or GUI is started by these tests.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import bootstrap


FIXTURE = b"#!/bin/bash\n# reviewed fixture\nprintf 'safe'\n"


def accept_fixture():
    return mock.patch.object(
        bootstrap, "HOMEBREW_INSTALL_SHA256",
        hashlib.sha256(FIXTURE).hexdigest(),
    )


def test_pin_is_immutable_and_checksum_is_well_formed():
    assert re.fullmatch(r"[0-9a-f]{40}", bootstrap.HOMEBREW_INSTALL_COMMIT)
    assert re.fullmatch(r"[0-9a-f]{64}", bootstrap.HOMEBREW_INSTALL_SHA256)
    assert bootstrap.HOMEBREW_INSTALL_COMMIT in bootstrap.HOMEBREW_INSTALL_URL
    assert "/HEAD/" not in bootstrap.HOMEBREW_INSTALL_URL
    assert "raw.githubusercontent.com/Homebrew/install/" in bootstrap.HOMEBREW_INSTALL_URL


def test_download_accepts_exact_reviewed_fixture_and_has_size_cap():
    with accept_fixture(), mock.patch.object(
        bootstrap.urllib.request, "urlopen", return_value=io.BytesIO(FIXTURE)
    ) as urlopen:
        assert bootstrap.download_verified_homebrew() == FIXTURE
    assert urlopen.call_args.kwargs["timeout"] == 45


@pytest.mark.parametrize(
    "body", [FIXTURE[:-1], FIXTURE + b"altered", b"", b"unexpected shell script"],
)
def test_modified_truncated_empty_or_wrong_script_never_executes(body):
    with accept_fixture(), mock.patch.object(bootstrap, "find_brew", return_value=None), \
         mock.patch.object(bootstrap.urllib.request, "urlopen", return_value=io.BytesIO(body)), \
         mock.patch.object(bootstrap, "checked_run") as run:
        with pytest.raises(bootstrap.SetupError):
            bootstrap.install_macos(check=False)
        run.assert_not_called()


def test_size_limit_is_enforced_before_execution():
    with accept_fixture(), mock.patch.object(bootstrap, "find_brew", return_value=None), \
         mock.patch.object(bootstrap.urllib.request, "urlopen", return_value=io.BytesIO(
             b"x" * (bootstrap.HOMEBREW_INSTALL_MAX_BYTES + 1)
         )), mock.patch.object(bootstrap, "checked_run") as run:
        with pytest.raises(bootstrap.SetupError, match="exceeds safe"):
            bootstrap.install_macos(check=False)
        run.assert_not_called()


def test_unavailable_network_or_readonly_check_never_executes():
    with mock.patch.object(bootstrap, "find_brew", return_value=None), \
         mock.patch.object(bootstrap.urllib.request, "urlopen",
                           side_effect=OSError("offline")) as download, \
         mock.patch.object(bootstrap, "checked_run") as run:
        with pytest.raises(bootstrap.SetupError, match="download failed"):
            bootstrap.install_macos(check=False)
        with pytest.raises(bootstrap.SetupError, match="Homebrew not found"):
            bootstrap.install_macos(check=True)
        assert download.call_count == 1
        run.assert_not_called()


def test_validated_bytes_are_executed_as_staged_file_without_shell_c():
    launched = []
    def run(command, *, env=None, **kwargs):
        assert command[0] == "/bin/bash"
        assert len(command) == 2  # Never -c, a pipe, or curl substitution.
        path = Path(command[1])
        assert path.is_file()
        assert path.read_bytes() == FIXTURE
        assert env["NONINTERACTIVE"] == "1"
        launched.append(path)

    with accept_fixture(), \
         mock.patch.object(bootstrap, "find_brew",
                           side_effect=[None, "/opt/homebrew/bin/brew"]), \
         mock.patch.object(bootstrap.urllib.request, "urlopen",
                           return_value=io.BytesIO(FIXTURE)), \
         mock.patch.object(bootstrap, "checked_run", side_effect=run), \
         mock.patch.object(bootstrap.subprocess, "check_output",
                           return_value="/opt/homebrew\n"), \
         mock.patch.object(bootstrap, "check_tools", return_value=[]), \
         mock.patch.object(bootstrap, "python_ok", return_value=True), \
         mock.patch.object(bootstrap, "works", return_value=True), \
         mock.patch.object(bootstrap, "pick_runtime",
                           return_value=Path("/opt/homebrew/bin/python3")):
        selected, env = bootstrap.install_macos(check=False)
    assert str(selected) == "/opt/homebrew/bin/python3"
    assert env["PATH"].split(bootstrap.os.pathsep)[0] == "/opt/homebrew/bin"
    assert len(launched) == 1
    assert not launched[0].exists()  # Private staging is removed after execution.
