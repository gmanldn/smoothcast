"""Deterministic GTK-free tests for portal command fencing and idempotency."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal_commands as commands


SESSION = "0" * 32


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def envelope(*, action="stop", payload=None, session_id=SESSION, revision=0,
             client_id="phone", command_id="cmd"):
    return commands.MutationEnvelope(
        client_id=client_id, command_id=command_id,
        expected_session_id=session_id, expected_revision=revision,
        action=action, payload=payload or {})


class FakeWindow:
    def __init__(self, fence):
        self._portal_fence = fence
        self._closing = False
        self.busy = False
        self.session = SimpleNamespace(state=object())
        self.external = False
        self.tracker = SimpleNamespace(known=True, duration=100.0)
        self.device_state = "PLAYING"
        self._preview_path = None
        self._dlna_cancel = None
        self.calls = []
        self.volume_scale = SimpleNamespace(
            set_value=lambda value: self.calls.append(("volume", value)))

    def _device(self):
        return "TV"

    def _volume_control_available(self):
        return True

    def toggle_play(self):
        self.calls.append("play_pause")

    def stop_stream(self):
        self.calls.append("stop")

    def seek_to(self, value):
        self.calls.append(("seek", value))


def test_parse_envelope_returns_none_for_legacy_body():
    assert commands.parse_envelope({"action": "stop"}) is None


def test_parse_envelope_accepts_bounded_seek():
    body = {"client_id": "phone", "command_id": "cmd",
            "expected_session_id": SESSION, "expected_revision": 2,
            "action": "seek", "payload": {"value": 12.5}}
    parsed = commands.parse_envelope(body)
    assert parsed is not None
    assert parsed.action == "seek" and parsed.payload == {"value": 12.5}


@pytest.mark.parametrize("body", [
    {"client_id": "phone"},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "stop", "payload": {}, "extra": 1},
    {"client_id": "bad id", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "stop", "payload": {}},
    {"client_id": "phone", "command_id": "x" * 200, "expected_session_id": SESSION,
     "expected_revision": 0, "action": "stop", "payload": {}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": "abc",
     "expected_revision": 0, "action": "stop", "payload": {}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": True, "action": "stop", "payload": {}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "cast", "payload": {}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "stop", "payload": {"value": 1}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "seek", "payload": {"value": float("nan")}},
    {"client_id": "phone", "command_id": "cmd", "expected_session_id": SESSION,
     "expected_revision": 0, "action": "volume", "payload": {"value": 101}},
])
def test_parse_envelope_rejects_invalid_bodies(body):
    with pytest.raises(commands.CommandError):
        commands.parse_envelope(body)


def test_fence_rotates_when_media_generation_changes():
    state = {"film": "A", "device": "TV"}
    fence = commands.CommandFence(
        generation=lambda: state["film"], owner=lambda: state["device"])
    session, revision, _ = fence.snapshot()
    state["film"] = "B"
    with pytest.raises(commands.CommandError) as error:
        fence.check(session, revision, owner="TV")
    assert error.value.status == 409
    new_session, new_revision, _ = fence.snapshot()
    fence.check(new_session, new_revision, owner="TV")


def test_fence_rotates_when_owner_changes():
    state = {"device": "TV"}
    fence = commands.CommandFence(owner=lambda: state["device"])
    session, revision, _ = fence.snapshot()
    state["device"] = "Other TV"
    with pytest.raises(commands.CommandError):
        fence.check(session, revision, owner="Other TV")
    new_session, new_revision, _ = fence.snapshot()
    fence.check(new_session, new_revision, owner="Other TV")


def test_fence_rejects_stale_generation_and_foreign_owner():
    fence = commands.CommandFence(clock=Clock())
    session_id, revision, _ = fence.snapshot()
    fence.rotate(owner="TV")
    with pytest.raises(commands.CommandError) as error:
        fence.check(session_id, revision)
    assert error.value.status == 409 and error.value.revision == 1
    new_session, new_revision, _ = fence.snapshot()
    fence.check(new_session, new_revision, owner="TV")
    with pytest.raises(commands.CommandError):
        fence.check(new_session, new_revision, owner="Other TV")


def test_duplicate_command_returns_original_receipt_and_altered_replay_fails():
    fence = commands.CommandFence()
    calls = []

    def dispatch(item):
        calls.append(item)
        return commands.CommandReceipt(item.command_id, SESSION, 0, "accepted")

    dispatcher = commands.CommandDispatcher(dispatch, fence=fence)
    try:
        first = envelope(action="seek", payload={"value": 1})
        one = dispatcher.execute(first)
        two = dispatcher.execute(first)
        assert one == two and len(calls) == 1
        altered = envelope(action="seek", payload={"value": 2})
        with pytest.raises(commands.CommandError) as error:
            dispatcher.execute(altered)
        assert error.value.status == 409 and len(calls) == 1
    finally:
        dispatcher.close()


def test_concurrent_duplicate_waits_for_original_receipt():
    fence = commands.CommandFence()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def dispatch(item):
        calls.append(item)
        started.set()
        assert release.wait(2)
        return commands.CommandReceipt(item.command_id, SESSION, 0, "accepted")

    dispatcher = commands.CommandDispatcher(dispatch, fence=fence)
    try:
        item = envelope()
        results = []
        errors = []

        def run():
            try:
                results.append(dispatcher.execute(item))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=run)
        first.start()
        assert started.wait(2)
        second = threading.Thread(target=run)
        second.start()
        time.sleep(0.05)
        assert len(calls) == 1
        release.set()
        first.join(2)
        second.join(2)
        assert not errors and len(results) == 2 and results[0] == results[1]
    finally:
        dispatcher.close()


def test_concurrent_distinct_commands_are_serialized():
    fence = commands.CommandFence()
    active = 0
    peak = 0
    order = []
    lock = threading.Lock()

    def dispatch(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            order.append(item.command_id)
        time.sleep(0.02)
        with lock:
            active -= 1
        return commands.CommandReceipt(item.command_id, SESSION, 0, "accepted")

    dispatcher = commands.CommandDispatcher(dispatch, fence=fence, per_client_cap=8)
    try:
        threads = [threading.Thread(target=dispatcher.execute,
                                    args=(envelope(command_id=f"c{i}"),))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        assert peak == 1
        assert len(order) == 8
    finally:
        dispatcher.close()


def test_timed_out_command_never_returns_success():
    fence = commands.CommandFence()

    def dispatch(_item):
        raise commands.CommandError(503, "SmoothCast did not respond in time")

    dispatcher = commands.CommandDispatcher(dispatch, fence=fence)
    try:
        with pytest.raises(commands.CommandError) as error:
            dispatcher.execute(envelope())
        assert error.value.status == 503
        with pytest.raises(commands.CommandError):
            dispatcher.execute(envelope())
    finally:
        dispatcher.close()


def test_receipt_cache_expires_and_is_bounded():
    clock = Clock()
    fence = commands.CommandFence(clock=clock)
    calls = []

    def dispatch(item):
        calls.append(item.command_id)
        return commands.CommandReceipt(item.command_id, SESSION, 0, "accepted")

    dispatcher = commands.CommandDispatcher(dispatch, fence=fence, clock=clock,
                                            ttl=10.0, capacity=2)
    try:
        for index in range(3):
            dispatcher.execute(envelope(command_id=f"c{index}"))
        assert len(calls) == 3
        dispatcher.execute(envelope(command_id="c0"))
        assert calls.count("c0") == 2
        clock.now = 11.0
        dispatcher.execute(envelope(command_id="c2"))
        assert calls.count("c2") == 2
    finally:
        dispatcher.close()


@pytest.mark.parametrize("action,payload,expected", [
    ("play_pause", {}, ["play_pause"]),
    ("stop", {}, ["stop"]),
    ("seek", {"value": 12.5}, [("seek", 12.5)]),
    ("volume", {"value": 40}, [("volume", 40)]),
])
def test_run_mutation_applies_valid_actions(action, payload, expected):
    fence = commands.CommandFence()
    window = FakeWindow(fence)
    session_id, revision, _ = fence.snapshot()
    receipt = commands.run_mutation(
        window, fence, envelope(action=action, payload=payload,
                                session_id=session_id, revision=revision))
    assert window.calls == expected
    assert receipt.command_id == "cmd"


def test_run_mutation_rejects_stale_session_before_effects():
    fence = commands.CommandFence()
    window = FakeWindow(fence)
    old_session, old_revision, _ = fence.snapshot()
    fence.rotate(owner="TV")
    with pytest.raises(commands.CommandError) as error:
        commands.run_mutation(window, fence,
                              envelope(session_id=old_session, revision=old_revision))
    assert error.value.status == 409 and window.calls == []


def test_run_mutation_rejects_foreign_owner_before_effects():
    fence = commands.CommandFence()
    fence.rotate(owner="Other TV")
    window = FakeWindow(fence)
    session_id, revision, _ = fence.snapshot()
    with pytest.raises(commands.CommandError):
        commands.run_mutation(window, fence,
                              envelope(session_id=session_id, revision=revision))
    assert window.calls == []


def test_run_mutation_rejects_busy_or_closing_before_effects():
    fence = commands.CommandFence()
    window = FakeWindow(fence)
    session_id, revision, _ = fence.snapshot()
    window.busy = True
    with pytest.raises(commands.CommandError) as error:
        commands.run_mutation(window, fence,
                              envelope(session_id=session_id, revision=revision))
    assert error.value.status == 409 and window.calls == []
    window.busy = False
    window._closing = True
    with pytest.raises(commands.CommandError) as error:
        commands.run_mutation(window, fence,
                              envelope(session_id=session_id, revision=revision))
    assert error.value.status == 503 and window.calls == []


def test_reordered_commands_cannot_touch_the_new_generation():
    fence = commands.CommandFence()
    window = FakeWindow(fence)
    old_session, old_revision, _ = fence.snapshot()
    fence.rotate(owner="TV")
    new_session, new_revision, _ = fence.snapshot()
    commands.run_mutation(window, fence,
                          envelope(command_id="new", session_id=new_session,
                                   revision=new_revision))
    with pytest.raises(commands.CommandError):
        commands.run_mutation(window, fence,
                              envelope(command_id="old", session_id=old_session,
                                       revision=old_revision))
    assert window.calls == ["stop"]


def test_dispatcher_rejects_when_queue_is_full():
    fence = commands.CommandFence()
    started = threading.Event()
    release = threading.Event()

    def apply(_item):
        started.set()
        assert release.wait(2)
        return commands.CommandReceipt("one", SESSION, 0, "ok")

    dispatcher = commands.CommandDispatcher(apply, fence=fence, queue_capacity=1)
    try:
        first = threading.Thread(target=dispatcher.execute,
                                 args=(envelope(command_id="one"),))
        first.start()
        assert started.wait(2)
        with pytest.raises(commands.CommandError) as error:
            dispatcher.execute(envelope(command_id="two"))
        assert error.value.status == 503
        release.set()
        first.join(2)
    finally:
        dispatcher.close()


def test_precheck_rejects_before_dispatch():
    fence = commands.CommandFence(owner=lambda: "TV")
    session_id, revision, _owner = fence.snapshot()
    item = envelope(session_id=session_id, revision=revision)
    commands.precheck(FakeWindow(fence), fence, item)
    closed = FakeWindow(fence)
    closed._closing = True
    with pytest.raises(commands.CommandError) as error:
        commands.precheck(closed, fence, item)
    assert error.value.status == 503
    with pytest.raises(commands.CommandError) as error:
        commands.precheck(FakeWindow(fence), None, item)
    assert error.value.status == 503
    foreign = FakeWindow(fence)
    foreign._device = lambda: "Other TV"
    with pytest.raises(commands.CommandError) as error:
        commands.precheck(foreign, fence, item)
    assert error.value.status == 409


def test_participant_buckets_limit_a_flood_without_starving_other_guests():
    clock = Clock()
    limiter = commands.ParticipantRateLimiter(clock=clock)
    allowed = sum(limiter.retry_after("noisy", "mutation") == 0 for _ in range(500))
    assert allowed == 12  # whole flood arrived in a single simulated second
    assert limiter.retry_after("noisy", "mutation") > 0
    assert limiter.retry_after("quiet", "mutation") == 0
    assert limiter.retry_after("noisy", "read") == 0
    clock.now += 1
    assert sum(limiter.retry_after("noisy", "mutation") == 0 for _ in range(7)) == 6


def test_rate_limiter_bounds_memory_and_does_not_trust_clock_going_backwards():
    clock = Clock()
    limiter = commands.ParticipantRateLimiter(
        clock=clock, limits={"read": (1.0, 2.0)}, max_buckets=3,
    )
    for i in range(100):
        assert limiter.retry_after(str(i), "read") == 0
    assert len(limiter._buckets) == 3
    assert limiter.retry_after("99", "read") > 0
    clock.now = -10
    assert limiter.retry_after("99", "read") > 0
    clock.now = 1
    assert limiter.retry_after("99", "read") == 0


def test_per_participant_command_cap_preserves_a_second_guests_admission():
    fence = commands.CommandFence()
    running = threading.Event()
    release = threading.Event()
    completed = []
    failures = []

    def dispatch(item):
        if item.client_id == "flood0":
            running.set()
            assert release.wait(2)
        completed.append(item.client_id)
        return commands.CommandReceipt(item.command_id, SESSION, 0, "ok")

    dispatcher = commands.CommandDispatcher(
        dispatch, fence=fence, queue_capacity=2, per_client_cap=1,
    )
    try:
        def first():
            try:
                dispatcher.execute(envelope(client_id="flood0", command_id="a"),
                                   participant_key="same-guest")
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=first)
        thread.start()
        assert running.wait(2)
        for i in range(500):
            # A guest cannot evade the cap by supplying fresh envelope client_ids.
            with pytest.raises(commands.CommandError) as exc:
                dispatcher.execute(envelope(client_id=f"flood{i+1}", command_id=f"c{i}"),
                                   participant_key="same-guest")
            assert exc.value.status == 429
        other = threading.Thread(target=lambda: dispatcher.execute(
            envelope(client_id="quiet", command_id="b"), participant_key="quiet-guest"))
        other.start()
        release.set()
        thread.join(2)
        other.join(2)
        assert not thread.is_alive() and not other.is_alive()
        assert not failures
        assert completed == ["flood0", "quiet"]
    finally:
        release.set()
        dispatcher.close()
