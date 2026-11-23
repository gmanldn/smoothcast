"""Receiver-confirmed command traces: mock backend/SOAP, no desktop or LAN IO."""
from unittest import mock
from xml.etree import ElementTree as ET

import pytest

import castctl
import command_trace
import dlna


def _stages(trace):
    rows = [row for row in command_trace.recent() if row["id"] == trace.id]
    assert len(rows) == 1
    return [event["stage"] for event in rows[0]["stages"]]


def _renderer():
    return dlna.Renderer(
        name="Private TV", host="192.168.3.88", location="",
        transport_url="http://192.168.3.88:1234/upnp",
        transport_service="urn:schemas-upnp-org:service:AVTransport:1",
    )


def test_cast_ack_requires_matching_receiver_observation():
    backend = mock.Mock()
    backend.command.return_value = (True, "accepted")
    backend.info.return_value = {"player_state": "PAUSED"}
    with mock.patch.object(castctl, "_backend", backend):
        with command_trace.scope("portal", "play_pause") as trace:
            assert castctl.pause("private-receiver") == (True, "accepted")
            assert "receiver_confirmed" not in _stages(trace)
            assert castctl.info("foreign-receiver") == {"player_state": "PAUSED"}
            assert "receiver_confirmed" not in _stages(trace)
            assert castctl.info("private-receiver") == {"player_state": "PAUSED"}
    assert _stages(trace).count("receiver_confirmed") == 1
    assert "private-receiver" not in str(command_trace.recent())


def test_rejected_cast_call_cannot_later_be_confirmed():
    backend = mock.Mock()
    backend.command.return_value = (False, "private failure detail")
    backend.info.return_value = {"player_state": "PAUSED"}
    with mock.patch.object(castctl, "_backend", backend):
        with command_trace.scope("cli", "pause") as trace:
            assert castctl.command("private", "pause")[0] is False
            castctl.info("private")
    assert "receiver_failed" in _stages(trace)
    assert "receiver_confirmed" not in _stages(trace)
    assert "private failure detail" not in str(command_trace.recent())


def test_dlna_pause_is_ack_only_until_status_confirms_it():
    renderer = _renderer()
    ack = ET.Element("ack")
    state = ET.fromstring(
        "<Root><CurrentTransportState>PAUSED_PLAYBACK</CurrentTransportState></Root>"
    )
    with mock.patch.object(dlna, "_soap", side_effect=[ack, state, ET.Element("pos")]) as soap:
        with command_trace.scope("desktop", "play_pause") as trace:
            dlna.pause(renderer)
            assert "receiver_call" in _stages(trace)
            assert "receiver_ack" in _stages(trace)
            assert "receiver_confirmed" not in _stages(trace)
            assert dlna.info(renderer)["player_state"] == "PAUSED"
    assert [call.args[1] for call in soap.call_args_list] == [
        "Pause", "GetTransportInfo", "GetPositionInfo",
    ]
    assert _stages(trace).count("receiver_confirmed") == 1
    assert renderer.name not in str(command_trace.recent())
    assert renderer.host not in str(command_trace.recent())


def test_dlna_unknown_state_cannot_confirm_stop():
    renderer = _renderer()
    with mock.patch.object(dlna, "_soap", side_effect=[
        ET.Element("ack"),
        ET.fromstring("<Root><CurrentTransportState>UNRECOGNISED</CurrentTransportState></Root>"),
        ET.Element("pos"),
    ]):
        with command_trace.scope("desktop", "stop") as trace:
            dlna.stop(renderer)
            assert dlna.info(renderer)["player_state"] == "UNKNOWN"
    assert "receiver_ack" in _stages(trace)
    assert "receiver_confirmed" not in _stages(trace)


def test_dlna_soap_failure_records_code_without_private_exception():
    renderer = _renderer()
    with mock.patch.object(dlna, "_soap", side_effect=dlna.DlnaError("/private/film.mkv")):
        with command_trace.scope("desktop", "play_pause") as trace:
            with pytest.raises(dlna.DlnaError):
                dlna.play(renderer)
    assert "receiver_failed" in _stages(trace)
    assert "receiver_ack" not in _stages(trace)
    assert "/private/film.mkv" not in str(command_trace.recent())
    assert any(item.get("code") == 502
               for item in next(row for row in command_trace.recent()
                                if row["id"] == trace.id)["stages"])


def test_stale_duplicate_or_other_receiver_is_never_confirmed():
    with command_trace.scope("portal", "play_pause") as trace:
        command_trace.expect_receiver("receiver A", "PLAYING")
        command_trace.observe_receiver("receiver B", "PLAYING")
        command_trace.observe_receiver("receiver A", "UNKNOWN")
        assert "receiver_confirmed" not in _stages(trace)
        command_trace.observe_receiver("receiver A", "PAUSED")
        command_trace.observe_receiver("receiver A", "PAUSED")
        command_trace.observe_receiver("receiver A", "PLAYING")
        command_trace.observe_receiver("receiver A", "PLAYING")
    assert _stages(trace).count("unconfirmed") == 1
    assert _stages(trace).count("receiver_confirmed") == 1


def test_old_or_replaced_expectation_cannot_confirm():
    with command_trace.scope("portal", "play_pause") as trace:
        command_trace.expect_receiver("receiver A", "PAUSED")
        with mock.patch.object(command_trace.time, "monotonic", return_value=999999999):
            command_trace.observe_receiver("receiver A", "PAUSED")
        command_trace.expect_receiver("receiver A", "PAUSED")
        command_trace.clear_receiver_expectation()
        command_trace.observe_receiver("receiver A", "PAUSED")
    assert "receiver_confirmed" not in _stages(trace)
    assert _stages(trace).count("unconfirmed") == 1
