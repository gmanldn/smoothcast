"""demo_launch: isolated child environment, no real-session handoff (#454/#523)."""
from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import demo_launch  # noqa: E402
import demo_mode  # noqa: E402


def fake_media(command, **kwargs):
    Path(command[-1]).write_bytes(b"x")
    return subprocess.CompletedProcess(command, 0)


def test_child_gets_demo_environment_without_real_session_channels(tmp_path):
    seen = {}

    def spawn(command, cwd, env):
        seen.update(command=command, env=env, cwd=cwd)
        assert demo_mode.active(env)  # token marker really exists while the child runs
        return 7

    base = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XAUTHORITY": "/x",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "PATH": "/bin",
            "SMOOTHCAST_CAST_BACKEND": "catt", "HOME": "/home/real"}
    code = demo_launch.run(["--demo"], "/venv/python", base, spawn=spawn, parent=tmp_path,
                           media_run=fake_media, out=io.StringIO())
    env = seen["env"]
    assert code == 7 and seen["command"][0] == "/venv/python"
    assert seen["command"][1].endswith("src/cast_control.py")
    for gone in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "SMOOTHCAST_CAST_BACKEND"):
        assert gone not in env
    assert env["SMOOTHCAST_DEMO"] == "1" and env["HOME"] != "/home/real"
    assert env["DISPLAY"] == ":0" and env["GDK_BACKEND"] == "x11"
    assert list(tmp_path.iterdir()) == []  # profile removed afterwards


def test_extra_arguments_and_missing_display_are_refused_without_spawning():
    def spawn(*a, **k):
        raise AssertionError("must not start")

    out = io.StringIO()
    assert demo_launch.run(["--demo", "film.mkv"], spawn=spawn, out=out) == 2
    assert demo_launch.run(["--demo"], base_env={"PATH": "/bin"}, spawn=spawn,
                           media_run=fake_media, out=out) == 1
    assert "DISPLAY" in out.getvalue()
