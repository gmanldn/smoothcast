"""GTK-free tests for the persistent Google Cast adapter."""
from __future__ import annotations

import sys
import uuid
import os
import subprocess
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, "src")

import castctl
from pychromecast_backend import PyChromecastBackend


class FakeMediaController:
    def __init__(self):
        self.status = SimpleNamespace(
            player_state="PLAYING",
            current_time=12.5,
            duration=120.0,
            content_id="http://192.168.1.5/movie.mp4",
            idle_reason=None,
            media_session_id=7,
            volume_level=0.6,
            volume_muted=False,
            media_metadata={"title": "Film"},
            subtitle_tracks={3: {"type": "TEXT"}},
        )
        self.listener = None
        self.calls = []

    def register_status_listener(self, listener):
        self.listener = listener

    def update_status(self):
        self.calls.append(("update_status",))

    def play(self, timeout=10.0):
        self.calls.append(("play", timeout))

    def pause(self, timeout=10.0):
        self.calls.append(("pause", timeout))

    def stop(self, timeout=10.0):
        self.calls.append(("stop", timeout))

    def seek(self, position, timeout=10.0):
        self.calls.append(("seek", position, timeout))

    def enable_subtitle(self, track_id, timeout=10.0):
        self.calls.append(("enable_subtitle", track_id, timeout))

    def disable_subtitle(self, timeout=10.0):
        self.calls.append(("disable_subtitle", timeout))

    def play_media(self, url, content_type, **kwargs):
        self.calls.append(("play_media", url, content_type, kwargs))


class FakeCast:
    def __init__(self, *, name="Living Room", host="192.168.1.25", identifier=None):
        self.cast_info = SimpleNamespace(
            uuid=identifier or uuid.uuid4(),
            friendly_name=name,
            host=host,
            port=8009,
            model_name="Chromecast",
            manufacturer="Google",
        )
        self.uuid = self.cast_info.uuid
        self.media_controller = FakeMediaController()
        self.status = SimpleNamespace(volume_level=0.6, volume_muted=False)
        self.status_listener = None
        self.connection_listener = None
        self.disconnected = []
        self.volume_calls = []

    def register_connection_listener(self, listener):
        self.connection_listener = listener

    def register_status_listener(self, listener):
        self.status_listener = listener

    def set_volume(self, level, timeout=10.0):
        self.volume_calls.append((level, timeout))

    def set_volume_muted(self, muted, timeout=10.0):
        self.volume_calls.append(("mute", muted, timeout))

    def disconnect(self, timeout=2):
        self.disconnected.append(timeout)


class FakeBrowser:
    def __init__(self):
        self.stopped = False

    def stop_discovery(self):
        self.stopped = True


def discovered_backend(casts):
    browser = FakeBrowser()

    def discover(*, callback, **_kwargs):
        for cast in casts:
            callback(cast)
        return browser

    backend = PyChromecastBackend(discover=discover, connect_from_host=mock.Mock())
    return backend, browser


def test_scan_keeps_one_browser_and_returns_device_identity():
    cast = FakeCast()
    backend, browser = discovered_backend([cast])

    assert backend.scan(timeout=0) == [
        castctl.Device("Living Room", "192.168.1.25", 8009, "Chromecast", "Google", str(cast.uuid))
    ]
    assert backend.scan(timeout=0) == [
        castctl.Device("Living Room", "192.168.1.25", 8009, "Chromecast", "Google", str(cast.uuid))
    ]
    assert cast.media_controller.listener is not None
    backend.close()
    assert browser.stopped
    assert cast.disconnected == [2]


def test_warm_scan_returns_snapshot_without_waiting_and_sees_later_advertisements():
    first, second, third = FakeCast(name="Den"), FakeCast(name="Lounge"), FakeCast(name="Bedroom")
    browser = FakeBrowser()
    callbacks = []
    discover_calls = []

    def discover(*, callback, **_kwargs):
        discover_calls.append(1)
        callbacks.append(callback)
        callback(first)
        callback(second)
        return browser

    backend = PyChromecastBackend(discover=discover, connect_from_host=mock.Mock())
    try:
        initial = backend.scan(timeout=0)
        assert len(initial) == 2
        backend._changed.wait = mock.Mock(side_effect=AssertionError("warm scan must not wait"))

        assert backend.scan(timeout=30) == initial
        callbacks[0](third)
        updated = backend.scan(timeout=30)

        assert len(updated) == 3 and {device.name for device in updated} == {"Den", "Lounge", "Bedroom"}
        assert discover_calls == [1]
        backend._changed.wait.assert_not_called()
    finally:
        backend.close()


def test_cold_scan_still_collects_late_advertisements_and_closed_scan_fails():
    first, second = FakeCast(name="Den"), FakeCast(name="Lounge")
    browser = FakeBrowser()
    callbacks = []

    def discover(*, callback, **_kwargs):
        callbacks.append(callback)
        callback(first)

        def advertise_later():
            time.sleep(0.01)
            callback(second)

        threading.Thread(target=advertise_later, daemon=True).start()
        return browser

    backend = PyChromecastBackend(discover=discover, connect_from_host=mock.Mock())
    assert len(backend.scan(timeout=0.5)) == 2
    backend.close()
    with pytest.raises(castctl.CastError, match="backend is closed"):
        backend.scan(timeout=30)


def test_status_commands_and_direct_media_use_the_persistent_cast():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)

    status = backend.info("Living Room")
    assert status == {
        "player_state": "PLAYING",
        "current_time": 12.5,
        "duration": 120.0,
        "content_id": "http://192.168.1.5/movie.mp4",
        "media_session_id": 7,
        "title": "Film",
        "volume_level": 0.6,
        "volume_muted": False,
    }
    assert backend.info("Living Room") == status
    assert cast.media_controller.calls.count(("update_status",)) == 1
    assert backend.command("Living Room", "pause") == (True, "")
    assert backend.command("Living Room", "seek", "60.5") == (True, "")
    assert backend.command("Living Room", "volume", "75") == (True, "")
    assert backend.command("Living Room", "volumemute", "true") == (True, "")
    assert backend.command("Living Room", "subs") == (True, "")
    assert backend.command("Living Room", "subs", "-n") == (True, "")
    assert backend.command(
        "Living Room", "cast", "--no-subs", "http://192.168.1.5/movie.mp4"
    ) == (True, "")

    assert cast.media_controller.calls == [
        ("update_status",),
        ("pause", 12),
        ("seek", 60.5, 12),
        ("enable_subtitle", 3, 12),
        ("disable_subtitle", 12),
        (
            "play_media",
            "http://192.168.1.5/movie.mp4",
            "video/mp4",
            {"title": "movie.mp4", "stream_type": "BUFFERED"},
        ),
    ]
    assert cast.volume_calls == [(0.75, 12), ("mute", True, 12)]
    backend.close()


def test_receiver_exception_details_stay_out_of_command_results():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    try:
        with mock.patch("pychromecast_backend.log_backend_failure") as log:
            cast.media_controller.pause = mock.Mock(side_effect=OSError("/private/media/film.mkv"))
            assert backend.command("Living Room", "pause") == (
                False, "The receiver command failed. Check the receiver connection and try again.",
            )
            log.assert_called_once_with("Google Cast receiver command failed", exc_info=True)
    finally:
        backend.close()


def test_fmp4_hls_cast_declares_segment_formats_to_receiver():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)

    assert backend.command(
        "Living Room", "cast",
        "http://192.168.1.5/movie-" + "a" * 32 + "-fmp4.m3u8",
    ) == (True, "")
    assert cast.media_controller.calls[-1] == (
        "play_media",
        "http://192.168.1.5/movie-" + "a" * 32 + "-fmp4.m3u8",
        "application/vnd.apple.mpegurl",
        {
            "title": "movie-" + "a" * 32 + "-fmp4.m3u8",
            "stream_type": "BUFFERED",
            "media_info": {
                "hlsSegmentFormat": "fmp4",
                "hlsVideoSegmentFormat": "fmp4",
            },
        },
    )
    backend.close()


def test_status_push_reaches_subscriber_and_unsubscribe_stops_delivery():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    updates = []
    unsubscribe = backend.subscribe("Living Room", updates.append)
    status = SimpleNamespace(
        player_state="PAUSED",
        current_time=15.0,
        duration=120.0,
        content_id="http://192.168.1.5/movie.mp4",
        idle_reason=None,
        media_session_id=7,
        volume_level=0.6,
        volume_muted=False,
        media_metadata={"title": "Film"},
    )

    cast.media_controller.listener.new_media_status(status)
    cast.status_listener.new_cast_status(
        SimpleNamespace(volume_level=0.3, volume_muted=True)
    )
    unsubscribe()
    status.player_state = "PLAYING"
    cast.media_controller.listener.new_media_status(status)

    assert len(updates) == 2
    assert updates[0]["player_state"] == "PAUSED"
    assert updates[0]["current_time"] == 15.0
    assert updates[1]["volume_level"] == 0.3
    assert updates[1]["volume_muted"] is True
    backend.close()


def test_pychromecast_backend_advertises_push_status():
    backend, _browser = discovered_backend([])
    assert backend.supports_push_status
    assert backend.subscribe("not discovered", lambda _status: None) is None
    backend.close()


def test_duplicate_friendly_names_are_rejected_and_manual_targets_are_private():
    first = FakeCast(host="192.168.1.25")
    second = FakeCast(host="192.168.1.26")
    backend, _browser = discovered_backend([first, second])
    backend.scan(timeout=0)

    ok, message = backend.command("Living Room", "pause")
    assert not ok
    assert "Several Google Cast receivers" in message
    assert backend.command("8.8.8.8", "pause")[0] is False
    backend.close()


def test_manual_private_ip_connection_uses_one_persistent_connection():
    factory = mock.Mock(
        side_effect=lambda host, **_kwargs: FakeCast(
            name=host[0], host=host[0], identifier=host[2]
        )
    )
    backend = PyChromecastBackend(discover=mock.Mock(return_value=FakeBrowser()),
                                  connect_from_host=factory)

    assert backend.command("192.168.1.30", "pause") == (True, "")
    assert backend.command("192.168.1.30", "stop") == (True, "")
    factory.assert_called_once()
    backend.close()


def test_simultaneous_manual_connects_share_only_the_same_endpoint():
    entered, release = threading.Event(), threading.Event()
    factory_calls = []

    def connect(endpoint, **_kwargs):
        factory_calls.append(endpoint)
        entered.set()
        assert release.wait(2)
        cast = FakeCast(name=f"{endpoint[0]}:{endpoint[1]}", host=endpoint[0], identifier=endpoint[2])
        cast.cast_info.port = endpoint[1]
        return cast

    backend = PyChromecastBackend(discover=mock.Mock(return_value=FakeBrowser()),
                                  connect_from_host=connect)
    wait_entered = threading.Event()
    original_wait = backend._changed.wait

    def observed_wait(timeout=None):
        wait_entered.set()
        return original_wait(timeout)

    backend._changed.wait = observed_wait
    start = threading.Barrier(3)
    results, failures = [], []

    def caller(port):
        start.wait()
        try:
            results.append(backend.connect_manual("192.168.1.44", port=port))
        except Exception as exc:  # pragma: no cover - captured for assertion below
            failures.append(exc)

    threads = [threading.Thread(target=caller, args=(8009,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    try:
        assert entered.wait(2)
        assert wait_entered.wait(2), "the second caller did not join the in-flight attempt"
    finally:
        release.set()
    for thread in threads:
        thread.join(2)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == [] and len(results) == 2 and results[0] == results[1]
    assert len(factory_calls) == 1

    other_port = backend.connect_manual("192.168.1.44", port=9000)
    assert other_port.port == 9000
    assert len(factory_calls) == 2 and [endpoint[1] for endpoint in factory_calls] == [8009, 9000]
    backend.close()


def test_failed_manual_connect_wakes_all_waiters_and_can_be_retried():
    entered, release = threading.Event(), threading.Event()
    factory_calls = []

    def connect(endpoint, **_kwargs):
        factory_calls.append(endpoint)
        if len(factory_calls) == 1:
            entered.set()
            assert release.wait(2)
            raise RuntimeError("receiver did not answer")
        return FakeCast(host=endpoint[0], identifier=endpoint[2])

    backend = PyChromecastBackend(discover=mock.Mock(return_value=FakeBrowser()),
                                  connect_from_host=connect)
    wait_entered = threading.Event()
    original_wait = backend._changed.wait

    def observed_wait(timeout=None):
        wait_entered.set()
        return original_wait(timeout)

    backend._changed.wait = observed_wait
    start = threading.Barrier(3)
    results, failures = [], []

    def caller():
        start.wait()
        try:
            results.append(backend.connect_manual("192.168.1.45"))
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=caller) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    try:
        assert entered.wait(2)
        assert wait_entered.wait(2), "the second caller did not join the in-flight attempt"
    finally:
        release.set()
    for thread in threads:
        thread.join(2)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [] and len(failures) == 2
    assert all("Cannot connect to Google Cast receiver 192.168.1.45:8009" in str(exc)
               for exc in failures)
    recovered = backend.connect_manual("192.168.1.45")
    assert recovered.host == "192.168.1.45" and len(factory_calls) == 2
    backend.close()


def test_manual_connect_waiters_are_released_when_backend_closes():
    entered, release = threading.Event(), threading.Event()
    casts = []

    def connect(endpoint, **_kwargs):
        entered.set()
        assert release.wait(2)
        cast = FakeCast(host=endpoint[0], identifier=endpoint[2])
        casts.append(cast)
        return cast

    backend = PyChromecastBackend(discover=mock.Mock(return_value=FakeBrowser()),
                                  connect_from_host=connect)
    wait_entered = threading.Event()
    original_wait = backend._changed.wait

    def observed_wait(timeout=None):
        wait_entered.set()
        return original_wait(timeout)

    backend._changed.wait = observed_wait
    start = threading.Barrier(3)
    failures = []

    def caller():
        start.wait()
        try:
            backend.connect_manual("192.168.1.46")
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=caller) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    assert entered.wait(2)
    assert wait_entered.wait(2), "the second caller did not join the in-flight attempt"
    backend.close()
    release.set()
    for thread in threads:
        thread.join(2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(failures) == 2 and all("backend is closed" in str(exc) for exc in failures)
    assert casts and casts[0].disconnected == [1]


def test_backend_selection_is_explicit_and_catt_remains_the_fallback():
    fake_library = types.ModuleType("pychromecast")
    fake_library.get_chromecasts = mock.Mock()
    fake_library.get_chromecast_from_host = mock.Mock()
    with mock.patch.dict(sys.modules, {"pychromecast": fake_library}):
        castctl.configure_backend("pychromecast")
        assert isinstance(castctl._backend, PyChromecastBackend)
    castctl.configure_backend("catt")
    assert isinstance(castctl._backend, castctl.CattBackend)
    with mock.patch.dict("os.environ", {"SMOOTHCAST_CAST_BACKEND": "unknown"}):
        with pytest.raises(ValueError, match="must be 'catt' or 'pychromecast'"):
            castctl.configure_backend()


def test_environment_flag_selects_backend_during_fresh_import():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path("src").resolve())
    env["SMOOTHCAST_CAST_BACKEND"] = "pychromecast"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys,types; p=types.ModuleType('pychromecast'); "
            "p.get_chromecasts=lambda **kw: None; "
            "p.get_chromecast_from_host=lambda *args,**kw: None; "
            "sys.modules['pychromecast']=p; import castctl; "
            "from pychromecast_backend import PyChromecastBackend; "
            "assert isinstance(castctl._backend, PyChromecastBackend)",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_running_app_id_is_reported_and_unknown_stays_absent():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    updates = []
    backend.subscribe("Living Room", updates.append)
    media = SimpleNamespace(player_state="IDLE", content_id=None, idle_reason=None)

    cast.status = SimpleNamespace(volume_level=0.6, volume_muted=False, app_id=None)
    cast.media_controller.listener.new_media_status(media)
    cast.status = SimpleNamespace(volume_level=0.6, volume_muted=False, app_id="233637DE")
    cast.status_listener.new_cast_status(cast.status)
    cast.status = SimpleNamespace(volume_level=0.6, volume_muted=False)
    cast.media_controller.listener.new_media_status(media)

    assert updates[0]["app_id"] == ""          # no app running
    assert updates[1]["app_id"] == "233637DE"  # someone else's app
    assert "app_id" not in updates[2]          # cannot tell: fail closed
    backend.close()


def test_status_dict_exposes_standby_and_input_only_when_the_receiver_reports_them():
    backend, _browser = discovered_backend([])
    reported = SimpleNamespace(app_id="", is_stand_by=True, is_active_input=False,
                               volume_level=0.5, volume_muted=False)
    status = backend._status_dict(None, reported)
    assert status["is_stand_by"] is True and status["is_active_input"] is False
    bare = backend._status_dict(None, SimpleNamespace(app_id="", volume_level=0.5, volume_muted=False))
    assert "is_stand_by" not in bare and "is_active_input" not in bare
    backend.close()


@pytest.mark.parametrize("args, code", [
    (("cast", "not-a-url"), "media.url_invalid"),
    (("cast", "http://192.168.1.5/stream"), "media.type_unsupported"),
    (("seek", "not-a-number"), "cast.command_invalid"),
])
def test_command_failures_carry_catalogue_code_and_copy(args, code):
    """#521: each failure returns the reviewed catalogue copy and records its code."""
    import errors

    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    try:
        errors.reset_recent()
        assert backend.command("Living Room", *args) == (False, errors.CATALOGUE[code].message)
        assert [entry["code"] for entry in errors.recent()][-1] == code
    finally:
        backend.close()


def test_no_selectable_subtitle_track_and_unknown_receiver_codes():
    import errors

    cast = FakeCast()
    cast.media_controller.status.subtitle_tracks = {}
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    try:
        errors.reset_recent()
        assert backend.command("Living Room", "subs") == (
            False, errors.CATALOGUE["cast.no_subtitle_track"].message)
        assert errors.recent()[-1]["code"] == "cast.no_subtitle_track"
    finally:
        backend.close()


def test_receiver_failure_message_is_catalogued_and_unchanged():
    import errors

    assert errors.CATALOGUE["cast.command_failed"].message == (
        "The receiver command failed. Check the receiver connection and try again.")

def test_disconnect_invalidates_status_and_reconnect_requires_fresh_observation():
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    updates = []
    backend.subscribe("Living Room", updates.append)
    assert backend.info("Living Room")["player_state"] == "PLAYING"
    cast.connection_listener.new_connection_status(SimpleNamespace(status="LOST"))
    assert backend.info("Living Room") is None
    assert updates[-1] == {}
    # Media events arriving while disconnected are not current evidence.
    cast.media_controller.listener.new_media_status(cast.media_controller.status)
    assert backend.info("Living Room") is None
    cast.connection_listener.new_connection_status(SimpleNamespace(status="CONNECTED"))
    # A reconnect re-observes the current playback status so the receiver keeps
    # reporting instead of appearing silent.
    assert backend.info("Living Room")["player_state"] == "PLAYING"
    cast.media_controller.status.player_state = "PAUSED"
    cast.media_controller.listener.new_media_status(cast.media_controller.status)
    assert backend.info("Living Room")["player_state"] == "PAUSED"
    assert updates[-1]["player_state"] == "PAUSED"
    backend.close()
    cast.media_controller.listener.new_media_status(cast.media_controller.status)
    assert backend.info("Living Room") is None

def test_status_subscription_never_connects_a_manual_target_on_ui_context():
    factory = mock.Mock(
        side_effect=lambda host, **_kwargs: FakeCast(
            name=host[0], host=host[0], identifier=host[2]
        )
    )
    backend = PyChromecastBackend(discover=mock.Mock(return_value=FakeBrowser()),
                                  connect_from_host=factory)
    updates = []
    assert backend.subscribe("192.168.1.30", updates.append) is None
    factory.assert_not_called()
    # The existing asynchronous polling fallback establishes the connection.
    assert backend.info("192.168.1.30")["player_state"] == "PLAYING"
    unsubscribe = backend.subscribe("192.168.1.30", updates.append)
    assert unsubscribe is not None and updates[-1]["player_state"] == "PLAYING"
    factory.assert_called_once()
    unsubscribe()
    backend.close()
    assert backend.subscribe("192.168.1.30", updates.append) is None
    assert backend.info("192.168.1.30") is None
    factory.assert_called_once()


@pytest.mark.parametrize("state,expected", [
    ("PLAYING", "pause"),
    ("BUFFERING", "pause"),
    ("PAUSED", "play"),
    ("UNKNOWN", None),
    ("IDLE", None),
    (None, None),
])
def test_toggle_requires_known_receiver_playback_state(state, expected):
    cast = FakeCast()
    backend, _browser = discovered_backend([cast])
    backend.scan(timeout=0)
    try:
        if state is None:
            cast.connection_listener.new_connection_status(SimpleNamespace(status="LOST"))
        else:
            cast.media_controller.status.player_state = state
            cast.media_controller.listener.new_media_status(cast.media_controller.status)
        cast.media_controller.calls.clear()
        success, message = backend.command("Living Room", "play_toggle")
        if expected is None:
            assert not success and message
            assert cast.media_controller.calls == []
        else:
            assert success
            assert cast.media_controller.calls == [(expected, 12)]
    finally:
        backend.close()


@pytest.mark.parametrize("event", ["LOST", "close"])
def test_initial_status_read_rejects_observation_invalidated_during_read(event):
    receiver = FakeCast()
    backend, _browser = discovered_backend([receiver])
    backend.scan(timeout=0)
    original = backend._status_dict

    def invalidated(media, status):
        snapshot = original(media, status)
        if event == "close":
            backend.close()
        else:
            receiver.connection_listener.new_connection_status(SimpleNamespace(status=event))
        return snapshot

    try:
        with mock.patch.object(backend, "_status_dict", side_effect=invalidated):
            assert backend.info("Living Room") is None
        assert backend.info("Living Room") is None
    finally:
        backend.close()


def test_explicitly_disconnected_receiver_rejects_commands_until_reconnect():
    receiver = FakeCast()
    backend, _browser = discovered_backend([receiver])
    backend.scan(timeout=0)
    try:
        receiver.connection_listener.new_connection_status(SimpleNamespace(status="LOST"))
        receiver.media_controller.calls.clear()
        for action in ("play", "pause", "stop"):
            success, message = backend.command("Living Room", action)
            assert not success and message
        assert receiver.media_controller.calls == []
        receiver.connection_listener.new_connection_status(SimpleNamespace(status="CONNECTED"))
        success, _ = backend.command("Living Room", "pause")
        assert success
        assert receiver.media_controller.calls[-1] == ("pause", 12)
    finally:
        backend.close()
