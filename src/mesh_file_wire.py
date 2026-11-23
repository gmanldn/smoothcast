"""HTTP Range framing and bounded retry pump for SmoothCast mesh files (#567).

Keep byte identity validation and transfer cleanup independent of mesh routing.
No sockets are created on import; open_upstream is supplied by the caller.
"""
from __future__ import annotations

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
            try:
                chunk = reply.read(min(chunk_size, length - sent))
                if not chunk:
                    raise OSError("upstream ended early")
            except OSError:
                retries += 1
                if retries > max_retries:
                    return
                conn.close()
                last = start + length - 1
                try:
                    conn, reply = open_upstream(
                        url, key, f"bytes={start + sent}-{last}", False)
                except OSError:
                    continue
                if not _valid_resume(
                        reply, start + sent, last, total, etag, generation):
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
        conn.close()
