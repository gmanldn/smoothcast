"""Controller for the idle join slate, driven with fakes (no GTK window, no TV)."""
from __future__ import annotations

import pytest

import castctl
import join_slate_ui
from join_slate_policy import DEFAULT_MEDIA_RECEIVER_APP_ID

ROOM = "http://192.168.1.20:8080/"
URL = ROOM + "join-slate.png"
FREE = {"player_state": "IDLE", "app_id": ""}


class Host(join_slate_ui.JoinSlateMixin):
    def __init__(self, enabled=True):
        self.cfg = {"device": "Lounge", "idle_join_slate": enabled}
        self.session = None
        self.external = False
        self.queue = []
        self.busy = False
        self._portal = type("P", (), {"url": ROOM})()
        self.lines = []

    def _device(self):
        return self.cfg["device"]

    def _dlna_renderer(self, _device=None):
        return None

    def _console(self, text):
        self.lines.append(text)


def after_playback(host):
    """Our own film was playing, then ended: the TV is on and the slate is armed."""
    host.session = object()
    host._join_slate_observe({"player_state": "PLAYING", "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID})
    host.session = None


@pytest.fixture
def rig(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(join_slate_ui.time, "monotonic", lambda: clock[0])

    class Sync:
        @staticmethod
        def run(work, done=None, failed=None, domain=""):
            try:
                result = work()
            except Exception as exc:  # mirrors Async: failures reach `failed`
                failed(str(exc))
            else:
                done(result)

    monkeypatch.setattr(join_slate_ui, "Async", Sync)
    outcome = {"result": (True, "")}

    def command(device, *args, timeout=0):
        calls.append((device, args))
        return outcome["result"]

    monkeypatch.setattr(castctl, "command", command)
    return calls, clock, outcome


def test_slate_is_cast_once_after_a_minute_of_proven_idle(rig):
    calls, clock, _ = rig
    host = Host()
    after_playback(host)
    host._join_slate_observe(FREE)          # starts the idle clock
    assert calls == []
    clock[0] += 61
    host._join_slate_observe(FREE)
    host._join_slate_observe({"player_state": "PLAYING", "content_id": URL,
                              "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID})
    assert calls == [("Lounge", ("cast", "--no-subs", URL))]
    assert host._join_slate_showing({"content_id": URL, "player_state": "PLAYING",
                                     "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID})


def test_user_playback_other_apps_and_disabled_setting_never_cast(rig):
    calls, clock, _ = rig
    for host, info in [
        (Host(enabled=False), FREE),
        (Host(), {"player_state": "IDLE", "app_id": "233637DE"}),
        (Host(), {"player_state": "IDLE"}),
    ]:
        host._join_slate_observe(info)
        clock[0] += 120
        host._join_slate_observe(info)
    busy = Host()
    busy.queue = ["film.mp4"]
    busy._join_slate_observe(FREE)
    clock[0] += 120
    busy._join_slate_observe(FREE)
    assert calls == []


def test_never_wakes_an_unused_tv_at_app_start_or_after_one_slate(rig):
    calls, clock, _ = rig
    fresh = Host()                           # idle receiver, but we never played anything
    fresh._join_slate_observe(FREE)
    clock[0] += 600
    fresh._join_slate_observe(FREE)
    assert calls == []
    host = Host()
    after_playback(host)
    host._join_slate_observe(FREE)
    clock[0] += 61
    host._join_slate_observe(FREE)
    assert len(calls) == 1
    clock[0] += 600                          # slate ended or timed out: not re-cast alone
    host._join_slate_observe(FREE)
    clock[0] += 600
    host._join_slate_observe(FREE)
    assert len(calls) == 1
    host._slate_armed = None
    other = Host()
    after_playback(other)
    other.cfg["device"] = "Kitchen"          # arming belongs to the receiver that played
    other._join_slate_observe(FREE)
    clock[0] += 120
    other._join_slate_observe(FREE)
    assert len(calls) == 1


@pytest.mark.parametrize("flag", [{"is_stand_by": True}, {"is_active_input": False}])
def test_tv_on_standby_or_another_input_is_left_alone(rig, flag):
    calls, clock, _ = rig
    host = Host()
    after_playback(host)
    host._join_slate_observe({**FREE, **flag})
    clock[0] += 120
    host._join_slate_observe({**FREE, **flag})
    assert calls == []


def test_failure_backs_off_instead_of_retrying_every_poll(rig):
    calls, clock, outcome = rig
    outcome["result"] = (False, "refused")
    host = Host()
    after_playback(host)
    host._join_slate_observe(FREE)
    clock[0] += 61
    host._join_slate_observe(FREE)
    host._join_slate_observe(FREE)
    clock[0] += 300
    host._join_slate_observe(FREE)
    assert len(calls) == 1
    assert "not shown" in host.lines[-1]
    clock[0] += 400
    host._join_slate_observe(FREE)
    assert len(calls) == 2


def test_observer_never_raises_into_the_status_poll(rig):
    host = Host()
    host.cfg = None                          # force an internal error
    host._join_slate_observe(FREE)           # must swallow and log


def test_clear_stops_only_our_own_slate(rig, monkeypatch):
    _calls, _clock, _ = rig
    stopped = []
    monkeypatch.setattr(castctl, "stop", lambda d: (stopped.append(d), (True, ""))[1])
    ours = {"player_state": "PLAYING", "content_id": URL,
            "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID}
    host = Host()
    host._slate_cast = ("Lounge", URL)
    monkeypatch.setattr(castctl, "info", lambda d: ours)
    assert host._join_slate_clear_now() is True and stopped == ["Lounge"]

    host._slate_cast = ("Lounge", URL)       # someone replaced it with another app
    monkeypatch.setattr(castctl, "info", lambda d: {**ours, "app_id": "233637DE"})
    assert host._join_slate_clear_now() is False and stopped == ["Lounge"]
    assert host._slate_cast is None


def test_turning_the_setting_off_takes_down_only_our_slate(rig, monkeypatch):
    _calls, _clock, _ = rig
    stopped = []
    monkeypatch.setattr(castctl, "stop", lambda d: (stopped.append(d), (True, ""))[1])
    monkeypatch.setattr(castctl, "info", lambda d: {
        "player_state": "PLAYING", "content_id": URL,
        "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID})
    host = Host(enabled=False)
    host._slate_cast = ("Lounge", URL)
    host._join_slate_observe(FREE)
    host._join_slate_observe(FREE)           # second poll: nothing left to clear
    assert stopped == ["Lounge"] and host._slate_cast is None


def test_setting_and_wiring_are_registered():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src"
    assert '"idle_join_slate": False' in (src / "cast_widgets.py").read_text()
    prefs = (src / "preferences_ui.py").read_text()
    assert "join_slate_ui.add_switch(self, room)" in (src / "preferences_room_ui.py").read_text()
    assert '"Show join code on the TV when idle"' in (src / "join_slate_ui.py").read_text()
    assert '"idle_join_slate"' in prefs.split("def _change_switch", 1)[1]
    queue = (src / "cast_discovery.py").read_text()
    assert "self._join_slate_observe(info)" in queue
    assert "_join_slate_showing(info)" in queue.split("def _detect_external", 1)[1]
