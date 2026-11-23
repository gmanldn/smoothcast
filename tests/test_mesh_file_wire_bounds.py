"""Reject hostile HTTP byte lengths before numeric conversion (#567)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_file_wire import MAX_MEDIA_BYTES, _matches_request, _valid_resume, parse_wire_uint


@pytest.mark.parametrize("value,expected", [
    ("0", 0), ("19", 19), (str(MAX_MEDIA_BYTES), MAX_MEDIA_BYTES),
    (str(MAX_MEDIA_BYTES + 1), None), ("9" * 20, None), ("9" * 10000, None),
    ("", None), (None, None), ("-1", None), ("+1", None),
    ("01x", None), ("١٢", None), (" 1", None),
])
def test_peer_decimal_is_bounded_before_int_conversion(value, expected):
    assert parse_wire_uint(value) == expected


@pytest.mark.parametrize("range_header", [
    "bytes=" + "9" * 10000 + "-", "bytes=0-" + "9" * 10000,
    "bytes=-" + "9" * 10000, "bytes=9223372036854775808-",
    "bytes=0-9223372036854775808", "bytes=-9223372036854775808",
    "bytes=١-10", "bytes=0-1,2-3",
])
def test_hostile_client_ranges_are_rejected_without_exception(range_header):
    assert not _matches_request(range_header, 206, 0, 99, 100)


class HeaderReply:
    status = 206

    def __init__(self, **headers):
        self.headers = headers

    def getheader(self, name):
        return self.headers.get(name)


@pytest.mark.parametrize("headers", [
    {"Content-Range": "bytes " + "9" * 10000 + "-7/8", "Content-Length": "4"},
    {"Content-Range": "bytes 4-" + "9" * 10000 + "/8", "Content-Length": "4"},
    {"Content-Range": "bytes 4-7/" + "9" * 10000, "Content-Length": "4"},
    {"Content-Range": "bytes 4-7/9223372036854775808", "Content-Length": "4"},
    {"Content-Range": "bytes 4-7/8", "Content-Length": "9" * 10000},
    {"Content-Range": "bytes 4-7/8", "Content-Length": "9223372036854775808"},
    {"Content-Range": "bytes ٤-7/8", "Content-Length": "4"},
])
def test_hostile_retry_framing_fails_closed(headers):
    assert not _valid_resume(HeaderReply(**headers), 4, 7, "8", None)


def test_normal_small_and_high_valid_frame_still_accepted():
    assert _valid_resume(HeaderReply(**{
        "Content-Range": "bytes 4-7/8", "Content-Length": "4",
        "ETag": '"stable-bytes"',
    }), 4, 7, "8", '"stable-bytes"')
    high = MAX_MEDIA_BYTES
    assert _valid_resume(HeaderReply(**{
        "Content-Range": f"bytes {high-3}-{high-1}/{high}",
        "Content-Length": "3", "ETag": '"stable-big-file"',
    }), high-3, high-1, str(high), '"stable-big-file"')
    assert _matches_request("bytes=10-19", 206, 10, 19, 100)
    assert _matches_request("bytes=-10", 206, 90, 99, 100)
