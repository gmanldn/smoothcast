"""Documented model-profile limits and Cast-compatible rejection responses."""
from __future__ import annotations

import json
import struct
import subprocess
import sys

import pytest

from fakecast import FakeCastReceiver
from fakecast.profiles import PROFILES
from fakecast.receiver import CastMessage, MEDIA_SRC_NOT_SUPPORTED, NS_MEDIA


class RecordingClient:
    def __init__(self):
        self.frames: list[bytes] = []

    def sendall(self, frame: bytes) -> None:
        self.frames.append(frame)


def request() -> CastMessage:
    message = CastMessage()
    message.protocol_version = CastMessage.CASTV2_1_0
    message.source_id = "sender-0"
    message.destination_id = "receiver-0"
    message.payload_type = CastMessage.STRING
    message.namespace = NS_MEDIA
    message.payload_utf8 = json.dumps({"type": "LOAD", "requestId": 1})
    return message


def response(client: RecordingClient) -> dict:
    frame = client.frames[-1]
    size = struct.unpack(">I", frame[:4])[0]
    message = CastMessage()
    message.ParseFromString(frame[4:4 + size])
    return json.loads(message.payload_utf8)


CASES = (
    (
        "chromecast-gen2",
        {"codec": "h264", "profile": "high", "level": "4.1",
         "width": 1920, "height": 1080, "fps": 30},
        {"codec": "h264", "profile": "high", "level": "4.2",
         "width": 1920, "height": 1080, "fps": 30},
    ),
    (
        "chromecast-gen3",
        {"codec": "h264", "profile": "high", "level": "4.2",
         "width": 1920, "height": 1080, "fps": 60},
        {"codec": "h264", "profile": "high", "level": "4.3",
         "width": 1920, "height": 1080, "fps": 60},
    ),
    (
        "chromecast-ultra",
        {"codec": "h265", "profile": "main10", "level": "5.1",
         "width": 3840, "height": 2160, "fps": 60},
        {"codec": "h265", "profile": "main10", "level": "5.2",
         "width": 3840, "height": 2160, "fps": 60},
    ),
    (
        "chromecast-with-google-tv",
        {"codec": "vp9", "profile": "2", "level": "5.1",
         "width": 3840, "height": 2160, "fps": 60},
        {"codec": "h265", "profile": "main10", "level": "5.2",
         "width": 3840, "height": 2160, "fps": 60},
    ),
    (
        "google-tv-streamer",
        {"codec": "av1", "profile": "main", "level": "5.1",
         "width": 3840, "height": 2160, "fps": 60},
        {"codec": "av1", "profile": "main", "level": "5.2",
         "width": 3840, "height": 2160, "fps": 60},
    ),
)


@pytest.mark.parametrize("profile,accepted,rejected", CASES)
def test_each_documented_receiver_profile_accepts_limit_and_rejects_out_of_spec(
    profile: str, accepted: dict, rejected: dict,
):
    assert profile in PROFILES
    receiver = FakeCastReceiver(profile=profile)
    accepted_client = RecordingClient()
    accepted_request = request()
    accepted_data = {
        "type": "LOAD",
        "itemId": 1,
        "media": {
            "contentId": "http://127.0.0.1/movie.mp4",
            "contentType": "video/mp4",
            "customData": {"fakeStream": accepted},
        },
    }
    receiver._media_command(accepted_client, accepted_request, accepted_data)
    assert response(accepted_client)["type"] == "MEDIA_STATUS"

    rejected_client = RecordingClient()
    rejected_request = request()
    rejected_data = {
        **accepted_data,
        "media": {
            **accepted_data["media"],
            "customData": {"fakeStream": rejected},
        },
    }
    receiver._media_command(rejected_client, rejected_request, rejected_data)
    failed = response(rejected_client)
    assert failed["type"] == "LOAD_FAILED"
    assert failed["detailedErrorCode"] == MEDIA_SRC_NOT_SUPPORTED
    assert failed["itemId"] == 1


def test_chromecast_gen2_allows_1080p30_but_rejects_1080p60():
    receiver = FakeCastReceiver(profile="chromecast-gen2")
    client = RecordingClient()
    data = {
        "type": "LOAD",
        "itemId": 1,
        "media": {"customData": {"fakeStream": {
            "codec": "h264", "profile": "high", "level": "4.1",
            "width": 1920, "height": 1080, "fps": 60,
        }}},
    }
    receiver._media_command(client, request(), data)
    assert response(client)["type"] == "LOAD_FAILED"


def test_generic_profile_does_not_apply_model_limits():
    receiver = FakeCastReceiver()
    client = RecordingClient()
    receiver._media_command(client, request(), {
        "type": "LOAD",
        "itemId": 1,
        "media": {"customData": {"fakeStream": {
            "codec": "unknown", "profile": "none", "level": "99.0",
            "width": 7680, "height": 4320, "fps": 120,
        }}},
    })
    assert response(client)["type"] == "MEDIA_STATUS"


def test_standalone_cli_accepts_the_documented_chromecast_gen2_profile():
    result = subprocess.run(
        [sys.executable, "-m", "fakecast", "--profile", "chromecast-gen2", "--help"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "chromecast-gen2" in result.stdout
