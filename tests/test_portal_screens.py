"""Screen registry: ownership, fencing, expiry, routing and auto-advance."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal_screens as screens

CAPS = ["video/mp4", "audio/mpeg", "audio/mp4"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def registry(clock):
    return screens.ScreenRegistry(clock=clock, can_transcode=lambda: True)


def make(registry, key="k1", name="Lounge TV", caps=CAPS):
    return registry.register(key, "p1", name, caps)


def play(registry, screen, item="abc", suffix=".mp4", **extra):
    return registry.command(screen.id, "play", item=item, title="Film",
                            duration=60.0, suffix=suffix, **extra)


# -- naming, capabilities and bounds ---------------------------------------

def test_names_are_sanitised_and_unique(registry):
    first = make(registry, "k1", "  Living\x00 room\n TV  ")
    second = make(registry, "k2", "Living room TV")
    third = make(registry, "k3", "")
    assert first.name == "Living room TV"
    assert second.name == "Living room TV 2"
    assert third.name == "Screen"


def test_unknown_capabilities_are_dropped(registry):
    screen = make(registry, caps=["video/mp4", "text/html", 7, "audio/flac"])
    assert screen.capabilities == {"video/mp4", "audio/flac"}
    assert make(registry, "k2", caps="video/mp4").capabilities == frozenset()


def test_registry_is_bounded_and_reuses_a_session_slot(registry):
    for index in range(screens.MAX_SCREENS):
        make(registry, f"k{index}", f"S{index}")
    with pytest.raises(screens.ScreenError) as info:
        make(registry, "extra", "One too many")
    assert info.value.status == 409
    # The same session re-registering (reload, reconnect) keeps its slot and id.
    again = make(registry, "k0", "Renamed")
    assert again.id == next(s for s in registry._screens.values() if s.owner_key == "k0").id
    assert len(registry.snapshot()) == screens.MAX_SCREENS


def test_claim_only_works_for_the_owner(registry):
    mine = make(registry, "k1")
    other = registry.register("k2", "p2", "Other", CAPS, claim=mine.id)
    assert other.id != mine.id
    assert registry.register("k1", "p1", "Mine", CAPS, claim=mine.id).id == mine.id


# -- expiry ----------------------------------------------------------------

def test_screen_goes_stale_then_expires_without_contact(registry, clock):
    screen = make(registry)
    clock.now += screens.STALE_AFTER + 1
    assert registry.snapshot()[0]["ready"] is False
    with pytest.raises(screens.ScreenError) as info:
        play(registry, screen)
    assert info.value.status == 409          # never queue orders for a dead screen
    clock.now += screens.SCREEN_TTL
    assert registry.snapshot() == []


def test_polling_counts_as_contact(registry, clock):
    screen = make(registry)
    for _ in range(5):
        clock.now += 10
        registry.poll(screen.id, "k1", 0)
    assert registry.snapshot()[0]["ready"] is True


def test_revoked_sessions_lose_their_screens(registry):
    make(registry, "k1", "A")
    make(registry, "k2", "B")
    assert registry.drop_owner_keys({"k1"}) == 1
    assert [s["name"] for s in registry.snapshot()] == ["B"]
    assert registry.retain_owner_keys(lambda key: False) == 1
    assert registry.snapshot() == []


# -- ownership -------------------------------------------------------------

def test_only_the_owner_can_poll_report_or_remove(registry):
    screen = make(registry, "k1")
    for call in (
        lambda: registry.poll(screen.id, "intruder", 0),
        lambda: registry.report(screen.id, "intruder", {"state": "idle"}),
    ):
        with pytest.raises(screens.ScreenError) as info:
            call()
        assert info.value.status == 404
    assert registry.remove(screen.id, "intruder") is False
    assert registry.remove(screen.id, "k1") is True


# -- commands and fencing --------------------------------------------------

def test_orders_are_sequenced_and_replayed_after_a_missed_poll(registry):
    screen = make(registry)
    play(registry, screen)
    registry.command(screen.id, "pause")
    registry.command(screen.id, "seek", value=42)
    registry.command(screen.id, "volume", value=30)
    result = registry.poll(screen.id, "k1", 0)
    assert [o["kind"] for o in result["orders"]] == ["play", "pause", "seek", "volume"]
    assert [o["seq"] for o in result["orders"]] == [1, 2, 3, 4]
    later = registry.poll(screen.id, "k1", 2)
    assert [o["kind"] for o in later["orders"]] == ["seek", "volume"]
    assert registry.poll(screen.id, "k1", 4)["orders"] == []


def test_identical_command_id_is_an_idempotent_retry(registry):
    screen = make(registry)
    first = play(registry, screen, command_id="c-1")
    second = play(registry, screen, command_id="c-1")
    assert first == second
    assert len(registry.poll(screen.id, "k1", 0)["orders"]) == 1


def _state(registry, screen):
    row = registry.snapshot()[0]
    return (row["state"], row["item"], screen.seq, len(screen.orders))


def test_a_reused_command_id_with_a_different_intent_is_a_conflict(registry):
    screen = make(registry)
    first = play(registry, screen, item="aaa", command_id="X")
    assert play(registry, screen, item="aaa", command_id="X") == first
    # Display metadata is not intent: a retry that renames the film still replays.
    renamed = registry.command(screen.id, "play", item="aaa", title="Renamed",
                               duration=61.0, suffix=".mp4", command_id="X")
    assert renamed == first
    assert len(screen.orders) == 1
    settled = _state(registry, screen)

    def conflicts(action, **kw):
        with pytest.raises(screens.ScreenError) as info:
            registry.command(screen.id, action, command_id="X", **kw)
        assert info.value.status == 409
        assert _state(registry, screen) == settled

    conflicts("stop")
    conflicts("play", item="bbb", title="Film", duration=60.0, suffix=".mp4")
    conflicts("play", item="aaa", title="Film", duration=60.0, suffix=".mp4", start=30.0)
    conflicts("play", item="aaa", title="Film", duration=60.0, suffix=".mp4", follow=True)
    conflicts("pause")
    # The original receipt is still replayable afterwards.
    assert play(registry, screen, item="aaa", command_id="X") == first


def test_a_reused_seek_or_volume_id_with_a_changed_value_is_a_conflict(registry):
    screen = make(registry)
    play(registry, screen, item="aaa")
    seek = registry.command(screen.id, "seek", value=40, command_id="S")
    assert registry.command(screen.id, "seek", value=40.0, command_id="S") == seek
    volume = registry.command(screen.id, "volume", value=30, command_id="V")
    settled = _state(registry, screen)
    for action, value, cid in (("seek", 90, "S"), ("volume", 31, "V"), ("seek", 40, "V")):
        with pytest.raises(screens.ScreenError) as info:
            registry.command(screen.id, action, value=value, command_id=cid)
        assert info.value.status == 409
        assert _state(registry, screen) == settled
    assert registry.command(screen.id, "volume", value=30, command_id="V") == volume


@pytest.mark.parametrize("kwargs", [
    {"action": "explode"},
    {"action": "volume", "value": 101},
    {"action": "volume", "value": True},
    {"action": "seek", "value": -1},
    {"action": "seek", "value": float("nan")},
    {"action": "seek", "value": "7"},
    {"action": "pause"},                      # nothing loaded yet
    {"action": "play", "item": "../etc"},
    {"action": "play", "item": ""},
    {"action": "play", "item": "ok", "command_id": "bad id!"},
])
def test_invalid_commands_are_rejected_without_side_effects(registry, kwargs):
    screen = make(registry)
    kwargs = dict(kwargs, suffix=".mp4")
    action = kwargs.pop("action")
    with pytest.raises(screens.ScreenError) as info:
        registry.command(screen.id, action, **kwargs)
    assert info.value.status in {400, 409}
    assert registry.poll(screen.id, "k1", 0)["orders"] == []


def test_stop_clears_state_and_fences_late_reports(registry):
    screen = make(registry)
    play(registry, screen, follow=True)
    registry.command(screen.id, "stop")
    # A report about the play that was running before the stop must be ignored.
    registry.report(screen.id, "k1", {"state": "playing", "position": 9,
                                      "play_seq": 1})
    row = registry.snapshot()[0]
    assert row["state"] == "idle" and row["item"] == "" and row["follow"] is False


def test_a_late_report_cannot_overwrite_a_newer_play(registry):
    screen = make(registry)
    play(registry, screen, item="one")
    play(registry, screen, item="two")
    before = registry.snapshot()[0]
    registry.report(screen.id, "k1", {
        "state": "error", "play_seq": 1, "position": 51,
        "duration": 999, "volume": 7, "error": "old film failed",
    })
    after = registry.snapshot()[0]
    for field in ("state", "position", "duration", "volume", "error", "item"):
        assert after[field] == before[field]


def test_missing_or_invalid_generation_is_ignored_after_play_and_stop(registry, clock):
    screen = make(registry)
    play(registry, screen, item="one")
    play(registry, screen, item="two")
    before = registry.snapshot()[0]
    last_seen = screen.last_seen
    last_seen = screen.last_seen
    clock.now += 5
    registry.report(screen.id, "k1", {
        "state": "error", "position": 41, "duration": 500,
        "volume": 2, "error": "ambiguous report",
    })
    after = registry.snapshot()[0]
    for field in ("state", "position", "duration", "volume", "error", "item"):
        assert after[field] == before[field]
    assert screen.last_seen > last_seen

    registry.command(screen.id, "stop")
    stopped = registry.snapshot()[0]
    registry.report(screen.id, "k1", {
        "state": "error", "play_seq": 2, "position": 8,
        "duration": 100, "volume": 3, "error": "before stop",
    })
    assert registry.snapshot()[0]["state"] == stopped["state"]
    registry.report(screen.id, "k1", {
        "state": "error", "play_seq": 3, "position": 8,
        "duration": 100, "volume": 3, "error": "after stop",
    })
    assert registry.snapshot()[0]["state"] == "error"


def test_report_validation(registry):
    screen = make(registry)
    for bad in (None, [], {"state": "exploding"}, {}):
        with pytest.raises(screens.ScreenError) as info:
            registry.report(screen.id, "k1", bad)
        assert info.value.status == 400
    registry.report(screen.id, "k1", {"state": "playing", "position": float("inf"),
                                      "duration": -4, "volume": 500, "ack": 99})
    row = registry.snapshot()[0]
    assert row["position"] == 0 and row["duration"] == 0 and row["volume"] == 100


def test_error_text_is_bounded_and_cleared_on_recovery(registry):
    screen = make(registry)
    registry.report(screen.id, "k1", {"state": "error", "error": "x\x00" + "y" * 400})
    assert len(registry.snapshot()[0]["error"]) == 120
    registry.report(screen.id, "k1", {"state": "playing"})
    assert registry.snapshot()[0]["error"] == ""


# -- following the shared queue -------------------------------------------

def test_following_screen_asks_for_the_next_item_exactly_once(registry):
    screen = make(registry)
    play(registry, screen, item="one", follow=True)
    registry.report(screen.id, "k1", {"state": "playing", "play_seq": 1})
    first = registry.report(screen.id, "k1", {"state": "ended", "play_seq": 1})
    assert first["advance"] == "one"
    duplicate = registry.report(screen.id, "k1", {"state": "ended", "play_seq": 1})
    assert duplicate["advance"] == ""        # a retried report cannot double-skip


def test_non_following_screen_never_advances(registry):
    screen = make(registry)
    play(registry, screen, item="one", follow=False)
    assert registry.report(screen.id, "k1", {"state": "ended", "play_seq": 1})["advance"] == ""


# -- route selection -------------------------------------------------------

@pytest.mark.parametrize("suffix,caps,mode,mime", [
    (".mp4", {"video/mp4"}, "direct", "video/mp4"),
    (".MP4", {"video/mp4"}, "direct", "video/mp4"),
    (".mkv", {"video/x-matroska"}, "direct", "video/x-matroska"),
    (".mkv", {"video/mp4"}, "transcode", "video/mp4"),
    (".avi", {"video/mp4", "video/webm"}, "transcode", "video/mp4"),
    (".flac", {"audio/flac"}, "direct", "audio/flac"),
    (".flac", set(), "transcode", "audio/mp4"),
    (".aiff", {"audio/mpeg"}, "transcode", "audio/mp4"),
])
def test_route_prefers_direct_play_and_falls_back_to_conversion(suffix, caps, mode, mime):
    route = screens.choose_route(suffix, caps, can_transcode=True)
    assert (route.mode, route.mime) == (mode, mime)
    assert (route.reason != "") == (mode == "transcode")


def test_route_fails_clearly_without_ffmpeg_or_for_non_media():
    with pytest.raises(screens.ScreenError) as info:
        screens.choose_route(".mkv", {"video/mp4"}, can_transcode=False)
    assert info.value.status == 415 and "FFmpeg" in info.value.message
    for suffix in (".exe", ".txt", "", ".py"):
        with pytest.raises(screens.ScreenError) as info:
            screens.choose_route(suffix, {"video/mp4"}, can_transcode=True)
        assert info.value.status == 415


def test_play_order_carries_primary_and_fallback_urls(registry):
    screen = make(registry, caps=["video/mp4"])
    order = play(registry, screen, item="vid", suffix=".mp4")
    assert order["seq"] == 1
    sent = registry.poll(screen.id, "k1", 0)["orders"][0]
    assert sent["url"] == "/api/media/vid" and sent["fallback"].endswith("?mode=transcode")
    play(registry, screen, item="old", suffix=".avi")
    converted = registry.poll(screen.id, "k1", 1)["orders"][0]
    assert converted["url"].endswith("?mode=transcode") and converted["fallback"] == ""
    assert "/" not in converted["item"] and ".." not in converted["url"]


def test_no_fallback_offered_when_host_cannot_convert(clock):
    registry = screens.ScreenRegistry(clock=clock, can_transcode=lambda: False)
    screen = make(registry, caps=["video/mp4"])
    play(registry, screen, suffix=".mp4")
    assert registry.poll(screen.id, "k1", 0)["orders"][0]["fallback"] == ""


# -- long polling ----------------------------------------------------------

def test_long_poll_wakes_immediately_for_a_new_order():
    registry = screens.ScreenRegistry(can_transcode=lambda: True)
    screen = make(registry)
    results = []
    thread = threading.Thread(target=lambda: results.append(
        registry.poll(screen.id, "k1", 0, wait=5.0)))
    thread.start()
    play(registry, screen)
    thread.join(2)
    assert not thread.is_alive()
    assert results[0]["orders"][0]["kind"] == "play"


def test_long_poll_returns_empty_at_the_deadline_and_close_wakes_pollers():
    registry = screens.ScreenRegistry(can_transcode=lambda: True)
    screen = make(registry)
    assert registry.poll(screen.id, "k1", 0, wait=0.05)["orders"] == []
    results = []

    def waiter():
        try:
            registry.poll(screen.id, "k1", 0, wait=5.0)
        except screens.ScreenError as exc:
            results.append(exc.status)
    thread = threading.Thread(target=waiter)
    thread.start()
    registry.close()
    thread.join(2)
    assert results == [404]


def test_hundreds_of_concurrent_commands_keep_sequence_unique(registry):
    screen = make(registry)
    errors = []

    def hammer():
        try:
            for _ in range(50):
                registry.command(screen.id, "volume", value=10)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)
    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors
    live = registry.get(screen.id)
    assert live.seq == 400
    seqs = [o["seq"] for o in live.orders]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert len(seqs) <= screens.MAX_PENDING_ORDERS
