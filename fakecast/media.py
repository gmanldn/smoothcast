"""Bounded loopback-only HLS fetching for the fake Cast receiver."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import time
import threading
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_SEGMENT_BYTES = 64 * 1024 * 1024
MAX_SEGMENTS = 10000
PLAYLIST_TYPES = {
    "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl",
}


class MediaFetchError(RuntimeError):
    """The fake receiver could not safely fetch or parse an HLS resource."""


@dataclass(frozen=True)
class Segment:
    uri: str
    duration: float
    byte_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class FetchResult:
    duration: float
    segment_count: int
    bytes_received: int
    ended: bool
    requests: tuple[dict[str, object], ...]
    cors_origins: tuple[str | None, ...]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HlsFetcher:
    """Fetch a finite HLS presentation from a loopback HTTP server only."""

    def __init__(self, *, timeout: float = 2.0, segment_delay: float = 0.0,
                 cancelled: threading.Event | None = None) -> None:
        if not 0.1 <= timeout <= 10:
            raise ValueError("timeout must be between 0.1 and 10 seconds")
        if not 0 <= segment_delay <= 30:
            raise ValueError("segment delay must be between 0 and 30 seconds")
        self.timeout = timeout
        self.segment_delay = segment_delay
        self.cancelled = cancelled
        self.requests: list[dict[str, object]] = []
        self.cors_origins: list[str | None] = []
        self.bytes_received = 0
        self.segment_count = 0
        self.duration = 0.0
        self._opener = build_opener(_NoRedirect())

    @staticmethod
    def _check_url(url: str) -> tuple[str, str]:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise MediaFetchError("HLS fake accepts unauthenticated loopback HTTP URLs only")
        try:
            addresses = {ipaddress.ip_address(item[4][0].split("%", 1)[0])
                         for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
        except (OSError, ValueError) as exc:
            raise MediaFetchError("HLS URL hostname could not be resolved") from exc
        if not addresses or any(not address.is_loopback for address in addresses):
            raise MediaFetchError("HLS URL must resolve exclusively to loopback addresses")
        return parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _media_type(value: str | None) -> str:
        return (value or "").split(";", 1)[0].strip().lower()

    def _get(self, url: str, *, byte_range: tuple[int, int] | None = None,
             max_bytes: int = MAX_SEGMENT_BYTES) -> tuple[bytes, str, str | None]:
        if self.cancelled and self.cancelled.is_set():
            raise MediaFetchError("HLS fetch was cancelled")
        self._check_url(url)
        headers = {"Origin": "http://smoothcast-fake.local"}
        if byte_range is not None:
            headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        request = Request(url, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                content_type = self._media_type(response.headers.get("Content-Type"))
                content_range = response.headers.get("Content-Range")
                cors = response.headers.get("Access-Control-Allow-Origin")
                body = response.read(max_bytes + 1)
        except (HTTPError, OSError, TimeoutError) as exc:
            raise MediaFetchError(f"HTTP fetch failed ({getattr(exc, 'code', 'network')})") from exc
        if len(body) > max_bytes:
            raise MediaFetchError("HLS resource exceeds the fake receiver size limit")
        if byte_range is None and status != 200:
            raise MediaFetchError(f"unexpected HTTP status {status} for HLS resource")
        if byte_range is not None:
            expected = f"bytes {byte_range[0]}-{byte_range[1]}/"
            if status != 206 or not content_range or not content_range.startswith(expected):
                raise MediaFetchError("byte-range response did not match the requested range")
        if cors not in {None, "*", "http://smoothcast-fake.local"}:
            raise MediaFetchError("HLS server returned an invalid CORS origin")
        self.bytes_received += len(body)
        self.requests.append({
            "url": url,
            "status": status,
            "content_type": content_type,
            "content_range": content_range,
            "range": byte_range,
            "bytes": len(body),
        })
        self.cors_origins.append(cors)
        return body, content_type, cors

    def _playlist(self, url: str, depth: int = 0) -> tuple[list[Segment], bool]:
        if depth > 2:
            raise MediaFetchError("HLS playlist nesting is too deep")
        body, content_type, _cors = self._get(url, max_bytes=MAX_PLAYLIST_BYTES)
        if content_type not in PLAYLIST_TYPES:
            raise MediaFetchError("HLS playlist has an unsupported content type")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeError as exc:
            raise MediaFetchError("HLS playlist is not UTF-8 text") from exc
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] != "#EXTM3U":
            raise MediaFetchError("HLS playlist does not start with #EXTM3U")
        variant_next = False
        variants: list[str] = []
        segments: list[Segment] = []
        pending_duration: float | None = None
        pending_range: str | None = None
        previous_range_end: dict[str, int] = {}
        init_uris: set[str] = set()
        ended = False
        for line in lines[1:]:
            if line.startswith("#EXT-X-STREAM-INF:"):
                variant_next = True
            elif line.startswith("#EXT-X-MAP:"):
                marker = 'URI="'
                start = line.find(marker)
                if start >= 0:
                    init_url = urljoin(url, line[start + len(marker):].split('"', 1)[0])
                    if init_url not in init_uris:
                        body, content_type, _cors = self._get(init_url)
                        if content_type not in {"video/mp4", "application/octet-stream"}:
                            raise MediaFetchError("HLS initialization segment has an invalid content type")
                        init_uris.add(init_url)
            elif line.startswith("#EXTINF:"):
                try:
                    pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
                except ValueError as exc:
                    raise MediaFetchError("HLS segment duration is invalid") from exc
                if not 0 < pending_duration <= 3600:
                    raise MediaFetchError("HLS segment duration is outside supported limits")
            elif line.startswith("#EXT-X-BYTERANGE:"):
                pending_range = line.split(":", 1)[1]
            elif line == "#EXT-X-ENDLIST":
                ended = True
            elif line.startswith("#"):
                continue
            elif variant_next:
                variants.append(urljoin(url, line))
                variant_next = False
            else:
                if pending_duration is None:
                    continue
                segment_url = urljoin(url, line)
                byte_range = None
                if pending_range is not None:
                    try:
                        length_text, _, offset_text = pending_range.partition("@")
                        length = int(length_text)
                        offset = (int(offset_text) if offset_text else
                                  previous_range_end.get(segment_url, 0))
                    except ValueError as exc:
                        raise MediaFetchError("HLS byte range is invalid") from exc
                    if length <= 0 or offset < 0:
                        raise MediaFetchError("HLS byte range is invalid")
                    byte_range = (offset, offset + length - 1)
                    previous_range_end[segment_url] = offset + length
                segments.append(Segment(segment_url, pending_duration, byte_range))
                pending_duration = None
                pending_range = None
                if len(segments) > MAX_SEGMENTS:
                    raise MediaFetchError("HLS playlist contains too many segments")
        if variants:
            return self._playlist(variants[0], depth + 1)
        if not segments:
            raise MediaFetchError("HLS playlist contains no media segments")
        return segments, ended

    def fetch(self, url: str, on_segment=None) -> FetchResult:
        """Fetch each playlist segment and report buffered playback progress."""
        segments, ended = self._playlist(url)
        for segment in segments:
            if self.cancelled and self.cancelled.is_set():
                raise MediaFetchError("HLS fetch was cancelled")
            if self.segment_delay:
                if self.cancelled:
                    if self.cancelled.wait(self.segment_delay):
                        raise MediaFetchError("HLS fetch was cancelled")
                else:
                    time.sleep(self.segment_delay)
            self._check_url(segment.uri)
            body, content_type, _cors = self._get(
                segment.uri, byte_range=segment.byte_range,
            )
            path = urlsplit(segment.uri).path.lower()
            allowed_types = ({"video/mp2t", "application/octet-stream"}
                             if path.endswith(".ts") else {"video/mp4", "application/octet-stream"})
            if content_type not in allowed_types:
                raise MediaFetchError("HLS segment has an unsupported content type")
            if not body:
                raise MediaFetchError("HLS segment is empty")
            self.segment_count += 1
            self.duration += segment.duration
            if on_segment is not None:
                on_segment(self.duration, self.segment_count)
        return FetchResult(
            self.duration, self.segment_count, self.bytes_received, ended,
            tuple(self.requests), tuple(self.cors_origins),
        )
