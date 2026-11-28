"""Serve and proxy house media by content key (issue #422).

``GET /mesh/file/<content_key>`` answers with ranged bytes: from this node's
shared library when it holds the file, otherwise by proxying HTTP Range
requests to a peer that does, so any receiver or transcoder only needs to talk
to one nearby node. Bounded buffers, bounded concurrency, resume on hiccups.
"""
from __future__ import annotations

from http.client import HTTPConnection, HTTPException
import mimetypes
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import lan_guard
from mesh_file_wire import (_CONTENT_RANGE, _matches_request, _valid_resume as _valid_resume,
                            drop_range_for_if_range, identity_body, parse_wire_uint, pump_stream,
                            valid_unsatisfied_range)
import portal_media

KEY = re.compile(r"qh:[0-9a-f]{32}")
CHUNK = 1024 * 1024
MAX_RETRIES = 3
TIMEOUT = 5.0
HOP_HEADER = "X-SmoothCast-Hop"


def key_from_path(path: str) -> str | None:
    prefix = "/mesh/file/"
    if not path.startswith(prefix):
        return None
    key = path[len(prefix):]
    return key if KEY.fullmatch(key) else None


class MeshFiles:
    def __init__(self, resolve_local: Callable[[str], "Path | None"],
                 peers_with: Callable[[str], list[str]],
                 peer_url: Callable[[str], str | None], *,
                 connect=HTTPConnection) -> None:
        self.resolve_local, self.peers_with, self.peer_url = resolve_local, peers_with, peer_url
        self._connect = connect

    # -- entry point -------------------------------------------------------
    def serve(self, handler, key: str, *, head: bool, write_headers) -> None:
        drop_range_for_if_range(handler.headers)
        proxied = handler.headers.get(HOP_HEADER) is not None
        local = self.resolve_local(key)
        if local is not None:
            mime = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
            with portal_media.stream_slot():
                portal_media.serve_direct(handler, local, mime, head=head,
                                          mesh_generation=True,
                                          write_headers=write_headers)
            return
        if proxied:  # a proxied request is never proxied again (no loops)
            raise portal_media.MediaError(404, "That media is not available right now")
        for origin in self.peers_with(key):
            url = self.peer_url(origin)
            if url and self._proxy(handler, key, url, head=head, write_headers=write_headers):
                return
        raise portal_media.MediaError(404, "That media is not available right now")

    # -- proxy -------------------------------------------------------------
    def _open(self, url: str, key: str, range_header: str | None, head: bool):
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not lan_guard.is_lan_address(host):
            raise OSError("peer is not on the home LAN")
        conn = self._connect(host, parts.port or 80, timeout=TIMEOUT)
        headers = {"Host": f"{host}:{parts.port}", HOP_HEADER: "1"}
        if range_header:
            headers["Range"] = range_header
        try:
            conn.request("HEAD" if head else "GET", f"/mesh/file/{key}", headers=headers)
            return conn, conn.getresponse()
        except BaseException:  # noqa: BLE001 - close the half-open connection then re-raise
            # No caller owns the connection until getresponse succeeds.
            conn.close()
            raise

    def _proxy(self, handler, key: str, url: str, *, head: bool, write_headers) -> bool:
        range_header = handler.headers.get("Range")
        try:
            conn, reply = self._open(url, key, range_header, head)
        except (OSError, HTTPException):
            return False
        try:
            if reply.status not in (200, 206):
                if reply.status == 416:
                    content_range = reply.getheader("Content-Range")
                    if not valid_unsatisfied_range(range_header, content_range):
                        return False
                    write_headers(416, {"Content-Length": "0",
                                        "Content-Range": content_range})
                    return True
                return False
            if not identity_body(reply):
                return False
            headers = {"Content-Type": reply.getheader("Content-Type") or "application/octet-stream",
                       "Accept-Ranges": "bytes"}
            generation = reply.getheader("X-SmoothCast-Generation")
            if generation is not None:
                # Internal generation only; do not expose origin filesystem identity.
                headers["X-SmoothCast-Generation"] = generation
            length = parse_wire_uint(reply.getheader("Content-Length"))
            if length is None:
                return False
            headers["Content-Length"] = str(length)
            start = 0
            # A full 200 response can still be resumed by an exact 206 Range.
            total = str(length) if reply.status == 200 else None
            if range_header is not None and reply.status == 200:
                # An upstream that ignores Range cannot satisfy a seeking client.
                return False
            if reply.status == 206:
                match = _CONTENT_RANGE.fullmatch(reply.getheader("Content-Range") or "")
                if match is None:
                    return False
                first, last, size = (parse_wire_uint(v) for v in match.groups())
                if (first is None or last is None or size is None
                        or last < first or last >= size or length != last - first + 1):
                    return False
                start = first
                headers["Content-Range"] = reply.getheader("Content-Range") or ""
                total = str(size)
                if not _matches_request(range_header, 206, start, last, size):
                    return False
            if head or length == 0:
                write_headers(reply.status, headers)
                return True
            # Acquire capacity BEFORE sending HTTP success. A full stream pool
            # must produce a real 503, not corrupt an already committed 200/206.
            with portal_media.stream_slot():
                write_headers(reply.status, headers)
                self._pump(handler, key, url, conn, reply, start, length, total,
                           reply.getheader("ETag"), generation)
            return True
        finally:
            conn.close()

    def _pump(self, handler, key: str, url: str, conn, reply, start: int, length: int,
              total: str | None, etag: str | None,
              generation: str | None = None) -> None:
        # Preserve the public test/runtime method while keeping wire logic small.
        pump_stream(self._open, handler, key, url, conn, reply, start, length,
                    total, etag, generation, chunk_size=CHUNK,
                    max_retries=MAX_RETRIES)
