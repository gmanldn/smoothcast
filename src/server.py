"""Minimal Chromecast HLS server.

Only the playlist and transcoded segments are exposed to the LAN. Internal
session metadata, logs, configuration and directory listings must stay private.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit

ROOT = Path.home() / ".cache" / "cast-control"
PORT = 8767
HEALTH_PATH = "/_smoothcast/health"
HEALTH_BODY = b"SmoothCast HLS server v1\n"
# Written by the streamer before each cast; read per request so a server kept
# alive between casts always honours the *current* receiver.
POLICY_NAME = "server_access.json"
LOOPBACK = "127.0.0.1"
# Address this process was told to listen on (health header, for reuse checks).
BIND = LOOPBACK
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


@dataclass(frozen=True)
class AccessPolicy:
    """Who may fetch the stream besides loopback (used by the health check).

    ``hosts`` are exact receiver / explicitly allowed private addresses.
    ``any_private`` is the defined fallback when the receiver address is not
    known (e.g. a cast selected by name): private-LAN clients only. Public
    addresses are never allowed. The default is fail-closed: loopback only.
    """
    hosts: frozenset[str] = frozenset()
    any_private: bool = False


def _normalise(address: str):
    """Parse a client address; unwrap IPv4-mapped IPv6 and drop a scope id."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def _private_lan(ip) -> bool:
    return (ip.is_private or ip.is_link_local) and not (
        ip.is_loopback or ip.is_unspecified or ip.is_multicast
        or ip.is_global)


def make_policy(receiver: str | None, extra: tuple[str, ...] = ()) -> AccessPolicy:
    """Build a policy; invalid or public ``extra`` entries are ignored."""
    hosts = set()
    known = _normalise(receiver) if receiver else None
    if known is not None and not known.is_unspecified and not known.is_multicast:
        hosts.add(str(known))
    for item in extra:
        ip = _normalise(item)
        if ip is not None and _private_lan(ip):
            hosts.add(str(ip))
    return AccessPolicy(frozenset(hosts), any_private=known is None and not hosts)


def client_allowed(address: str, policy: AccessPolicy) -> bool:
    ip = _normalise(address)
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    if str(ip) in policy.hosts:
        return True
    return policy.any_private and _private_lan(ip)


def write_policy(root: Path, policy: AccessPolicy) -> None:
    """Atomically publish *policy* for a running server to pick up."""
    root.mkdir(parents=True, exist_ok=True)
    target = root / POLICY_NAME
    temp = root / f".{POLICY_NAME}.{os.getpid()}.tmp"
    temp.write_text(json.dumps({
        "hosts": sorted(policy.hosts), "any_private": policy.any_private,
    }), "utf-8")
    os.replace(temp, target)


def load_policy(root: Path) -> AccessPolicy:
    try:
        data = json.loads((root / POLICY_NAME).read_text("utf-8"))
        hosts = frozenset(
            str(ip) for ip in map(_normalise, data.get("hosts", ())) if ip is not None)
        return AccessPolicy(hosts, any_private=bool(data.get("any_private")))
    except (OSError, ValueError, AttributeError, TypeError):
        return AccessPolicy()  # fail closed: loopback only


class H(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def guess_type(self, path: "str | os.PathLike[str]") -> str:
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
        if not client_allowed(self.client_address[0], load_policy(ROOT)):
            self.send_error(403, "Forbidden")
        elif urlsplit(self.path).path == HEALTH_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(HEALTH_BODY)))
            self.send_header("X-SmoothCast-Bind", BIND)
            self.send_header("X-SmoothCast-Pid", str(os.getpid()))
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


def _listen_addresses(bind: str | None) -> list[str]:
    """Loopback (health check) plus the one chosen interface; never 0.0.0.0."""
    ip = _normalise(bind) if bind else None
    if ip is None or ip.version != 4 or ip.is_unspecified or ip.is_multicast:
        return [LOOPBACK]
    return [LOOPBACK] if ip.is_loopback else [LOOPBACK, str(ip)]


def main(argv: list[str] | None = None) -> None:
    global BIND
    args = sys.argv[1:] if argv is None else argv
    bind = args[args.index("--bind") + 1] if "--bind" in args[:-1] else None
    addresses = _listen_addresses(bind)
    BIND = addresses[-1]
    ROOT.mkdir(parents=True, exist_ok=True)
    servers = [ThreadingHTTPServer((address, PORT), H) for address in addresses]
    try:
        for extra in servers[:-1]:
            threading.Thread(target=extra.serve_forever, daemon=True).start()
        servers[-1].serve_forever()
    finally:
        for httpd in servers:
            httpd.server_close()


if __name__ == "__main__":
    main()
