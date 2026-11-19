"""Minimal Chromecast HLS server.

Only the playlist and transcoded segments are exposed to the LAN. Internal
session metadata, logs, configuration and directory listings must stay private.
"""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path.home() / ".cache" / "cast-control"
PORT = 8767
HEALTH_PATH = "/_smoothcast/health"
HEALTH_BODY = b"SmoothCast HLS server v1\n"
# A unique 128-bit media generation binds the playlist and all its
# segments. Legacy names are read-only compatibility for already saved casts;
# new sessions never write those names, so stale requests cannot alias them.
_SEGMENT = re.compile(r"/segment-[0-9]+\.ts\Z")
_GENERATION = re.compile(r"/(?:movie-[0-9a-f]{32}\.m3u8|segment-[0-9a-f]{32}-[0-9]+\.ts)\Z")


def public_resource(url: str) -> bool:
    path = urlsplit(url).path
    # Exact basenames only: traversal, encoded slashes, paths and accidental
    # new files under ROOT never become LAN-visible. Query strings don't
    # change the identity of the underlying generation-specific resource.
    return (path == "/movie.m3u8" or _SEGMENT.fullmatch(path) is not None
            or _GENERATION.fullmatch(path) is not None)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def guess_type(self, path: str) -> str:
        """Use stable Cast/HLS MIME types, independent of OS MIME tables."""
        suffix = Path(path).suffix.lower()
        if suffix == ".m3u8":
            return "application/vnd.apple.mpegurl"
        if suffix == ".ts":
            return "video/mp2t"
        return super().guess_type(path)

    def end_headers(self):
        if public_resource(self.path):
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _serve(self, head: bool) -> None:
        if urlsplit(self.path).path == HEALTH_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(HEALTH_BODY)))
            self.end_headers()
            if not head:
                self.wfile.write(HEALTH_BODY)
        elif public_resource(self.path):
            if head:
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_error(404, "Not found")

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with ThreadingHTTPServer(("0.0.0.0", PORT), H) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
