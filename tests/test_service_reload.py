"""Relaunching ``sc.py`` bounces services in place without interrupting playback.

The launcher forwards ``--reload-services`` to an already-running primary; the
primary restarts its room, mesh, library indexer, heartbeat and MPRIS while the
active cast, session and tracker keep running.
"""
from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "src" / "cast_control.py"
sys.path.insert(0, str(ROOT / "setup"))  # setup/launch.py is GTK-free by design


def _reload_window():
    """A bare ``Window`` carrying the real ``reload_house_services`` method."""
    source = main_window_methods()["reload_house_services"]
    code = "class Window:\n" + textwrap.indent(textwrap.dedent(source), "    ") + "\n"
    namespace: dict = {}
    exec(compile(code, "<service-reload>", "exec"), namespace)  # noqa: S102
    return namespace["Window"]()


def test_reload_stops_then_rebuilds_room_mesh_indexer_and_heartbeat():
    window = _reload_window()
    calls: list[str] = []
    window._closing = False
    window._stop_portal = lambda: calls.append("stop_portal")
    window._stop_house_services = lambda: calls.append("stop_house")
    window._refresh_portal = lambda: calls.append("refresh_portal")
    window.reload_house_services()
    # Room + mesh + heartbeat come down first, then everything is rebuilt.
    assert calls == ["stop_portal", "stop_house", "refresh_portal"]


def test_reload_never_touches_playback_ownership():
    window = _reload_window()
    window._closing = False
    window._stop_portal = lambda: None
    window._stop_house_services = lambda: None
    window._refresh_portal = lambda: None
    # A bounce must leave the active cast and its tracker untouched.
    session = object()
    tracker = object()
    window.session = session
    window.tracker = tracker
    window.external = False
    window.reload_house_services()
    assert window.session is session and window.tracker is tracker
    assert window.external is False


def test_reload_is_a_no_op_while_closing():
    window = _reload_window()
    calls: list[str] = []
    window._closing = True
    window._stop_portal = lambda: calls.append("stop_portal")
    window._stop_house_services = lambda: calls.append("stop_house")
    window._refresh_portal = lambda: calls.append("refresh_portal")
    window.reload_house_services()
    assert calls == []


def _app_methods() -> dict[str, str]:
    source = CONTROL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    app = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "CastControlApp")
    return {member.name: ast.get_source_segment(source, member)
            for member in app.body if isinstance(member, ast.FunctionDef)}


def test_command_line_parses_the_reload_flag_and_schedules_a_bounce():
    methods = _app_methods()
    command_line = methods["do_command_line"]
    assert '"--reload-services"' in command_line
    assert "self._reload_services" in command_line


def test_bounce_waits_for_started_services_and_restarts_mpris():
    reload_method = _app_methods()["_reload_services"]
    # A cold start has nothing to bounce: only act once timers (services) run.
    assert "_timers_enabled" in reload_method
    assert "reload_house_services" in reload_method
    assert "_restart_mpris" in reload_method


def test_launcher_and_app_agree_on_the_reload_flag():
    import launch  # setup/launch.py, GTK-free

    assert launch.RELOAD_SERVICES_ARG == "--reload-services"
    assert launch.RELOAD_SERVICES_ARG in CONTROL.read_text(encoding="utf-8")
