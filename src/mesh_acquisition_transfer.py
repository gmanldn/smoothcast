"""Move one verified acquired file from a worker to the room host (#589).

Worker: :class:`TransferServer` is a tiny LAN-only HTTP server that serves
*only* files a job explicitly registered, each behind its own random ticket
token (constant-time compared, revocable, expiring), with single ``Range``
resume. Host: :func:`fetch` streams to a private temp file, bounds size and time,
and publishes it only after the byte count AND SHA-256 equal the executor's
reported values. :class:`TransferHost` then asks the ledger to enqueue exactly
once and delivers the verified local copy. A partial or mismatching file is
never delivered, never queued and never left behind.

GTK-free; LAN addresses only (``mesh_model.is_lan_address``).
"""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import secrets
import threading
import time

import mesh_acquisition_assignment as core
import mesh_acquisition_rpc as wire
import mesh_model

TICKET_SECONDS = 900.0
MAX_CONCURRENT = 2
CHUNK = 1 << 20
_PATH = re.compile(r"/acq/([A-Za-z0-9_-]{8,64})/([A-Za-z0-9_-]{16,64})\Z")
_RANGE = re.compile(r"bytes=(\d{1,19})-\Z")
MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ts",
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav",
})


class TransferError(RuntimeError):
    """The file did not arrive intact; nothing was published."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8


class TransferServer:
    def __init__(self, bind_ip: str, port: int = 0, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not mesh_model.is_lan_address(bind_ip):
            raise ValueError("bind_ip must be a private LAN IPv4 address")
        self._clock = clock
        self._lock = threading.Lock()
        self._tickets: dict[str, tuple[str, Path, int, float]] = {}  # job -> (token, file, size, expiry)
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 10
            server_version = "SmoothCastMesh"
            sys_version = ""

            def log_message(self, *_a: object) -> None:
                return

            def _fail(self, status: int) -> None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

            def do_GET(self) -> None:  # noqa: N802
                if not mesh_model.is_lan_address(self.client_address[0]):
                    return self._fail(403)
                match = _PATH.fullmatch(self.path)
                entry = outer._lookup(match.group(1), match.group(2)) if match else None
                if entry is None:
                    return self._fail(404)  # unknown job, wrong token and expiry are indistinguishable
                path, size = entry
                start = 0
                requested = self.headers.get("Range")
                if requested is not None:
                    ranged = _RANGE.fullmatch(requested.strip())
                    if ranged is None or int(ranged.group(1)) >= size:
                        return self._fail(416)
                    start = int(ranged.group(1))
                if not outer._slots.acquire(blocking=False):
                    return self._fail(503)
                try:
                    with open(path, "rb") as stream:
                        stream.seek(start)
                        self.send_response(206 if requested else 200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(size - start))
                        if requested:
                            self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        remaining = size - start
                        while remaining > 0:
                            chunk = stream.read(min(CHUNK, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except OSError:
                    pass
                finally:
                    outer._slots.release()
                    self.close_connection = True

            do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = (  # noqa: N815
                lambda self: self._fail(405))

        self._server = _Server((bind_ip, port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.1},
                                        name="smoothcast-acq-transfer", daemon=True)
        self._thread.start()

    def register(self, job: str, path: Path, size: int) -> str:
        """Offer exactly this file for this job; returns the ticket token."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tickets[job] = (token, Path(path), size, self._clock() + TICKET_SECONDS)
        return token

    def revoke(self, job: str) -> None:
        with self._lock:
            self._tickets.pop(job, None)

    def _lookup(self, job: str, token: str) -> tuple[Path, int] | None:
        with self._lock:
            entry = self._tickets.get(job)
        if entry is None or self._clock() > entry[3] or not hmac.compare_digest(entry[0], token):
            return None
        path, size = entry[1], entry[2]
        try:
            info = path.lstat()
        except OSError:
            return None
        if info.st_size != size or path.is_symlink():
            return None
        return path, size

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(2)


def fetch(host: str, port: int, job: str, token: str, destination: Path, *,
          expect_size: int, expect_sha: str, timeout: float = 10.0,
          deadline: float = 3600.0, attempts: int = 3,
          clock: Callable[[], float] = time.monotonic) -> Path:
    """Download to *destination* (atomic) only if size and SHA-256 both match."""
    if not mesh_model.is_lan_address(host) or type(port) is not int or not 1 <= port <= 65535:
        raise TransferError("transfer endpoint is not a LAN address")
    if not (type(expect_size) is int and 0 < expect_size <= core.MAX_BYTES
            and re.fullmatch(r"[0-9a-f]{64}", expect_sha or "")):
        raise TransferError("invalid transfer expectations")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    part = destination.with_name(destination.name + ".part")
    end = clock() + deadline
    last: Exception | None = None
    try:
        for _ in range(max(1, attempts)):
            have = part.stat().st_size if part.exists() else 0
            if have > expect_size:
                part.unlink()
                have = 0
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            try:
                headers = {"Range": f"bytes={have}-"} if 0 < have < expect_size else {}
                conn.request("GET", f"/acq/{job}/{token}", headers=headers)
                response = conn.getresponse()
                if response.status not in (200, 206) or (headers and response.status != 206):
                    last = TransferError(f"worker refused the transfer ({response.status})")
                    if response.status in (404, 403, 405):
                        break
                    continue
                mode = "ab" if response.status == 206 else "wb"
                if response.status == 200:
                    have = 0
                fd = os.open(part, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "ab" else os.O_TRUNC), 0o600)
                with os.fdopen(fd, mode) as out:
                    while chunk := response.read(CHUNK):
                        have += len(chunk)
                        if have > expect_size or clock() > end:
                            raise TransferError("transfer exceeded its size or time bound")
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if have == expect_size:
                    break
                last = TransferError("transfer ended early")
            except (OSError, http.client.HTTPException) as exc:
                last = exc
            finally:
                conn.close()
        if not part.exists() or part.stat().st_size != expect_size:
            raise TransferError(str(last) if last else "incomplete transfer")
        digest = hashlib.sha256()
        with open(part, "rb") as stream:
            while block := stream.read(CHUNK):
                digest.update(block)
        if digest.hexdigest() != expect_sha:
            raise TransferError("transferred content does not match its hash")
        os.replace(part, destination)
        return destination
    except TransferError:
        part.unlink(missing_ok=True)
        raise
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise TransferError(str(exc)) from exc


class TransferHost:
    """Host side: ticket -> verified fetch -> enqueue exactly once -> deliver."""

    def __init__(self, coordinator: wire.HostCoordinator, directory: Path,
                 address_of: Callable[[str], str | None],
                 deliver: Callable[[str, Path], None], *,
                 fetcher: Callable[..., Path] = fetch) -> None:
        self.coordinator, self.directory = coordinator, Path(directory)
        self._address_of, self._deliver, self._fetch = address_of, deliver, fetcher

    def collect(self, job_id: str) -> str:
        """Returns ``queued``, ``not_ready``, ``unavailable`` or ``failed``."""
        ledger = self.coordinator.ledger
        job = ledger.jobs.get(job_id)
        if (job is None or job.state != "transfer" or job.enqueued or job.ambiguous
                or job.node is None or not job.content_key):
            return "not_ready"
        host = self._address_of(job.node)
        if not host:
            return "unavailable"
        try:
            reply = self.coordinator._send(job.node, wire.build("ticket", job=job_id, gen=job.generation))
        except Exception:  # noqa: BLE001 - worker unreachable: retry later, nothing queued
            return "unavailable"
        port, token, size, ext = (reply.get(k) if isinstance(reply, dict) else None
                                  for k in ("port", "token", "size", "ext"))
        if (not isinstance(reply, dict) or not reply.get("ok") or type(port) is not int
                or not isinstance(token, str) or type(size) is not int
                or ext not in MEDIA_EXTENSIONS):
            return "unavailable"
        try:
            path = self._fetch(host, port, job_id, token, self.directory / f"{job_id}{ext}",
                               expect_size=size, expect_sha=job.content_key)
        except TransferError:
            return "failed"
        try:
            first = ledger.enqueue_once(job_id, job.content_key)
        except core.LedgerError:
            path.unlink(missing_ok=True)
            return "failed"
        if not first:
            return "not_ready"
        self._deliver(job_id, path)
        return "queued"
