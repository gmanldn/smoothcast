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
import signal
import stat
import sys
import threading
import time
from urllib.parse import urlsplit

import error_log

ROOT = Path.home() / ".cache" / "cast-control"
PORT = 8767
HEALTH_PATH = "/_smoothcast/health"
# v2 identifies the CORS-capable server. A new cast must not reuse v1.
HEALTH_BODY = b"SmoothCast HLS server v2\n"
# Written by the streamer before each cast; read per request so a server kept
# alive between casts always honours the *current* receiver.
POLICY_NAME = "server_access.json"
LOG_NAME = "server.log"
LOOPBACK = "127.0.0.1"
# Google Cast Default Media Receiver origin (adaptive HLS requires CORS).
CAST_ORIGIN = "https://www.gstatic.com"
CAST_CORS_HEADERS = frozenset({"content-type", "accept-encoding", "range"})
# Address this process was told to listen on (health header, for reuse checks).
BIND = LOOPBACK
# A unique 128-bit media generation binds the playlist and all its
# segments. Legacy names are read-only compatibility for already saved casts;
# new sessions never write those names, so stale requests cannot alias them.
_SEGMENT = re.compile(r"/segment-[0-9]+\.ts\Z")
_GENERATION = re.compile(
    r"/(?:movie-[0-9a-f]{32}(?:-fmp4)?\.m3u8|"
    r"segment-[0-9a-f]{32}-[0-9]+\.(?:ts|m4s)|init-[0-9a-f]{32}\.mp4)\Z"
)


def _url_path(url: str) -> str:
    """Path of a request target, or "" when it cannot be parsed.

    ``urlsplit`` raises ValueError for targets such as ``//a]b`` ("Invalid IPv6
    URL"); a hostile or broken client must get a 404, not a dropped connection.
    """
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def public_resource(url: str, token: str = "") -> bool:
    """Is *url* a servable HLS resource? With *token*, only that generation."""
    path = _url_path(url)
    # Exact basenames only: traversal, encoded slashes, paths and accidental
    # new files under ROOT never become LAN-visible. Query strings don't
    # change the identity of the underlying generation-specific resource.
    if token:
        return (path in {f"/movie-{token}.m3u8", f"/movie-{token}-fmp4.m3u8"}
                or re.fullmatch(rf"/segment-{token}-[0-9]+\.(?:ts|m4s)", path) is not None
                or path == f"/init-{token}.mp4")
    return (path == "/movie.m3u8" or _SEGMENT.fullmatch(path) is not None
            or _GENERATION.fullmatch(path) is not None)


_RANGE = re.compile(r"bytes=(\d*)-(\d*)\Z")


def parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Parse one RFC 7233 byte range; ``None`` means no/ignored range.

    Multiple ranges are deliberately unsupported (the receiver fetches one
    segment at a time). A syntactically valid but unsatisfiable range raises
    :class:`ValueError` so the caller can answer 416 with ``bytes */size``.
    """
    if not value or size < 0:
        return None
    match = _RANGE.fullmatch(value.strip())
    if match is None:
        raise ValueError("invalid range")
    first, last = match.groups()
    if not first and not last:
        raise ValueError("empty range")
    if first:
        start = int(first)
        end = int(last) if last else size - 1
        if start >= size or end < start:
            raise ValueError("unsatisfiable range")
        return start, min(end, size - 1)
    suffix = int(last)
    if suffix <= 0 or size == 0:
        raise ValueError("unsatisfiable suffix range")
    return max(0, size - suffix), size - 1


def etag_for(info: os.stat_result) -> str:
    """A stable strong-looking validator for an immutable HLS generation file."""
    return f'"{info.st_size:x}-{info.st_mtime_ns:x}"'


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
    # Accurate Content-Length on every response lets receivers reuse the
    # connection instead of reconnecting for every HLS segment.
    protocol_version = "HTTP/1.1"

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
        if not isinstance(address, str):
            return False
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
        if suffix in {".m4s", ".mp4"}:
            return "video/mp4"
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _cast_origin_allowed(self) -> bool:
        return self.headers.get_all("Origin", []) == [CAST_ORIGIN]

    def _send_cast_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", CAST_ORIGIN)
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Accept-Ranges")

    def do_OPTIONS(self) -> None:
        """Allow only the default receiver's read-only active-HLS preflight."""
        policy = load_policy(ROOT)
        if not client_allowed(self.client_address[0], policy):
            self.send_error(403, "Forbidden")
            return
        if not self._host_allowed():
            self.send_error(400, "Invalid HLS Host header")
            return
        if not policy.token or not public_resource(self.path, policy.token):
            self.send_error(404, "Not found")
            return
        methods = self.headers.get_all("Access-Control-Request-Method", [])
        requested = self.headers.get_all("Access-Control-Request-Headers", [])
        fields = {field.strip().lower() for value in requested for field in value.split(",")}
        if (not self._cast_origin_allowed() or methods not in (["GET"], ["HEAD"])
                or not fields.issubset(CAST_CORS_HEADERS)):
            self.send_error(403, "Forbidden")
            return
        self.send_response(204)
        self._send_cast_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept-Encoding, Range")
        self.send_header("Vary", "Origin, Access-Control-Request-Method, Access-Control-Request-Headers")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve(self, head: bool) -> None:
        policy = load_policy(ROOT)
        if not client_allowed(self.client_address[0], policy):
            self.send_error(403, "Forbidden")
        elif not self._host_allowed():
            # The HLS URL uses an interface IP, not an arbitrary hostname.
            # Reject DNS-rebinding and duplicate Host headers.
            self.send_error(400, "Invalid HLS Host header")
        elif _url_path(self.path) == HEALTH_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(HEALTH_BODY)))
            self.send_header("X-SmoothCast-Bind", BIND)
            self.send_header("X-SmoothCast-Pid", str(os.getpid()))
            self.end_headers()
            if not head:
                self.wfile.write(HEALTH_BODY)
        elif public_resource(self.path, policy.token):
            _note_media_request()
            self._serve_media(head, cors=bool(policy.token) and self._cast_origin_allowed())
        else:
            self.send_error(404, "Not found")

    def _serve_media(self, head: bool, *, cors: bool = False) -> None:
        """Serve one allow-listed HLS file with ranges and cache validators."""
        path = _url_path(self.path).lstrip("/")
        target = ROOT / path
        try:
            # Exact allow-listed basenames only; never follow a symlink that
            # could expose another file under the same name.
            if target.is_symlink():
                raise OSError("refusing a symlinked HLS resource")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(target, flags)
        except OSError:
            self.send_error(404, "Not found")
            return
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                self.send_error(404, "Not found")
                return
            size = info.st_size
            etag = etag_for(info)
            last_modified = self.date_time_string(info.st_mtime)
            if_range = self.headers.get("If-Range")
            range_header = self.headers.get("Range")
            if if_range and if_range.strip() not in {etag, last_modified}:
                range_header = None  # validator changed: send the whole file
            try:
                requested = parse_range(range_header, size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            start, end = requested if requested is not None else (0, size - 1)
            length = max(0, end - start + 1)
            status = 206 if requested is not None else 200
            self.send_response(status)
            self.send_header("Vary", "Origin")
            if cors:
                self._send_cast_cors()
            self.send_header("Content-Type", self.guess_type(target))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            self.send_header("Content-Length", str(length))
            if requested is not None:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head or length == 0:
                return
            os.lseek(fd, start, os.SEEK_SET)
            remaining = length
            while remaining > 0:
                chunk = os.read(fd, min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)

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


# Kept-stream watchdog. With "keep streaming" the encoder and this server
# outlive the app; if the receiver then stops fetching (another sender took
# over, TV off), nothing would ever stop a full-length transcode. Only an
# orphaned encoder of the current 128-bit generation is ever stopped.
IDLE_STOP_SECONDS = 600.0
_last_media_request = time.monotonic()


def _note_media_request() -> None:
    global _last_media_request
    _last_media_request = time.monotonic()


def _orphaned(pid: int, proc: Path = Path("/proc")) -> bool:
    """True when ``pid`` was reparented to init/systemd, i.e. the app is gone."""
    try:
        fields = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        ppid = int(fields[1])
        if ppid == 1:
            return True
        return (proc / str(ppid) / "comm").read_text().strip() in {"systemd", "init"}
    except (OSError, ValueError, IndexError):
        return False


_KEPT_PLAYLIST = re.compile(rb"movie-[0-9a-f]{32}(?:-fmp4)?\.m3u8\Z")


def kept_encoder_pids(root: Path, proc: Path = Path("/proc")) -> list[int]:
    """Orphaned FFmpeg processes writing a SmoothCast HLS generation under ``root``."""
    found = []
    prefix = os.fsencode(str(root)) + b"/"
    try:
        entries = [entry for entry in proc.iterdir() if entry.name.isdigit()]
    except OSError:
        return found
    for entry in entries:
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if not argv or not Path(os.fsdecode(argv[0])).name.startswith("ffmpeg"):
            continue
        if not any(arg.startswith(prefix) and _KEPT_PLAYLIST.search(arg) for arg in argv):
            continue
        pid = int(entry.name)
        if pid > 1 and _orphaned(pid, proc):
            found.append(pid)
    return found


def _session_encoder_alive(root: Path) -> bool:
    try:
        pid = int(json.loads((root / "session.json").read_text("utf-8")).get("ffmpeg_pid") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return pid > 1 and Path(f"/proc/{pid}").exists()


def _idle_watchdog(servers: list[ThreadingHTTPServer], *, interval: float = 60.0) -> None:
    while True:
        time.sleep(interval)
        if time.monotonic() - _last_media_request < IDLE_STOP_SECONDS:
            continue
        stopped = False
        for pid in kept_encoder_pids(ROOT):
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
                log_event(f"stopped kept encoder {pid}: receiver idle for "
                          f"{IDLE_STOP_SECONDS:.0f}s after the app exited")
            except OSError:
                pass
        # A server reused by a newer app instance stays while that app's own
        # encoder is alive; exit only when no saved session encoder remains.
        if _orphaned(os.getpid()) and (stopped or not _session_encoder_alive(ROOT)):
            log_event("idle with no app; server exiting")
            for httpd in servers:
                threading.Thread(target=httpd.shutdown, daemon=True).start()
            return


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
        if sys.platform.startswith("linux"):
            threading.Thread(target=_idle_watchdog, args=(servers,),
                             name="hls-idle-watchdog", daemon=True).start()
        servers[-1].serve_forever()
    except Exception:
        log_event("server stopped unexpectedly", exc_info=True)
        raise
    finally:
        for httpd in servers:
            httpd.server_close()


if __name__ == "__main__":
    main()
