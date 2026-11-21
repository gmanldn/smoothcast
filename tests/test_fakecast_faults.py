"""Deterministic fault controls for the loopback CASTV2 fake."""
from __future__ import annotations

import json
import struct
import time

import pytest

from fakecast import FakeCastReceiver
from fakecast.receiver import CastMessage, NS_HEARTBEAT, NS_MEDIA, NS_RECEIVER


class RecordingClient:
    def __init__(self):
        self.frames: list[bytes] = []
        self.closed = False

    def sendall(self, frame: bytes) -> None:
        self.frames.append(frame)

    def shutdown(self, _how: int) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


def request(namespace: str, message_type: str) -> CastMessage:
    message = CastMessage()
    message.protocol_version = CastMessage.CASTV2_1_0
    message.source_id = "sender-0"
    message.destination_id = "receiver-0"
    message.payload_type = CastMessage.STRING
    message.namespace = namespace
    message.payload_utf8 = json.dumps({"type": message_type})
    return message


def responses(client: RecordingClient) -> list[dict]:
    result = []
    for frame in client.frames:
        size = struct.unpack(">I", frame[:4])[0]
        message = CastMessage()
        message.ParseFromString(frame[4:4 + size])
        result.append(json.loads(message.payload_utf8))
    return result


def test_heartbeat_can_be_suppressed_and_command_faults_are_injectable():
    receiver = FakeCastReceiver()
    client = RecordingClient()
    ping = request(NS_HEARTBEAT, "PING")
    receiver._handle(client, ping, {"type": "PING"})
    assert responses(client)[-1]["type"] == "PONG"

    receiver.answer_heartbeats = False
    receiver._handle(client, ping, {"type": "PING"})
    assert len(responses(client)) == 1

    receiver.delay_command("GET_STATUS", 0.02)
    started = time.monotonic()
    receiver._handle(
        client, request(NS_RECEIVER, "GET_STATUS"), {"type": "GET_STATUS"},
    )
    assert time.monotonic() - started >= 0.015

    receiver.error_command("GET_STATUS", "injected receiver error")
    receiver._handle(
        client, request(NS_RECEIVER, "GET_STATUS"), {"type": "GET_STATUS"},
    )
    assert responses(client)[-1] == {
        "type": "ERROR", "reason": "injected receiver error",
    }

    receiver.drop_connection_on("STOP")
    receiver._handle(client, request(NS_RECEIVER, "STOP"), {"type": "STOP"})
    assert client.closed


def test_stale_media_session_and_unsupported_seek_faults_are_reported():
    receiver = FakeCastReceiver()
    receiver.stale_media_session = True
    receiver.unsupported_seek = True
    client = RecordingClient()
    receiver._media_command(
        client, request(NS_MEDIA, "SEEK"), {"type": "SEEK", "currentTime": 42},
    )
    status = responses(client)[-1]["status"][0]
    assert status["mediaSessionId"] == 0
    assert status["playerState"] == "IDLE"
    assert status["idleReason"] == "ERROR"
    assert status["currentTime"] == 0.0
    assert status["supportedMediaCommands"] == 11


def test_app_crash_fault_ends_the_session_and_reboot_reuses_its_loopback_port():
    with FakeCastReceiver() as receiver:
        port = receiver.port
        with receiver._lock:
            receiver._app_id = "CC1AD845"
            receiver._media_state = "PLAYING"
            receiver._current_time = 42
        receiver.crash_on_commands.add("GET_STATUS")
        client = RecordingClient()
        receiver._handle(
            client, request(NS_RECEIVER, "GET_STATUS"), {"type": "GET_STATUS"},
        )
        assert responses(client)[-1]["status"]["applications"] == []
        assert receiver._media_state == "IDLE"

        receiver.reboot(delay=0)
        assert receiver._listener is not None
        assert receiver.port == port
        assert receiver._app_id is None
        assert receiver._media_state == "IDLE"
        assert receiver._media_session_id == 2


@pytest.mark.parametrize("command,seconds", [("", 1), ("PAUSE", -1), ("PAUSE", 31)])
def test_invalid_delay_configuration_is_rejected(command: str, seconds: float):
    with pytest.raises(ValueError, match="delay from 0 to 30"):
        FakeCastReceiver().delay_command(command, seconds)
