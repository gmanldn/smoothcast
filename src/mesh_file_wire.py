"""HTTP Range framing and bounded retry pump for SmoothCast mesh files (#567).

Keep byte identity validation and transfer cleanup independent of mesh routing.
No sockets are created on import; open_upstream is supplied by the caller.
"""
from __future__ import annotations

from http.client import HTTPException
import re
from typing import Callable

# Reject huge HTTP integers before conversion: a malicious LAN peer must
# never turn Python's decimal-digit limit into an unhandled media exception.
# The 63-bit ceiling matches common signed OS file offsets.
MAX_MEDIA_BYTES = 2**63 - 1
_UINT = re.compile(r"[0-9]{1,19}\Z")
_CONTENT_RANGE = re.compile(r"bytes ([0-9]{1,19})-([0-9]{1,19})/([0-9]{1,19}|\*)\Z")
_SINGLE_RANGE = re.compile(r"bytes=([0-9]{0,19})-([0-9]{0,19})\Z")


def parse_wire_uint(value: str | None) -> int | None:
    """Parse bounded ASCII decimal from untrusted HTTP headers, or refuse."""
    if not isinstance(value, str) or _UINT.fullmatch(value) is None:
        return None
    number = int(value)
    return number if number <= MAX_MEDIA_BYTES else None


def _valid_resume(reply, start: int, end: int, total: str | None,
                  etag: str | None, generation: str | None = None) -> bool:
    """Only append bytes that continue the original range and object."""
    if reply.status != 206:
        return False
    match = _CONTENT_RANGE.fullmatch(reply.getheader("Content-Range") or "")
    if match is None or total is None or total == "*":
        return False
    first_text, last_text, size_text = match.groups()
    first, last, size = (parse_wire_uint(v) for v in
                         (first_text, last_text, size_text))
    if (first is None or last is None or size is None
            or first != start or last != end or size_text != total
            or last < first or last >= size):
        return False
    length = parse_wire_uint(reply.getheader("Content-Length"))
    if length != end - start + 1:
        return False
    # An unvalidated resume may splice bytes from another file generation.
    # Weak ETags only promise semantic equivalence, not byte identity.
    strong_etag = (
        isinstance(etag, str)
        and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag) is not None
    )
    if not generation and not strong_etag:
        return False
    if etag is not None and reply.getheader("ETag") != etag:
        return False
    if generation is not None and reply.getheader("X-SmoothCast-Generation") != generation:
        return False
    return True


def _matches_request(requested: str | None, status: int, start: int,
                     end: int, size: int) -> bool:
    """Never substitute a different byte span for a browser's Range."""
    if not 0 <= start <= end < size:
        return False
    if requested is None:
        return status == 200 and start == 0
    if status != 206:
        return False
    match = _SINGLE_RANGE.fullmatch(requested)
    if match is None:
        return False
    first, last = match.groups()
    if first:
        offset = parse_wire_uint(first)
        limit = parse_wire_uint(last) if last else size - 1
        if offset is None or limit is None or offset >= size or limit < offset:
            return False
        return start == offset and end == min(limit, size - 1)
    suffix = parse_wire_uint(last)
    if suffix is None or suffix == 0:
        return False
    return start == max(0, size - suffix) and end == size - 1



def drop_range_for_if_range(headers) -> None:
    """Degrade a conditional Range to a full 200 (RFC 9110 13.1.5).

    Mesh responses carry no ETag/Last-Modified a client could echo in
    ``If-Range``, so no validator can match: answer the whole object rather
    than splicing a partial body onto a possibly stale client copy.
    """
    if headers.get("If-Range") is not None:
        while "Range" in headers:
            del headers["Range"]


_UNSATISFIED_RANGE = re.compile(r"bytes \*/([0-9]{1,19})\Z")


def valid_unsatisfied_range(requested: str | None, content_range: str | None) -> bool:
    """Only forward a 416 that proves the client's byte range is unsatisfiable."""
    if not isinstance(requested, str) or not isinstance(content_range, str):
        return False
    request = _SINGLE_RANGE.fullmatch(requested)
    response = _UNSATISFIED_RANGE.fullmatch(content_range)
    if request is None or response is None:
        return False
    total = parse_wire_uint(response.group(1))
    if total is None:
        return False
    first, last = request.groups()
    if first:
        offset = parse_wire_uint(first)
        limit = parse_wire_uint(last) if last else None
        if offset is None or (last and (limit is None or limit < offset)):
            return False
        return offset >= total
    suffix = parse_wire_uint(last)
    return suffix is not None and (suffix == 0 or total == 0)


def pump_stream(
    open_upstream: Callable,
    handler,
    key: str,
    url: str,
    conn,
    reply,
    start: int,
    length: int,
    total: str | None,
    etag: str | None,
    generation: str | None = None,
    *,
    chunk_size: int = 1024 * 1024,
    max_retries: int = 3,
) -> None:
    """Transfer exact bytes; abort downstream keep-alive on incomplete bodies.

    A replacement upstream connection is always closed even after retry failure.
    A resume must match the original byte span and object validators.
    """
    sent, retries = 0, 0
    try:
        while sent < length:
            wanted = min(chunk_size, length - sent)
            try:
                chunk = reply.read(wanted)
                if not chunk or len(chunk) > wanted:
                    raise OSError("upstream returned an invalid body chunk")
            except (OSError, HTTPException):
                # Never read the old response after a failed reconnect.
                conn.close()
                conn = None
                last = start + length - 1
                while retries < max_retries:
                    retries += 1
                    try:
                        conn, reply = open_upstream(
                            url, key, f"bytes={start + sent}-{last}", False)
                    except (OSError, HTTPException):
                        continue
                    if not _valid_resume(
                            reply, start + sent, last, total, etag, generation):
                        return
                    break
                else:
                    return
                continue
            try:
                handler.wfile.write(chunk)
            except OSError:
                return
            sent += len(chunk)
    finally:
        if sent < length:
            # A partial HTTP body may not be reused as a successful response.
            handler.close_connection = True
        if conn is not None:
            conn.close()
