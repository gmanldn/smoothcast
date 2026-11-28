"""The opt-in GUI behaviour harness (scripts/gui_checks.py): pure parts only.

The real GTK run needs Xvfb and is never started by pytest; here we pin its
protocol, scenario registry and safety refusals without importing GTK.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gui_checks


def test_parse_checks_reads_only_well_formed_check_lines():
    output = "noise\nCHECK|first-run|config has no device|PASS|''\nCHECK|first-run|x|FAIL|a|b detail\n" \
             "CHECK|bad|y|MAYBE|z\nCHECK|short\nSELFTEST OK\n"
    assert gui_checks.parse_checks(output) == [
        ("first-run", "config has no device", True, "''"),
        ("first-run", "x", False, "a|b detail"),
    ]
    assert gui_checks.parse_checks("") == []


def test_every_parent_scenario_exists_in_the_child_and_vice_versa():
    tree = ast.parse((ROOT / "scripts" / "gui_checks_child.py").read_text(encoding="utf-8"))
    child = next(n for n in tree.body if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "SCENARIOS" for t in n.targets))
    child_names = {k.value for k in child.value.keys}
    assert child_names == set(gui_checks.SCENARIOS)
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for value in child.value.values:
        assert value.id in functions


def test_the_harness_refuses_to_run_inside_pytest():
    assert os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1"
    assert gui_checks.main([]) == 2


def test_unknown_scenarios_are_rejected_before_anything_starts(monkeypatch):
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    monkeypatch.setattr(gui_checks.sys, "platform", "linux")      # the harness is Linux-only; pin it for every OS
    monkeypatch.setattr(gui_checks.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(gui_checks, "run_scenario", lambda name: (_ for _ in ()).throw(AssertionError("started")))
    assert gui_checks.main(["no-such-scenario"]) == 2


def test_missing_xvfb_is_a_safe_skip_not_a_fallback_to_the_desktop(monkeypatch, capsys):
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    monkeypatch.setattr(gui_checks.sys, "platform", "linux")
    monkeypatch.setattr(gui_checks.shutil, "which", lambda name: None)
    monkeypatch.setattr(gui_checks, "run_scenario", lambda name: (_ for _ in ()).throw(AssertionError("started")))
    assert gui_checks.main([]) == 2
    assert "never use your desktop DISPLAY" in capsys.readouterr().err


def test_child_refuses_without_the_isolated_session_and_patches_the_browser():
    child = (ROOT / "scripts" / "gui_checks_child.py").read_text(encoding="utf-8")
    assert "CheckApp(selftest=True)" in child                # the app itself enforces isolation
    assert "launch_default_for_uri = staticmethod(" in child        # no real browser is ever launched
    result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "gui_checks_child.py"), "first-run"],
                            cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={"PATH": os.environ.get("PATH", ""), "HOME": str(ROOT)})
    assert result.returncode != 0 and "CHECK|" not in result.stdout


def test_the_harness_declines_politely_on_other_platforms(monkeypatch, capsys):
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(gui_checks.sys, "platform", platform)
        assert gui_checks.main([]) == 2
        assert "Linux/Xvfb" in capsys.readouterr().err


def test_journey_wire_checks_accept_seek_as_message_or_restart():
    import gui_checks
    call = lambda t: ("ns", {"type": t})  # noqa: E731
    assert gui_checks.journey_wire_checks([call(t) for t in ("LOAD", "PAUSE", "SEEK", "STOP")])[0][2]
    # A transcode seek is a fresh LOAD at the new offset.
    assert gui_checks.journey_wire_checks(
        [call(t) for t in ("PING", "LOAD", "PAUSE", "LOAD", "PAUSE", "STOP")])[0][2]
    assert not gui_checks.journey_wire_checks([call(t) for t in ("LOAD", "PAUSE", "STOP")])[0][2]
    assert not gui_checks.journey_wire_checks([call("LOAD"), call("PAUSE")])[0][2]
    assert not gui_checks.journey_wire_checks([])[0][2]


def test_demo_target_survives_config_normalisation(tmp_path, monkeypatch):
    import json
    import pytest
    import demo_mode
    cfg = tmp_path / "cast-control"
    cfg.mkdir()
    (cfg / "config.json").write_text(json.dumps(
        {"cast_targets": [{"name": "SmoothCast Demo TV", "host": "127.0.0.1", "port": 4321}]}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(demo_mode.TARGET_ENV, raising=False)
    assert demo_mode.demo_target() == ("127.0.0.1", 4321, "SmoothCast Demo TV")
    (cfg / "config.json").write_text(json.dumps({"cast_targets": []}))  # the app rewrites it
    assert demo_mode.demo_target() == ("127.0.0.1", 4321, "SmoothCast Demo TV")
    monkeypatch.setenv(demo_mode.TARGET_ENV, "10.0.0.5\n8009\nLAN TV")
    with pytest.raises(demo_mode.DemoModeError):
        demo_mode.demo_target()
