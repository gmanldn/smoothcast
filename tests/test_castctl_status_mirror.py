"""The kept status connection must never keep answering from a stale cache.

A reused connection that stopped answering (TV standby, app switch) used to
return an empty ``UNKNOWN`` status forever, so a cast failed with "Receiver
responded but did not report playback state" (Living Room TV).
"""
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import castctl

# The autouse conftest fixture replaces these per test; keep the real ones.
REAL_INFO = castctl._StatusMirror.info
MEDIA_NS = castctl._MEDIA_NAMESPACE


class FakeChromecast:
    """A pychromecast stand-in whose receiver may or may not answer."""

    def __init__(self, *, answers=True, app_id="CC1AD845", namespaces=(MEDIA_NS,),
                 media_after_update=True, session=None):
        self.answers = answers
        self.media_after_update = media_after_update
        self.status = SimpleNamespace(app_id=app_id, volume_level=0.5, volume_muted=False)
        self.media_controller = SimpleNamespace(
            status=SimpleNamespace(
                player_state="UNKNOWN", media_session_id=session, content_id=None,
                current_time=0.0, duration=None, idle_reason=None),
            update_status=self._update_media)
        self.socket_client = SimpleNamespace(
            app_namespaces=list(namespaces),
            receiver_controller=SimpleNamespace(update_status=self._update_receiver))
        self.media_updates = 0
        self.receiver_updates = 0
        self.disconnected = False

    def wait(self, timeout=None):
        return True

    def disconnect(self, timeout=None):
        self.disconnected = True

    def _update_receiver(self, callback_function=None):
        self.receiver_updates += 1
        if self.answers and callback_function is not None:
            callback_function(True, {})

    def _update_media(self):
        self.media_updates += 1
        if self.media_after_update:
            self.media_controller.status.media_session_id = 5
            self.media_controller.status.player_state = "PLAYING"


def _mirror_with(monkeypatch, *chromecasts):
    """A mirror whose connection factory hands out the given fakes in order."""
    queue = list(chromecasts)
    created = []

    def connect(host_tuple, **_kwargs):
        cast = queue.pop(0)
        created.append(cast)
        return cast

    monkeypatch.setitem(sys.modules, "pychromecast",
                        SimpleNamespace(get_chromecast_from_host=connect))
    monkeypatch.setattr(castctl, "log_backend_failure", lambda *a, **k: None)
    castctl._info_failures.clear()
    return castctl._StatusMirror(), created


def test_stale_kept_connection_is_replaced_by_a_fresh_one(monkeypatch):
    stale = FakeChromecast(answers=False)
    fresh = FakeChromecast()
    mirror, created = _mirror_with(monkeypatch, fresh)
    mirror._casts["10.0.0.5"] = stale  # a connection kept from an earlier poll

    status = REAL_INFO(mirror, "10.0.0.5", 6.0)

    assert status is not None and status["player_state"] == "PLAYING"
    assert stale.disconnected and created == [fresh]
    assert mirror._casts["10.0.0.5"] is fresh


def test_live_kept_connection_is_refreshed_not_replaced(monkeypatch):
    live = FakeChromecast(session=3)
    mirror, created = _mirror_with(monkeypatch)
    mirror._casts["10.0.0.5"] = live

    status = REAL_INFO(mirror, "10.0.0.5", 6.0)

    assert status is not None and live.receiver_updates == 1
    assert created == [] and not live.disconnected


def test_kept_connection_that_never_joins_the_running_app_reconnects(monkeypatch):
    joined_nothing = FakeChromecast(media_after_update=False)
    fresh = FakeChromecast()
    mirror, created = _mirror_with(monkeypatch, fresh)
    mirror._casts["10.0.0.5"] = joined_nothing

    status = REAL_INFO(mirror, "10.0.0.5", 8.0)

    assert status["player_state"] == "PLAYING"
    assert joined_nothing.disconnected and created == [fresh]


def test_app_without_a_media_channel_is_reported_without_waiting(monkeypatch):
    backdrop = FakeChromecast(app_id="E8C28D3C", namespaces=(), media_after_update=False)
    mirror, _created = _mirror_with(monkeypatch)
    mirror._casts["10.0.0.5"] = backdrop

    started = time.monotonic()
    status = REAL_INFO(mirror, "10.0.0.5", 6.0)

    assert time.monotonic() - started < 1.0  # used to burn 1.5 s per poll
    assert status is not None and status["app_id"] == "E8C28D3C"
    assert backdrop.media_updates == 0 and not backdrop.disconnected


def test_first_connection_with_no_media_session_reports_honestly(monkeypatch):
    fresh = FakeChromecast(media_after_update=False)
    mirror, created = _mirror_with(monkeypatch, fresh)

    status = REAL_INFO(mirror, "10.0.0.5", 4.0)

    assert status is not None and status["player_state"] == "UNKNOWN"
    assert created == [fresh] and not fresh.disconnected


def test_forget_waits_for_receiver_socket_startup_before_disconnect(monkeypatch):
    starting, allow_start = threading.Event(), threading.Event()
    disconnected = threading.Event()
    fresh = FakeChromecast()

    def wait(timeout=None):
        del timeout
        starting.set()
        assert allow_start.wait(2)
        return True

    def disconnect(timeout=None):
        del timeout
        disconnected.set()
        fresh.disconnected = True

    fresh.wait = wait
    fresh.disconnect = disconnect
    mirror, created = _mirror_with(monkeypatch, fresh)
    statuses = []
    reader = threading.Thread(
        target=lambda: statuses.append(REAL_INFO(mirror, "10.0.0.6", 3.0)))
    reader.start()
    assert starting.wait(1)

    drop_attempted = threading.Event()

    def forget():
        drop_attempted.set()
        mirror.forget("10.0.0.6")

    cleanup = threading.Thread(target=forget)
    cleanup.start()
    try:
        assert drop_attempted.wait(1)
        assert not disconnected.wait(0.05), "disconnect raced the SocketClient startup"
    finally:
        allow_start.set()
    reader.join(2)
    cleanup.join(2)

    assert not reader.is_alive() and not cleanup.is_alive()
    assert len(statuses) == 1 and statuses[0]["player_state"] == "PLAYING"
    assert created == [fresh] and disconnected.is_set()


def test_unreachable_receiver_reports_no_status(monkeypatch):
    def connect(*_args, **_kwargs):
        raise OSError("no route")

    monkeypatch.setitem(sys.modules, "pychromecast",
                        SimpleNamespace(get_chromecast_from_host=connect))
    monkeypatch.setattr(castctl, "log_backend_failure", lambda *a, **k: None)
    castctl._info_failures.clear()
    assert REAL_INFO(castctl._StatusMirror(), "10.0.0.5", 3.0) is None


def test_backend_reset_drops_the_kept_route(monkeypatch):
    backend = castctl.CattBackend()
    forgotten = []
    backend._mirror = SimpleNamespace(forget=forgotten.append)
    backend._mirror_routes["Living Room TV"] = "10.0.0.5"

    backend.reset_status_route("Living Room TV")
    backend.reset_status_route("Living Room TV")  # idempotent

    assert forgotten == ["10.0.0.5"] and "Living Room TV" not in backend._mirror_routes
    monkeypatch.setattr(castctl, "_backend", SimpleNamespace())
    castctl.reset_status_route("anything")  # backends without it are fine


@pytest.mark.parametrize("answered", [True, False])
def test_cast_confirmation_resets_a_route_that_only_reports_unknown(monkeypatch, answered):
    """_await_receiver must not poll one dead cache for the whole 40 s."""
    import streamer

    resets = []
    clock = {"now": 0.0}
    monkeypatch.setattr(streamer.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(streamer.time, "sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    monkeypatch.setattr(castctl, "reset_status_route", resets.append)

    def info(device, timeout=8):
        playing = answered and bool(resets)
        return {"player_state": "PLAYING" if playing else "UNKNOWN", "content_id": "u"}

    monkeypatch.setattr(castctl, "info", info)
    session = streamer.Session.__new__(streamer.Session)
    session.caster = None
    matcher = lambda i: bool(i) and i.get("player_state") == "PLAYING"  # noqa: E731
    if answered:
        session._await_receiver("Living Room TV", matcher, timeout=40.0)
    else:
        with pytest.raises(streamer.StreamPreparationError) as caught:
            session._await_receiver("Living Room TV", matcher, timeout=40.0)
        assert "did not report playback state" in str(caught.value)
    assert resets and len(resets) <= 3 and set(resets) == {"Living Room TV"}
