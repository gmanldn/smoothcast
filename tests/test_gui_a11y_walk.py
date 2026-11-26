"""Headless contract for the AT-SPI walk and its isolation guard (#449); no GTK."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import gui_a11y_walk  # noqa: E402
import gui_test_safety  # noqa: E402
import selftest_hold  # noqa: E402


def _node(role, name, showing=True):
    return {"role": role, "name": name, "showing": showing}


def test_unnamed_showing_interactive_controls_are_reported():
    nodes = [_node("push button", "Play"), _node("push button", ""), _node("slider", "  "),
             _node("toggle button", "", showing=False), _node("label", ""), _node("panel", "")]
    bad = gui_a11y_walk.find_unnamed(nodes)
    assert [n["role"] for n in bad] == ["push button", "slider"]


def test_named_controls_pass():
    assert gui_a11y_walk.find_unnamed([_node("slider", "Volume"), _node("check box", "Auto-play")]) == []


def _env(tmp_path, bus=None, token="a" * 64):
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / ".smoothcast-gui-test-token").write_text(token, encoding="ascii")
    auth = tmp_path / "xauth"
    auth.write_text("x")
    env = {"SMOOTHCAST_GUI_TEST_ISOLATED": "1", "GDK_BACKEND": "x11", "DISPLAY": ":99",
           "XDG_CONFIG_HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path),
           "XDG_CACHE_HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(runtime),
           "XAUTHORITY": str(auth), "SMOOTHCAST_GUI_TEST_TOKEN": token}
    if bus:
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.format(runtime=runtime)
    return env


def test_guard_allows_only_the_private_walk_bus(tmp_path):
    name = gui_test_safety.PRIVATE_BUS_NAME
    assert gui_test_safety.is_isolated_gui_test(_env(tmp_path))
    assert gui_test_safety.is_isolated_gui_test(_env(tmp_path, "unix:path={runtime}/" + name))
    for hostile in ("unix:path=/run/user/1000/bus", "unix:path={runtime}/other",
                    "unix:abstract=/tmp/dbus-xyz", "unix:path={runtime}/" + name + "x"):
        assert not gui_test_safety.is_isolated_gui_test(_env(tmp_path, hostile)), hostile


def test_private_bus_address_still_needs_the_runtime_token(tmp_path):
    env = _env(tmp_path, "unix:path={runtime}/" + gui_test_safety.PRIVATE_BUS_NAME)
    env["SMOOTHCAST_GUI_TEST_TOKEN"] = "b" * 64
    assert not gui_test_safety.is_isolated_gui_test(env)


def test_walker_refuses_outside_the_isolated_runner(monkeypatch, capsys):
    monkeypatch.delenv("SMOOTHCAST_GUI_TEST_ISOLATED", raising=False)
    assert gui_a11y_walk.main() == 2
    assert "Refusing" in capsys.readouterr().err


def test_selftest_hold_quits_immediately_by_default(monkeypatch):
    monkeypatch.delenv("SMOOTHCAST_A11Y_HOLD", raising=False)
    app = SimpleNamespace(quit=lambda: app.__dict__.setdefault("quit_calls", []).append(1))
    selftest_hold.quit_when_released(app)
    assert app.quit_calls == [1]


def test_launcher_exposes_the_a11y_mode_without_the_user_bus():
    source = (ROOT / "scripts" / "test_gui_isolated.py").read_text(encoding="utf-8")
    assert '["--a11y"]' in source and "gui_a11y_walk.py" in source
    walk = (ROOT / "scripts" / "gui_a11y_walk.py").read_text(encoding="utf-8")
    assert "<servicedir>" in walk and "DBUS_SESSION_BUS_ADDRESS" in walk
