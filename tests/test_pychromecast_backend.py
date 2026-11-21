"""GTK-free tests for the persistent Google Cast adapter."""
from __future__ import annotations

import sys
import uuid
import os
import subprocess
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
