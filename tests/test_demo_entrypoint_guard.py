"""Fail closed for unfinished demo from every entry point (Refs #523).

All probes are isolated: no GTK, setup, network or real media receiver is run.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import runpy
import sys
from types import ModuleType
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("args", [
    ["video.mkv", "--demo"],
    ["--demo=1"],
    ["--demo", "--portable"],
])
def test_canonical_launcher_refuses_before_bootstrap(args, capsys):
    launcher = runpy.run_path(str(ROOT / "sc.py"), run_name="demo-guard-test")
    fake_launch = ModuleType("launch")
    with mock.patch.dict(sys.modules, {"launch": fake_launch}):
        assert launcher["main"](args) == 2
    assert "no receiver was contacted" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["--demo"],
    ["--demo=ignored"],
    ["--action", "play", "--demo"],
])
def test_setup_launcher_refuses_before_runtime_probe(args, capsys):
    with mock.patch.object(sys, "path", [str(ROOT / "setup"), *sys.path]):
        launch = importlib.import_module("launch")
    with mock.patch.object(launch, "python_path", side_effect=AssertionError("runtime accessed")), \
         mock.patch.object(launch, "ensure_single_instance", side_effect=AssertionError("process scanned")):
        assert launch.main(args) == 2
    assert "No receiver was contacted" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["--demo"],
    ["--demo=fake"],
    ["cast", "--demo"],
    ["--version", "--demo"],
])
def test_internal_cli_refuses_before_frozen_dispatch_or_gtk(args, capsys):
    with mock.patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
        cli = importlib.import_module("cli")
        frozen = importlib.import_module("frozen_runtime")
    with mock.patch.object(frozen, "dispatch_frozen_helper",
                           side_effect=AssertionError("frozen helper executed")), \
         mock.patch.object(sys, "argv", ["smoothcast", *args]):
        assert cli._main() == 2
    assert "No receiver was contacted" in capsys.readouterr().err


def test_canonical_demo_never_hands_off_or_probes_single_instance(capsys):
    """Bare --demo must skip installed redirect and primary activation."""
    launcher = runpy.run_path(str(ROOT / "sc.py"), run_name="demo-guard-test")
    fake_launch = ModuleType("launch")
    fake_launch.runtime_ready = lambda: True
    fake_launch.python_path = lambda: Path("/venv/python")
    fake_launch.runtime_environment = lambda: {"PATH": "/bin"}
    fake_launch.ensure_single_instance = mock.Mock(side_effect=AssertionError("activated real app"))
    fake_launch.gui_instances = mock.Mock(side_effect=AssertionError("scanned real app"))
    demo_launch = ModuleType("demo_launch")
    demo_launch.run = mock.Mock(return_value=0)
    with mock.patch.dict(sys.modules, {"launch": fake_launch, "demo_launch": demo_launch}):
        assert launcher["main"](["--demo"]) == 0
    demo_launch.run.assert_called_once_with(["--demo"], "/venv/python", {"PATH": "/bin"})
