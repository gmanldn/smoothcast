"""Receiver confirmation failures stay distinct and diagnosable (no real receiver)."""
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from statistics import median
from threading import Event
from types import SimpleNamespace

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

def _timed_cast_start(monkeypatch, root, route, preparation_ms, receiver_ms, *, matching=True):
    """Exercise the real start and confirmation paths with a virtual clock."""
    now = [0]
    loaded_at = None
    content = None

    def delay(seconds):
        now[0] += round(seconds * 1000)

    def cast_command(args):
        if route == "Direct":
            now[0] += preparation_ms
        return ["synthetic-cast", *args]

    def popen(args, **kwargs):
        nonlocal loaded_at, content
        if args[0] == "synthetic-cast":
            loaded_at = now[0]
            content = next((arg for arg in args if arg.startswith("http://")), args[-1])
            return SimpleNamespace(pid=0, poll=lambda: 0, stdout=None)
        return SimpleNamespace(pid=0, poll=lambda: None, stdout=None)

    def info(device, timeout):
        assert loaded_at is not None
        ready = matching and now[0] - loaded_at >= receiver_ms
        return {"player_state": "PLAYING", "title": "Film" if ready else "Other",
                "content_id": content if ready else URL + "?other"}

    def segments_ready(timeout):
        now[0] += preparation_ms
        return True

    with monkeypatch.context() as patch:
        patch.setattr(streamer, "ROOT", root)
        patch.setattr(streamer, "FFMPEG_LOG", root / "ffmpeg.log")
        patch.setattr(streamer, "_save_session", lambda state: None)
        patch.setattr(streamer, "require_compatible_ffmpeg", lambda: (7, 0))
        patch.setattr(streamer, "host_ip", lambda device: "192.168.1.18")
        patch.setattr(streamer, "time", SimpleNamespace(
            monotonic=lambda: now[0] / 1000, sleep=delay, time=lambda: 1700000000))
        patch.setattr(streamer.subprocess, "Popen", popen)
        patch.setattr(streamer.process_identity, "start_time", lambda pid: 0.0)
        patch.setattr(streamer.process_priority, "lower", lambda process, low: None)
        patch.setattr(castctl, "catt_command", cast_command)
        patch.setattr(castctl, "supports_push_status", lambda: False)
        patch.setattr(castctl, "info", info)
        session = streamer.Session(port=8767)
        session.used_software_fallback = True
        patch.setattr(session, "_start_server", lambda *args, **kwargs: None)
        patch.setattr(session, "_start_sampler", lambda: None)
        patch.setattr(session, "_wait_for_segments", segments_ready)
        patch.setattr(session, "_begin_attempt", lambda args, software: "virtual encoder")
        media = streamer.MediaInfo(path=root / "film.mp4", duration=60, width=1280, height=720)
        intent_at = round(streamer.time.monotonic() * 1000)
        try:
            if route == "Direct":
                session.start_direct(media, device="TV", subs_file=None,
                                     subs_disabled=True, title="Film")
            else:
                session.start_transcode(
                    media, 0.0, device="TV", quality="balanced", audio_profile="original",
                    subs_file=None, burn_subs=False, title="Film")
        except streamer.StreamPreparationError as error:
            assert error.code == "cast.playback_unconfirmed"
            return None
        assert session.state is not None
        assert session.state.mode == ("direct" if route == "Direct" else "transcode")
        assert loaded_at is not None
        return loaded_at - intent_at, now[0] - loaded_at, now[0] - intent_at


def test_cast_start_timing_matrix(monkeypatch, tmp_path):
    print("Synthetic clock, milliseconds. Cold/warm are injected fixture conditions.")
    print("| Route | Condition | Confirmed | Rejected | Intent→LOAD median/p95 | LOAD→playing median/p95 | Total median/p95 |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for route, condition, prepare in (("Direct", "cold", 100), ("Direct", "warm", 20),
                                      ("HLS", "cold", 400), ("HLS", "warm", 125)):
        base_receiver = 500 if condition == "cold" else 250
        tried = [
            _timed_cast_start(monkeypatch, tmp_path, route, prepare + 10 * (n % 4),
                              base_receiver + 250 * (n % 3))
            for n in range(20)
        ]
        tried.append(_timed_cast_start(monkeypatch, tmp_path, route, prepare, 0, matching=False))
        successes = [result for result in tried if result is not None]
        rejected = len(tried) - len(successes)
        assert len(successes) == 20 and rejected == 1
        stages = [f"{median(values):g}/{sorted(values)[ceil(0.95 * len(values)) - 1]}"
                  for values in zip(*successes)]
        print(f"| {route} | {condition} | {len(successes)} | {rejected} | " + " | ".join(stages) + " |")

        baseline = _timed_cast_start(monkeypatch, tmp_path, route, prepare, base_receiver)
        pre_load = _timed_cast_start(monkeypatch, tmp_path, route, prepare + 500, base_receiver)
        before_play = _timed_cast_start(monkeypatch, tmp_path, route, prepare, base_receiver + 500)
        assert baseline == (prepare, base_receiver, prepare + base_receiver)
        assert tuple(b - a for a, b in zip(baseline, pre_load)) == (500, 0, 500)
        assert tuple(b - a for a, b in zip(baseline, before_play)) == (0, 500, 500)
