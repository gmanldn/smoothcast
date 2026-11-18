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
_SEGMENT = re.compile(r"/segment-[0-9]+\.ts\Z")


def public_resource(url: str) -> bool:
    path = urlsplit(url).path
    # Exact names only: reject directory traversal, dotfiles, encoded aliases,
    # and anything else that isn't an HLS resource.
    return path == "/movie.m3u8" or _SEGMENT.fullmatch(path) is not None


class H(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

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
