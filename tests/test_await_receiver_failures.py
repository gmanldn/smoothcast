"""Receiver confirmation failures stay distinct and diagnosable (no real receiver)."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import castctl
import playback_state
import streamer

URL = "http://192.0.2.1:8000/stream.m3u8"


def _session(caster=None):
    session = streamer.Session.__new__(streamer.Session)
    session.caster = caster
    return session


def _await(monkeypatch, replies, **kwargs):
    feed = iter(replies)
    last = {"v": replies[-1]}

    def fake_info(device, timeout=8):
        last["v"] = next(feed, last["v"])
        return last["v"]

    monkeypatch.setattr(castctl, "info", fake_info)
    with pytest.raises(streamer.StreamPreparationError) as error:
        _session(**kwargs)._await_receiver(
            "TV", lambda info: playback_state.hls_session_matches(info, URL, "Film"),
            timeout=0.3, interval=0.01)
    return error.value


@pytest.mark.parametrize("reply", [None, {}])
def test_no_status_is_offline_and_carries_the_recorded_reason(monkeypatch, reply):
    castctl._info_failures["TV"] = "status helper timed out after 8s"
    error = _await(monkeypatch, [reply])
    assert error.code == "cast.receiver_offline"
    assert "status helper timed out after 8s" in str(error)
    castctl._info_failures.pop("TV", None)


def test_no_status_without_a_recorded_reason_keeps_the_plain_message(monkeypatch):
    castctl._info_failures.pop("TV", None)
    error = _await(monkeypatch, [None])
    assert error.code == "cast.receiver_offline"
    assert str(error).startswith("Receiver did not return status")


def test_status_without_player_state_is_not_called_offline(monkeypatch):
    error = _await(monkeypatch, [{"volume_level": 30, "app_id": "CC1AD845"}])
    assert error.code == "cast.status_unavailable"
    assert "did not report playback state" in str(error)


def test_other_media_is_not_confirmed(monkeypatch):
    other = {"player_state": "PLAYING", "content_id": "http://x/other", "title": "Film"}
    error = _await(monkeypatch, [other])
    assert error.code == "cast.playback_unconfirmed"
    assert "did not confirm playback" in str(error)


def test_status_arriving_late_still_confirms(monkeypatch):
    ok = {"player_state": "PLAYING", "content_id": URL, "title": "Film"}
    replies = iter([None, None, ok])
    monkeypatch.setattr(castctl, "info", lambda device, timeout=8: next(replies, ok))
    _session()._await_receiver(
        "TV", lambda info: playback_state.hls_session_matches(info, URL, "Film"),
        timeout=1.0, interval=0.01)


def test_helper_exit_zero_without_match_ends_instead_of_hanging(monkeypatch):
    class Done:
        stdout = None

        def poll(self):
            return 0

    error = _await(monkeypatch, [None], caster=Done())
    assert error.code == "cast.receiver_offline"


def test_matching_receiver_push_wakes_confirmation_without_a_poll_tick(monkeypatch):
    listeners = []
    polled = Event()
    removed = []
    calls = []

    def subscribe(receiver, listen):
        assert receiver == "TV"
        listeners.append(listen)
        return lambda: removed.append(receiver)

    def status(receiver, timeout):
        calls.append(receiver)
        polled.set()
        return None

    monkeypatch.setattr(castctl, "supports_push_status", lambda: True)
    monkeypatch.setattr(castctl, "subscribe", subscribe)
    monkeypatch.setattr(castctl, "info", status)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _session()._await_receiver, "TV",
            lambda info: playback_state.hls_session_matches(info, URL, "Film"),
            timeout=1.5, interval=5.0,
        )
        assert polled.wait(0.7)
        assert len(listeners) == 1
        listeners[0]({"player_state": "PLAYING", "content_id": URL + "?other"})
        listeners[0]({"player_state": "PLAYING", "content_id": URL})
        future.result(timeout=0.7)
    assert calls == ["TV"]
    assert removed == ["TV"]


def test_unrelated_push_alone_times_out_and_unsubscribes(monkeypatch):
    removed = []

    def subscribe(receiver, listen):
        listen({"player_state": "PLAYING", "content_id": URL + "?other"})
        return lambda: removed.append(receiver)

    monkeypatch.setattr(castctl, "supports_push_status", lambda: True)
    monkeypatch.setattr(castctl, "subscribe", subscribe)
    monkeypatch.setattr(castctl, "info", lambda *a, **kw: None)
    with pytest.raises(streamer.StreamPreparationError) as error:
        _session()._await_receiver(
            "TV", lambda info: playback_state.hls_session_matches(info, URL, "Film"),
            timeout=0.05, interval=0.2,
        )
    assert error.value.code == "cast.playback_unconfirmed"
    assert removed == ["TV"]
