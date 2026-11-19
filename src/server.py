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

import error_log

ROOT = Path.home() / ".cache" / "cast-control"
PORT = 8767
HEALTH_PATH = "/_smoothcast/health"
HEALTH_BODY = b"SmoothCast HLS server v1\n"
# Written by the streamer before each cast; read per request so a server kept
# alive between casts always honours the *current* receiver.
POLICY_NAME = "server_access.json"
LOG_NAME = "server.log"
LOOPBACK = "127.0.0.1"
# Address this process was told to listen on (health header, for reuse checks).
BIND = LOOPBACK
# A unique 128-bit media generation binds the playlist and all its
# segments. Legacy names are read-only compatibility for already saved casts;
# new sessions never write those names, so stale requests cannot alias them.
_SEGMENT = re.compile(r"/segment-[0-9]+\.ts\Z")
_GENERATION = re.compile(r"/(?:movie-[0-9a-f]{32}\.m3u8|segment-[0-9a-f]{32}-[0-9]+\.ts)\Z")


def public_resource(url: str, token: str = "") -> bool:
    """Is *url* a servable HLS resource? With *token*, only that generation."""
    path = urlsplit(url).path
    # Exact basenames only: traversal, encoded slashes, paths and accidental
    # new files under ROOT never become LAN-visible. Query strings don't
    # change the identity of the underlying generation-specific resource.
    if token:
        return (path == f"/movie-{token}.m3u8"
                or re.fullmatch(rf"/segment-{token}-[0-9]+\.ts", path) is not None)
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
    # The active HLS generation (32 hex). When set, only that generation's
    # playlist and segments are served; every other generation and the legacy
    # fixed names get 404, so stale URLs die as soon as a new cast starts or
    # the policy is revoked (#228). Empty = legacy behaviour for older casts.
    token: str = ""


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


_TOKEN = re.compile(r"[0-9a-f]{32}\Z")


def make_policy(receiver: str | None, extra: tuple[str, ...] = (),
                token: str = "") -> AccessPolicy:
    """Build a policy; invalid or public ``extra`` entries are ignored.

    A non-empty *token* must be a 32-character lowercase hex generation id;
    anything else raises ValueError rather than silently serving everything.
    """
    if token and not _TOKEN.match(token):
        raise ValueError("HLS token must be 32 lowercase hex characters")
    hosts = set()
    known = _normalise(receiver) if receiver else None
    if known is not None and not known.is_unspecified and not known.is_multicast:
        hosts.add(str(known))
    for item in extra:
        ip = _normalise(item)
        if ip is not None and _private_lan(ip):
            hosts.add(str(ip))
    return AccessPolicy(frozenset(hosts), any_private=known is None and not hosts, token=token)


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
        "token": policy.token,
    }), "utf-8")
    os.replace(temp, target)


def load_policy(root: Path) -> AccessPolicy:
    try:
        data = json.loads((root / POLICY_NAME).read_text("utf-8"))
        hosts = frozenset(
            str(ip) for ip in map(_normalise, data.get("hosts", ())) if ip is not None)
        token = data.get("token", "")
        if token and not (isinstance(token, str) and _TOKEN.match(token)):
            return AccessPolicy()  # corrupt token: fail closed rather than serve everything
        return AccessPolicy(hosts, any_private=bool(data.get("any_private")), token=token)
    except (OSError, ValueError, AttributeError, TypeError):
        return AccessPolicy()  # fail closed: loopback only


_LOGS: dict[str, error_log.ErrorLog] = {}
_LOGS_LOCK = threading.Lock()


def server_log() -> error_log.ErrorLog:
    """Bounded server.log in the cache directory (#232).

    Reuses ErrorLog, so it has the same line, byte and compaction limits as the
    application error log. One instance per file, safe across handler threads.
    """
    path = str(ROOT / LOG_NAME)
    with _LOGS_LOCK:
        if path not in _LOGS:
            _LOGS[path] = error_log.ErrorLog(path)
        return _LOGS[path]


def log_event(message: str, *, exc_info: bool = False) -> None:
    """Best-effort: a full disk or bad permissions must never break streaming."""
    try:
        server_log().add(message, exc_info=exc_info)
    except Exception:
        pass


class H(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def setup(self) -> None:
        super().setup()
        # Slow clients must not occupy a handler thread indefinitely.
        self.connection.settimeout(15.0)

    def _host_allowed(self) -> bool:
        hosts = self.headers.get_all("Host", [])
        if not hosts:
            return self.request_version == "HTTP/1.0"
        if len(hosts) != 1:
            return False
        if not isinstance(self.server, ThreadingHTTPServer):
            return False
        address = self.server.server_address[0]
        host = hosts[0].strip()
        return host in {address, f"{address}:{self.server.server_port}"}

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (stdlib signature)
        # Only errors reach this: successful requests are not logged below.
        log_event(f"{self.address_string()} {format % args}")

    def log_request(self, code="-", size="-") -> None:
        # A film is thousands of 200 responses; log only failed requests.
        try:
            failed = int(code) >= 400
        except (TypeError, ValueError):
            failed = True
        if failed:
            super().log_request(code, size)

    def guess_type(self, path: "str | os.PathLike[str]") -> str:
        """Use stable Cast/HLS MIME types, independent of OS MIME tables."""
        suffix = Path(path).suffix.lower()
        if suffix == ".m3u8":
            return "application/vnd.apple.mpegurl"
        if suffix == ".ts":
            return "video/mp2t"
        return super().guess_type(path)

    def end_headers(self):
        # Native receivers fetch HLS without browser CORS access.
        # Do not expose stream bytes to arbitrary LAN web-page origins.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _serve(self, head: bool) -> None:
        policy = load_policy(ROOT)
        if not client_allowed(self.client_address[0], policy):
            self.send_error(403, "Forbidden")
        elif not self._host_allowed():
            # The HLS URL uses an interface IP, not an arbitrary hostname.
            # Reject DNS-rebinding and duplicate Host headers.
            self.send_error(400, "Invalid HLS Host header")
        elif urlsplit(self.path).path == HEALTH_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(HEALTH_BODY)))
            self.send_header("X-SmoothCast-Bind", BIND)
            self.send_header("X-SmoothCast-Pid", str(os.getpid()))
            self.end_headers()
            if not head:
                self.wfile.write(HEALTH_BODY)
        elif public_resource(self.path, policy.token):
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


def listen_port(args: list[str]) -> int:
    """``--port N`` if it is a valid unprivileged TCP port, else the default."""
    try:
        port = int(args[args.index("--port") + 1]) if "--port" in args[:-1] else PORT
    except ValueError:
        return PORT
    return port if 1024 <= port <= 65535 else PORT


def main(argv: list[str] | None = None) -> None:
    global BIND
    args = sys.argv[1:] if argv is None else argv
    port = listen_port(args)
    bind = args[args.index("--bind") + 1] if "--bind" in args[:-1] else None
    addresses = _listen_addresses(bind)
    BIND = addresses[-1]
    ROOT.mkdir(parents=True, exist_ok=True)
    servers: list[ThreadingHTTPServer] = []
    try:
        for address in addresses:
            servers.append(ThreadingHTTPServer((address, port), H))
    except OSError:
        # Partial listen failures must not leak a loopback socket. Otherwise
        # each retry can consume the port and prevent healthy restarts.
        for httpd in servers:
            httpd.server_close()
        log_event(f"cannot listen on {addresses} port {port}", exc_info=True)
        raise
    log_event(f"listening on {', '.join(addresses)} port {port}")
    try:
        for extra in servers[:-1]:
            threading.Thread(target=extra.serve_forever, daemon=True).start()
        servers[-1].serve_forever()
    except Exception:
        log_event("server stopped unexpectedly", exc_info=True)
        raise
    finally:
        for httpd in servers:
            httpd.server_close()


if __name__ == "__main__":
    main()
