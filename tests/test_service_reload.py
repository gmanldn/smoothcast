"""Relaunching ``sc.py`` bounces services in place without interrupting playback.

The launcher forwards ``--reload-services`` to an already-running primary; the
primary restarts its room, mesh, library indexer, heartbeat and MPRIS while the
active cast, session and tracker keep running.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

from gui_source import main_window_methods

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "src" / "cast_control.py"
sys.path.insert(0, str(ROOT / "setup"))  # setup/launch.py is GTK-free by design


def _reload_window():
    """A bare ``Window`` carrying the real ``reload_house_services`` method."""
    import cast_portal_room

    class Window:
        def __init__(self):
            self.reload_house_services = cast_portal_room.PortalRoomController(self).reload_house_services

    return Window()


def test_reload_stops_then_rebuilds_room_mesh_indexer_and_heartbeat():
    window = _reload_window()
    calls: list[str] = []
    window._closing = False
    window._portal = SimpleNamespace(pin="135790")
    window._stop_portal = lambda: calls.append("stop_portal")
    window._stop_house_services = lambda **kw: calls.append(("stop_house", kw))
    window._refresh_portal = lambda: calls.append("refresh_portal")
    window.reload_house_services()
    # Room + mesh + heartbeat come down first, then everything is rebuilt.
    assert calls == ["stop_portal", ("stop_house", {"keep_fingerprint": True}),
                     "refresh_portal"]
    # The printed PIN stays valid so guests only re-authenticate, not re-learn it.
    assert window._portal_reuse_pin == "135790"


def test_reload_keeps_the_process_wide_content_key_cache():
    # Closing fingerprint.KEYS is a shutdown-only action; a bounce must not
    # permanently disable content keys for casting and queueing.
    window = _reload_window()
    window._closing = False
    window._stop_portal = lambda: None
    window._refresh_portal = lambda: None
    seen: list[bool] = []
    window._stop_house_services = lambda **kw: seen.append(kw.get("keep_fingerprint", False))
    window.reload_house_services()
    assert seen == [True]


def test_reload_never_touches_playback_ownership():
    window = _reload_window()
    window._closing = False
    window._stop_portal = lambda: None
    window._stop_house_services = lambda **kw: None
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
    window._stop_house_services = lambda **kw: calls.append("stop_house")
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


def test_refresh_portal_reuses_the_pin_stashed_by_a_bounce():
    refresh = main_window_methods()["_refresh_portal"]
    assert "_portal_reuse_pin" in refresh
    assert "pin=pin" in refresh


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
