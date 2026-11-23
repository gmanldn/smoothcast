"""Command correlation without GTK, LAN, media or real receiver calls."""
from concurrent.futures import ThreadPoolExecutor
import re

import command_trace


def test_opaque_identifier_and_privacy_scrubbed_export():
    title = "/home/private/Movies/secret-title.mkv"
    with command_trace.scope("portal", "play_pause", command_id=title,
                             client_id="guest.email") as rec:
        assert re.fullmatch(r"[0-9a-f]{24}", rec.id)
        assert command_trace.current_id() == rec.id
        command_trace.stage("fenced")
        command_trace.stage("receiver_failed", code=502)
    assert command_trace.current_id() is None
    data = next(x for x in command_trace.recent() if x["id"] == rec.id)
    assert data["source"] == "portal" and data["action"] == "play_pause"
    assert [s["stage"] for s in data["stages"]] == [
        "received", "fenced", "receiver_failed", "completed",
    ]
    assert data["stages"][2]["code"] == 502
    assert "secret-title" not in str(data) and "guest.email" not in str(data)


def test_same_command_id_is_one_trace_and_bad_stage_is_rejected():
    with command_trace.scope("portal", "stop", command_id="duplicate",
                             client_id="same") as first:
        command_trace.stage("unknown_stage")
        command_trace.stage("dispatched")
    with command_trace.scope("portal", "stop", command_id="duplicate",
                             client_id="same") as second:
        command_trace.stage("receiver_ack")
    assert first is second
    events = [v["stage"] for v in command_trace.recent()[-1]["stages"]]
    assert "replayed" in events and "unknown_stage" not in events


def test_nested_scopes_and_cross_thread_propagation():
    with command_trace.scope("cli", "seek") as current:
        def task():
            assert command_trace.current_id() == current.id
            with command_trace.scope("desktop", "play_pause"):
                command_trace.stage("receiver_call")
            return command_trace.current_id()
        wrapped = command_trace.propagate(task)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert pool.submit(wrapped).result(timeout=2) == current.id
            assert pool.submit(wrapped).result(timeout=2) == current.id
    assert command_trace.current_id() is None
    assert any(e["stage"] == "receiver_call"
               for e in command_trace.recent()[-1]["stages"])


def test_failures_capture_status_but_never_exception_text():
    class Failure(RuntimeError):
        status = 409

    with command_trace.scope("cli", "resume") as record:
        try:
            raise Failure("/private/secret")
        except Failure as err:
            command_trace.stage("rejected", code=err.status)
    assert record.id
    assert "/private/secret" not in str(command_trace.recent())
    assert any(e.get("code") == 409 for e in command_trace.recent()[-1]["stages"])


def test_stage_memory_bounded_and_export_detached():
    with command_trace.scope("desktop", "seek") as record:
        for _ in range(command_trace.MAX_STAGES + 12):
            command_trace.stage("dispatched")
    assert len(record.stages) <= command_trace.MAX_STAGES
    saved = command_trace.recent(999)
    assert len(saved) <= command_trace.MAX_EXPORT
    saved[-1]["stages"][0]["stage"] = "corrupted"
    assert command_trace.recent()[-1]["stages"][0]["stage"] != "corrupted"
    assert command_trace.recent(-1) == []


def test_traced_desktop_handler_and_portal_reuse():
    @command_trace.traced("desktop", "stop")
    def stop():
        command_trace.stage("dispatched")
        return command_trace.current_id()

    local = stop()
    assert local and command_trace.current_id() is None
    with command_trace.scope("portal", "stop", command_id="req22",
                             client_id="guest22") as trace:
        assert stop() == trace.id
        command_trace.stage("receiver_call")
    assert trace.id != local
