"""End-to-end trace coverage on fake receivers; never start GTK or control a TV."""
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace
from unittest import mock

import pytest

import async_jobs
import castctl
import command_trace
import diagnostics
import error_log
import portal_commands

ROOT = Path(__file__).resolve().parents[1]


def test_receiver_rejection_has_one_correlated_trace_with_every_failure_stage():
    fence = portal_commands.CommandFence()
    session, revision, _ = fence.snapshot()

    def toggle():
        ok, _response = castctl.command("Private receiver name", "pause")
        assert not ok
        raise portal_commands.CommandError(502, "Receiver refused the action")

    controller = SimpleNamespace(
        _closing=False, busy=False, _device=lambda: "Receiver",
        play_button=SimpleNamespace(get_sensitive=lambda: True),
        toggle_play=toggle,
    )
    env = portal_commands.MutationEnvelope(
        client_id="guest-device", command_id="trace-command-1",
        expected_session_id=session, expected_revision=revision,
        action="play_pause", payload={},
    )
    dispatcher = portal_commands.CommandDispatcher(
        lambda envelope: portal_commands.run_mutation(controller, fence, envelope),
        fence=fence,
    )
    fake_backend = mock.Mock()
    fake_backend.command.return_value = (False, "Internal receiver detail")
    try:
        with mock.patch.object(castctl, "_backend", fake_backend):
            with pytest.raises(portal_commands.CommandError) as exc:
                dispatcher.execute(env)
        assert exc.value.status == 502
    finally:
        dispatcher.close()
    match = [row for row in command_trace.recent() if row["action"] == "play_pause"]
    assert match
    trace = match[-1]
    stages = [event["stage"] for event in trace["stages"]]
    for expected in ("received", "fenced", "dispatched", "receiver_call",
                     "receiver_failed", "rejected", "completed"):
        assert expected in stages, (expected, stages)
    assert any(e.get("code") == 502 for e in trace["stages"])
    assert "Private receiver name" not in str(trace)
    assert "Internal receiver detail" not in str(trace)
    fake_backend.command.assert_called_once_with("Private receiver name", "pause", timeout=12)


def test_worker_queued_under_command_keeps_trace_on_result_callback():
    callbacks = Queue()
    domain = async_jobs.WorkDomains(lambda cb: callbacks.put(cb),
                                    limits={"transport": (1, 2)})
    result = []
    finished = Event()
    try:
        with command_trace.scope("desktop", "seek") as record:
            def work():
                command_trace.stage("receiver_call")
                return command_trace.current_id()

            def done(value):
                result.append((command_trace.current_id(), value))
                finished.set()

            assert domain.submit(work, done=done, domain="transport")
        callback = callbacks.get(timeout=2)
        callback()
        assert finished.wait(timeout=2)
        assert result == [(record.id, record.id)]
        assert any(e["stage"] == "worker_queued"
                   for e in command_trace.recent()[-1]["stages"])
    finally:
        domain.shutdown()


def test_error_log_and_support_bundle_include_only_opaque_ids(tmp_path):
    with command_trace.scope("cli", "stop") as record:
        log = error_log.ErrorLog(tmp_path / "errors.log")
        log.add("Safe receiver failure")
    assert f"[command:{record.id}]" in log.read()[-1]
    with mock.patch.object(diagnostics, "tool_version", return_value="mock tool"):
        payload = diagnostics.collect(error_log=[], server_log=[], activity=[],
                                      config={}, home=str(tmp_path))
    assert "command_traces" in payload
    assert any(row["id"] == record.id for row in payload["command_traces"])
    assert "Private receiver name" not in str(payload["command_traces"])


def test_cross_context_wiring_and_desktop_handler_boundaries_are_explicit():
    files = {name: (ROOT / "src" / name).read_text(encoding="utf-8")
             for name in ("cast_portal.py", "async_jobs.py", "cast_session.py",
                          "cast_av.py", "cli_control.py", "control_api.py")}
    assert "command_trace.propagate(run)" in files["cast_portal.py"]
    assert "command_trace.propagate(work)" in files["async_jobs.py"]
    assert '@command_trace.traced("desktop", "stop")' in files["cast_session.py"]
    assert '@command_trace.traced("desktop", "play_pause")' in files["cast_session.py"]
    assert '@command_trace.traced("desktop", "seek")' in files["cast_session.py"]
    assert '@command_trace.traced("desktop", "mute")' in files["cast_av.py"]
    assert 'command_trace.scope("cli", args.command)' in files["cli_control.py"]
    assert 'command_trace.scope("control_api", command)' in files["control_api.py"]


def test_legacy_queue_request_and_replay_share_one_privacy_safe_trace():
    import portal

    calls = []
    def dispatch(action, payload):
        calls.append(action)
        return "Queued"

    server = portal._PortalHTTPServer(
        ("127.0.0.1", 0), "234567", dispatch,
    )
    try:
        participant = server.room.join("Guest")
        body = {"action": "queue_clear", "queue_revision": 0,
                "queue_command_id": "opaque-command-7"}
        assert server.execute_queue_command(participant.id, body) == (202, "Queued")
        assert server.execute_queue_command(participant.id, body) == (202, "Queued")
        altered = {**body, "queue_revision": 1}
        assert server.execute_queue_command(participant.id, altered)[0] == 409
        assert calls == ["queue_clear"]
        rows = [row for row in command_trace.recent()
                if row["action"] == "queue_clear" and row["source"] == "portal"]
        assert len(rows) == 1
        stages = [entry["stage"] for entry in rows[0]["stages"]]
        assert "received" in stages and "dispatched" in stages
        assert "replayed" in stages and "rejected" in stages
        assert all(participant.id not in str(row) for row in rows)
    finally:
        server.server_close()


def test_legacy_room_actions_inherit_trace_on_host_dispatch():
    portal_source = (ROOT / "src" / "portal.py").read_text(encoding="utf-8")
    assert 'command_trace.scope("portal", "queue_vote")' in portal_source
    assert 'command_trace.scope("portal", action)' in portal_source
    assert "command_trace.scope(\"portal\", str(action or \"queue\")" in portal_source


def test_worker_failure_log_carries_original_command_trace_id():
    failures = []
    callbacks = Queue()
    domain = async_jobs.WorkDomains(
        lambda callback: callbacks.put(callback),
        on_error=lambda message, *, exc_info=False: failures.append(message),
        limits={"transport": (1, 2)},
    )
    try:
        with command_trace.scope("desktop", "play_pause") as trace:
            def work():
                raise OSError("Private filename should not appear")

            assert domain.submit(work, failed=lambda _message: None,
                                 domain="transport")
        callbacks.get(timeout=2)()
        assert any(f"[command:{trace.id}]" in item for item in failures)
        assert not any("Private filename" in item for item in failures)
    finally:
        domain.shutdown()
