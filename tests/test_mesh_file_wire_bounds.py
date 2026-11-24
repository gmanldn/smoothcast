"""Reject hostile HTTP byte lengths before numeric conversion (#567)."""
from __future__ import annotations

from http.client import BadStatusLine, IncompleteRead
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_file_wire import MAX_MEDIA_BYTES, _matches_request, _valid_resume, parse_wire_uint, pump_stream


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


@pytest.mark.parametrize("etag", [None, "", "not-quoted", 'W/"weak"',
                                  '"space inside"', '"a", "b"', '"a\n"'])
def test_malformed_etag_is_not_byte_identity(etag):
    reply = Mock(status=206)
    headers = {"Content-Range": "bytes 4-7/8", "Content-Length": "4",
               "ETag": etag, "X-SmoothCast-Generation": ""}
    reply.getheader.side_effect = headers.get
    assert not _valid_resume(reply, 4, 7, "8", etag, "")
    assert not _valid_resume(reply, 4, 7, "8", etag)


def _resumed_reply(payload=b"WXYZ"):
    reply = Mock(status=206)
    headers = {"Content-Range": "bytes 4-7/8", "Content-Length": "4",
               "ETag": '"same"'}
    reply.getheader.side_effect = headers.get
    reply.read.return_value = payload
    return reply


def test_failed_reconnect_never_reads_stale_reply():
    first_conn, next_conn = Mock(), Mock()
    first = Mock()
    first.read.side_effect = [b"ABCD", OSError("drop"),
                              AssertionError("old response reused")]
    resumed = _resumed_reply()
    opener = Mock(side_effect=[OSError("unreachable"), (next_conn, resumed)])
    client = SimpleNamespace(wfile=BytesIO(), close_connection=False)
    pump_stream(opener, client, "key", "url", first_conn, first,
                0, 8, "8", '"same"', chunk_size=4)
    assert client.wfile.getvalue() == b"ABCDWXYZ"
    assert not client.close_connection
    assert first.read.call_count == 2
    assert opener.call_count == 2
    assert all(call.args == ("url", "key", "bytes=4-7", False)
               for call in opener.call_args_list)
    first_conn.close.assert_called_once()
    next_conn.close.assert_called_once()


@pytest.mark.parametrize("failure", [OSError("down"), BadStatusLine("bad HTTP")])
def test_reconnect_exhaustion_closes_partial_downstream(failure):
    first_conn, first = Mock(), Mock()
    first.read.side_effect = [b"ABCD", OSError("drop"),
                              AssertionError("old response reused")]
    opener = Mock(side_effect=failure)
    client = SimpleNamespace(wfile=BytesIO(), close_connection=False)
    pump_stream(opener, client, "key", "url", first_conn, first,
                0, 8, "8", '"same"', chunk_size=4, max_retries=3)
    assert client.wfile.getvalue() == b"ABCD"
    assert client.close_connection
    assert opener.call_count == 3 and first.read.call_count == 2
    first_conn.close.assert_called_once()


@pytest.mark.parametrize("bad_chunk", [IncompleteRead(b"WX", 2), b"WXYZEXTRA"])
def test_bad_body_chunk_is_discarded_before_valid_resume(bad_chunk):
    first_conn, next_conn, first = Mock(), Mock(), Mock()
    first.read.side_effect = [b"ABCD", bad_chunk]
    opener = Mock(return_value=(next_conn, _resumed_reply()))
    client = SimpleNamespace(wfile=BytesIO(), close_connection=False)
    pump_stream(opener, client, "key", "url", first_conn, first,
                0, 8, "8", '"same"', chunk_size=4)
    assert client.wfile.getvalue() == b"ABCDWXYZ"
    assert not client.close_connection
    opener.assert_called_once_with("url", "key", "bytes=4-7", False)
    first_conn.close.assert_called_once()
    next_conn.close.assert_called_once()

@pytest.mark.parametrize("header,value", [
    ("Transfer-Encoding", "chunked"),
    ("Transfer-Encoding", "identity"),
    ("Content-Encoding", "gzip"),
    ("Content-Encoding", "br"),
    ("Content-Encoding", "identity, gzip"),
])
def test_resume_rejects_ambiguous_or_transformed_media_bytes(header, value):
    reply = HeaderReply(**{
        "Content-Range": "bytes 4-7/8", "Content-Length": "4",
        "ETag": '"same"', header: value,
    })
    assert not _valid_resume(reply, 4, 7, "8", '"same"')


def test_resume_accepts_explicit_identity_content_encoding():
    reply = HeaderReply(**{
        "Content-Range": "bytes 4-7/8", "Content-Length": "4",
        "ETag": '"same"', "Content-Encoding": "Identity",
    })
    assert _valid_resume(reply, 4, 7, "8", '"same"')

