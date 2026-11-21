"""Wall-clock corrections never alter room presence or timeout durations."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_room


def test_wall_clock_jumps_do_not_change_presence_or_session_expiry():
    monotonic = [1000.0]
    wall = [1700000000.0]
    clock = lambda: monotonic[0]
    wall_clock = lambda: wall[0]
    room = portal_room.PortalRoom(clock=clock, wall_clock=wall_clock)
    server = portal._PortalHTTPServer(
        ("127.0.0.1", 0), "234567", lambda *_args: {},
        clock=clock, room=room,
    )
    try:
        token, csrf, participant = server.create_session("Sam")
        assert participant.joined_at == wall[0]
        assert server.room.snapshot()["participants"][0]["online"]
        for delta in (+3600, -7200):
            wall[0] += delta
            server.service_actions()
            assert server.session_csrf(token) == csrf
            assert server.room.snapshot()["participants"][0]["online"]
        monotonic[0] += portal_room.ONLINE_SECONDS + 1
        server.service_actions()
        assert server.room.snapshot()["participants"] == []
        assert server.session_participant(token) == participant.id
        assert server.room.snapshot()["participants"][0]["name"] == "Sam"
        monotonic[0] += portal.SESSION_SECONDS + 1
        assert server.session_csrf(token) is None
        assert server.room.snapshot()["participants"] == []
    finally:
        server.server_close()


def test_event_timestamps_are_wall_time_not_uptime():
    mono = [300.0]
    wall = [1800000000.0]
    room = portal_room.PortalRoom(clock=lambda: mono[0], wall_clock=lambda: wall[0])
    p = room.join("Sam")
    assert room.snapshot()["activity"][-1]["at"] == wall[0]
    mono[0] += 10
    wall[0] += 3600
    room.record(p.id, "action")
    assert room.snapshot()["activity"][-1]["at"] == wall[0]
    assert room.snapshot()["participants"][0]["online"]


def test_timeout_paths_cannot_reintroduce_wall_clock_subtraction():
    root = Path(__file__).resolve().parents[1] / "src"
    forbidden = {
        "portal_room.py": ("time.time() if now is None",),
        "portal.py": ("self.room.expire_inactive(time.time())",
                      "self.room.join(name, now=time.time())"),
        "streamer.py": ("deadline = time.time() + timeout",
                        "time.time() < deadline"),
        "cast_av.py": ("self._volume_user_ts = time.time()",),
        "cast_queue.py": ("time.time() - self._volume_user_ts",),
    }
    for filename, patterns in forbidden.items():
        source = (root / filename).read_text()
        for pattern in patterns:
            assert pattern not in source, (filename, pattern)
