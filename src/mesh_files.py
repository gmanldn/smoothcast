"""Serve and proxy house media by content key (issue #422).

``GET /mesh/file/<content_key>`` answers with ranged bytes: from this node's
shared library when it holds the file, otherwise by proxying HTTP Range
requests to a peer that does, so any receiver or transcoder only needs to talk
to one nearby node. Bounded buffers, bounded concurrency, resume on hiccups.
"""
from __future__ import annotations

from http.client import HTTPConnection
import mimetypes
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import lan_guard
import portal_media

KEY = re.compile(r"qh:[0-9a-f]{32}")
CHUNK = 1024 * 1024
MAX_RETRIES = 3
TIMEOUT = 5.0
HOP_HEADER = "X-SmoothCast-Hop"
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


def _valid_resume(reply, start: int, end: int, total: str | None,
                  etag: str | None) -> bool:
    """Only append bytes that continue the original range and object."""
    if reply.status != 206:
        return False
    match = _CONTENT_RANGE.fullmatch(reply.getheader("Content-Range") or "")
    if match is None or total is None or total == "*":
        return False
    first, last, size = match.groups()
    if (int(first) != start or int(last) != end or size != total
            or int(last) < int(first) or int(last) >= int(size)):
        return False
    try:
        length = int(reply.getheader("Content-Length") or "")
    except ValueError:
        return False
    if length != end - start + 1:
        return False
    if etag is not None and reply.getheader("ETag") != etag:
        return False
    return True


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
        proxied = handler.headers.get(HOP_HEADER) is not None
        local = self.resolve_local(key)
        if local is not None:
            mime = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
            with portal_media.stream_slot():
                portal_media.serve_direct(handler, local, mime, head=head,
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
        conn.request("HEAD" if head else "GET", f"/mesh/file/{key}", headers=headers)
        return conn, conn.getresponse()

    def _proxy(self, handler, key: str, url: str, *, head: bool, write_headers) -> bool:
        range_header = handler.headers.get("Range")
        try:
            conn, reply = self._open(url, key, range_header, head)
        except OSError:
            return False
        try:
            if reply.status not in (200, 206):
                if reply.status == 416:
                    write_headers(416, {"Content-Length": "0",
                                        "Content-Range": reply.getheader("Content-Range") or "bytes */0"})
                    return True
                return False
            headers = {"Content-Type": reply.getheader("Content-Type") or "application/octet-stream",
                       "Accept-Ranges": "bytes"}
            try:
                length = int(reply.getheader("Content-Length") or "")
            except ValueError:
                return False
            if length < 0:
                return False
            headers["Content-Length"] = str(length)
            start = 0
            total = None
            if reply.status == 206:
                match = _CONTENT_RANGE.fullmatch(reply.getheader("Content-Range") or "")
                if match is None:
                    return False
                first, last, size = match.groups()
                start = int(first)
                if (size == "*" or int(last) < start or int(last) >= int(size)
                        or length != int(last) - start + 1):
                    return False
                headers["Content-Range"] = reply.getheader("Content-Range") or ""
                total = size
            write_headers(reply.status, headers)
            if head or length == 0:
                return True
            with portal_media.stream_slot():
                self._pump(handler, key, url, conn, reply, start, length, total,
                           reply.getheader("ETag"))
            return True
        finally:
            conn.close()

    def _pump(self, handler, key: str, url: str, conn, reply, start: int, length: int,
              total: str | None, etag: str | None) -> None:
        sent, retries = 0, 0
        try:
            while sent < length:
                try:
                    chunk = reply.read(min(CHUNK, length - sent))
                    if not chunk:
                        raise OSError("upstream ended early")
                except OSError:
                    retries += 1
                    if retries > MAX_RETRIES:
                        return
                    conn.close()
                    last = start + length - 1
                    try:
                        conn, reply = self._open(
                            url, key, f"bytes={start + sent}-{last}", False)
                    except OSError:
                        continue
                    if not _valid_resume(reply, start + sent, last, total, etag):
                        return
                    continue
                try:
                    handler.wfile.write(chunk)
                except OSError:
                    return
                sent += len(chunk)
        finally:
            # A retry may have replaced the original connection. Always close it.
            conn.close()
