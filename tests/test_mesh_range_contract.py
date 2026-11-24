"""Pure boundary matrix for the mesh Range framing contract (#567).

No sockets, files or threads: every case feeds the validators fabricated
header values, so failures point at framing logic alone.
"""
from __future__ import annotations

from email.message import Message
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh_file_wire import (  # noqa: E402
    _matches_request, _valid_resume, drop_range_for_if_range, identity_body,
    valid_unsatisfied_range,
)

MIB = 1024 * 1024
GIB = 1024 ** 3


class Reply:
    """Minimal http.client.HTTPResponse stand-in exposing status and getheader."""

    def __init__(self, status=206, **headers):
        self.status = status
        self._headers = {k.replace("_", "-").lower(): v for k, v in headers.items()}

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)


def resume_reply(start, end, size, *, etag='"v1"', status=206, length=None, **extra):
    return Reply(
        status,
        Content_Range=f"bytes {start}-{end}/{size}",
        Content_Length=str(end - start + 1 if length is None else length),
        ETag=etag,
        **extra,
    )


# ----------------------------------------------------------------- request framing

@pytest.mark.parametrize("requested,status,start,end,size,ok", [
    # No Range header: only a whole-object 200 is honest.
    (None, 200, 0, 9, 10, True),
    (None, 200, 1, 9, 10, False),
    (None, 206, 0, 9, 10, False),
    # One-byte object.
    ("bytes=0-", 206, 0, 0, 1, True),
    ("bytes=0-0", 206, 0, 0, 1, True),
    ("bytes=-1", 206, 0, 0, 1, True),
    ("bytes=1-", 206, 0, 0, 1, False),
    # Open-ended and bounded ranges.
    ("bytes=0-", 206, 0, 99, 100, True),
    ("bytes=10-", 206, 10, 99, 100, True),
    ("bytes=10-19", 206, 10, 19, 100, True),
    ("bytes=10-19", 206, 10, 18, 100, False),   # short span
    ("bytes=10-19", 206, 11, 19, 100, False),   # shifted start
    ("bytes=10-19", 200, 10, 19, 100, False),   # false full-object status
    ("bytes=90-500", 206, 90, 99, 100, True),   # oversize end clamps to size - 1
    ("bytes=90-500", 206, 90, 500, 100, False),  # but may not exceed the object
    ("bytes=99-", 206, 99, 99, 100, True),      # last byte
    ("bytes=100-", 206, 100, 100, 100, False),  # at EOF: unsatisfiable, not a span
    ("bytes=20-10", 206, 20, 10, 100, False),   # reversed
    # Suffix ranges.
    ("bytes=-10", 206, 90, 99, 100, True),
    ("bytes=-500", 206, 0, 99, 100, True),      # suffix larger than the object
    ("bytes=-10", 206, 89, 99, 100, False),
    ("bytes=-0", 206, 99, 99, 100, False),
    # Boundaries at 1 MiB and in a 1 GiB object.
    (f"bytes={MIB}-", 206, MIB, 2 * MIB - 1, 2 * MIB, True),
    (f"bytes={MIB - 1}-{MIB}", 206, MIB - 1, MIB, 2 * MIB, True),
    (f"bytes={MIB - 1}-{MIB}", 206, MIB - 1, MIB - 1, 2 * MIB, False),
    ("bytes=-1", 206, GIB - 1, GIB - 1, GIB, True),
    (f"bytes={GIB - 1}-", 206, GIB - 1, GIB - 1, GIB, True),
    # Forms the proxy refuses to interpret: never answer with a guess.
    ("bytes=0-1,5-6", 206, 0, 1, 100, False),
    ("bytes=-", 206, 0, 99, 100, False),
    ("items=0-1", 206, 0, 1, 100, False),
    ("bytes=a-b", 206, 0, 1, 100, False),
    ("bytes=0-9 ", 206, 0, 9, 100, False),
    # The served span must sit inside the object.
    ("bytes=0-", 206, 0, 100, 100, False),
    ("bytes=0-", 206, -1, 5, 100, False),
])
def test_served_span_must_equal_requested_span(requested, status, start, end, size, ok):
    assert _matches_request(requested, status, start, end, size) is ok


# ------------------------------------------------------------------ resume identity

def test_matching_resume_is_accepted():
    assert _valid_resume(resume_reply(100, 199, 1000), 100, 199, "1000", '"v1"')


@pytest.mark.parametrize("label,reply", [
    ("start moved", resume_reply(101, 199, 1000, length=99)),
    ("end moved", resume_reply(100, 198, 1000)),
    ("total moved", resume_reply(100, 199, 1001)),
    ("status 200", resume_reply(100, 199, 1000, status=200)),
    ("length short", resume_reply(100, 199, 1000, length=99)),
    ("length long", resume_reply(100, 199, 1000, length=101)),
    ("etag changed", resume_reply(100, 199, 1000, etag='"v2"')),
    ("etag dropped", Reply(206, Content_Range="bytes 100-199/1000", Content_Length="100")),
    ("chunked body", resume_reply(100, 199, 1000, Transfer_Encoding="chunked")),
    ("compressed body", resume_reply(100, 199, 1000, Content_Encoding="gzip")),
    ("unknown total", Reply(206, Content_Range="bytes 100-199/*",
                            Content_Length="100", ETag='"v1"')),
    ("missing content-range", Reply(206, Content_Length="100", ETag='"v1"')),
    ("garbage content-range", Reply(206, Content_Range="bytes x-y/z",
                                    Content_Length="100", ETag='"v1"')),
    ("range beyond total", resume_reply(900, 1000, 1000)),
])
def test_resume_fails_closed_on_any_identity_or_framing_drift(label, reply):
    assert not _valid_resume(reply, 100, 199, "1000", '"v1"'), label


def test_resume_without_validator_fails_closed():
    reply = resume_reply(100, 199, 1000)
    assert not _valid_resume(reply, 100, 199, "1000", None, None)


def test_weak_etag_cannot_prove_byte_identity():
    reply = resume_reply(100, 199, 1000, etag='W/"v1"')
    assert not _valid_resume(reply, 100, 199, "1000", 'W/"v1"')


def test_generation_identifies_object_when_etag_is_unusable():
    ok = resume_reply(100, 199, 1000, etag='W/"v1"', X_SmoothCast_Generation="7")
    assert _valid_resume(ok, 100, 199, "1000", None, "7")
    changed = resume_reply(100, 199, 1000, etag='W/"v1"', X_SmoothCast_Generation="8")
    assert not _valid_resume(changed, 100, 199, "1000", None, "7")
    missing = resume_reply(100, 199, 1000)
    assert not _valid_resume(missing, 100, 199, "1000", None, "7")


@pytest.mark.parametrize("encoding,ok", [
    (None, True), ("identity", True), (" IDENTITY ", True),
    ("gzip", False), ("br", False),
])
def test_content_encoding_must_be_identity(encoding, ok):
    headers = {} if encoding is None else {"Content_Encoding": encoding}
    assert identity_body(Reply(206, **headers)) is ok


def test_transfer_encoding_beside_fixed_length_is_ambiguous():
    assert not identity_body(Reply(206, Transfer_Encoding="chunked", Content_Length="5"))


# ---------------------------------------------------------------------- 416 and If-Range

@pytest.mark.parametrize("requested,content_range,ok", [
    ("bytes=100-", "bytes */100", True),       # starts at EOF
    ("bytes=500-", "bytes */100", True),
    ("bytes=99-", "bytes */100", False),       # satisfiable: a 416 would be a lie
    ("bytes=100-200", "bytes */100", True),
    ("bytes=200-100", "bytes */100", False),   # malformed, not merely unsatisfiable
    ("bytes=-0", "bytes */100", True),
    ("bytes=-5", "bytes */0", True),           # empty object
    ("bytes=-5", "bytes */100", False),
    ("bytes=100-", "bytes */x", False),
    ("bytes=100-", "bytes 0-9/100", False),
    ("bytes=100-", None, False),
    (None, "bytes */100", False),
    ("bytes=0-1,5-6", "bytes */100", False),
])
def test_unsatisfied_range_only_forwarded_when_provable(requested, content_range, ok):
    assert valid_unsatisfied_range(requested, content_range) is ok


def test_if_range_degrades_to_full_response():
    headers = Message()
    headers["Range"] = "bytes=10-"
    headers["If-Range"] = '"v1"'
    drop_range_for_if_range(headers)
    assert "Range" not in headers
    assert headers["If-Range"] == '"v1"'


def test_range_without_if_range_is_untouched():
    headers = Message()
    headers["Range"] = "bytes=10-"
    drop_range_for_if_range(headers)
    assert headers["Range"] == "bytes=10-"
