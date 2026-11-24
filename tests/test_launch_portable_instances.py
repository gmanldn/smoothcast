"""macOS/Windows running-instance detection without /proc or a session bus (#540)."""
from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import launch  # noqa: E402

APP = str((ROOT / "src" / "cast_control.py").resolve())
NO_PROC = Path("/definitely/not/a/proc")


@pytest.mark.parametrize("exe", ["python", "python3", "python3.12", "pythonw.exe", "python.exe",
                                 "C:\\Users\\me\\AppData\\Python\\pythonw.exe",
                                 "/Applications/SmoothCast/.venv/bin/python3"])
def test_python_executables_on_every_platform_are_recognised(exe):
    assert launch.is_gui_python_command([exe, APP], APP)


@pytest.mark.parametrize("exe", ["notpython", "ffplay", "python-config.sh", "pythonista"])
def test_other_executables_are_not(exe):
    assert not launch.is_gui_python_command([exe, APP], APP)


def test_psutil_style_listing_finds_only_this_checkout():
    procs = [(4242, ["python3", APP]), (4243, ["python3", "/elsewhere/src/cast_control.py"]),
             (4244, ["ffplay", APP]), (999, ["python3", APP])]
    with mock.patch.object(launch, "_portable_processes", return_value=procs), \
         mock.patch.object(launch.os, "getpid", return_value=999):
        assert launch.gui_instances(NO_PROC) == [4242]


def test_flattened_ps_commands_with_spaces_in_paths():
    spaced = "/Users/me/My Apps/SmoothCast/src/cast_control.py"
    assert launch._flat_argv(f"/venv/bin/python {spaced}", spaced) == ["/venv/bin/python", spaced]
    assert launch._flat_argv(f"/venv/bin/python {spaced}x", spaced) is None  # no partial match
    assert launch._flat_argv(f"/venv/bin/pythonx{spaced}", spaced) is None
    procs = [(7, ["\0flat", f"/venv/bin/python {APP} film.mkv"]),
             (8, ["\0flat", f"/usr/bin/vim {APP}"])]
    with mock.patch.object(launch, "_portable_processes", return_value=procs):
        assert launch.gui_instances(NO_PROC) == [7]


def test_enumeration_failure_means_no_instance_never_a_false_block():
    # Hermetic: always scan the fake non-Linux root, never this host's real /proc
    # (a developer's own running SmoothCast must not turn this into a false block).
    real = launch.gui_instances
    with mock.patch.object(launch, "_portable_processes", return_value=[]), \
         mock.patch.object(launch, "gui_instances",
                           side_effect=lambda *_a, **kw: real(NO_PROC, **kw)):
        assert launch.gui_instances() == []
        assert launch.ensure_single_instance([]) is None


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_running_instance_without_session_bus_is_reported_not_duplicated(platform, capsys):
    with mock.patch.object(launch.sys, "platform", platform), \
         mock.patch.object(launch, "gui_instances", return_value=[4242]):
        assert launch.activate_existing() is None
        assert launch.ensure_single_instance([]) == 3
    assert "already running" in capsys.readouterr().err
