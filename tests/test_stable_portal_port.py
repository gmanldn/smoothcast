"""Stable remote port: deterministic selection, collision handling and preferences."""
from pathlib import Path
import socket

import config_control
import portal


def _server(address):
    return portal.bind_room_server(
        address, "234567", lambda *_args: {},
    )


def test_random_initial_port_is_in_high_range_and_reproducible():
    value = portal.preferred_room_port(0, pick=lambda maximum: maximum - 1)
    assert value == portal.MAX_PORT
    assert portal.preferred_room_port(value) == value
    for invalid in (-1, 1024, 49151, 65536, True, "50000"):
        try:
            portal.preferred_room_port(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid port: {invalid}")


def test_room_port_is_reused_across_fresh_server_starts():
    first, fallback = _server(("127.0.0.1", 0))
    port = first.server_address[1]
    assert not fallback
    first.server_close()
    second, fallback = _server(("127.0.0.1", port))
    try:
        assert second.server_address[1] == port
        assert not fallback
    finally:
        second.server_close()


def test_taken_port_falls_back_to_new_port_without_stealing_listener():
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    server, fallback = _server(("127.0.0.1", port))
    try:
        assert fallback
        assert server.server_address[1] != port
    finally:
        server.server_close()
        occupied.close()


def test_port_config_is_bounded_and_desktop_persists_selected_port():
    defaults = {"portal_port": 0, "hls_port": 8767}
    for value in (0, 49152, 65535):
        assert config_control.sanitise_config({"portal_port": value}, defaults)["portal_port"] == value
    for value in (-1, 1, 49151, 65536, True, "49152"):
        assert config_control.sanitise_config({"portal_port": value}, defaults)["portal_port"] == 0
    root = Path(__file__).resolve().parents[1]
    host = (root / "src" / "cast_portal.py").read_text()
    pref = ((root / "src" / "preferences_ui.py").read_text()
            + (root / "src" / "preferences_tracks_ui.py").read_text()
            + (root / "src" / "preferences_room_ui.py").read_text())
    assert "preferred_port=settings.PortalSettings.from_config(self.cfg).port" in host
    assert 'self.cfg["portal_port"] = self._portal.port' in host
    assert 'self._portal.port_fallback' in host
    assert '"Room remote port"' in pref
    assert 'self.owner.cfg["portal_port"] = value' in pref
