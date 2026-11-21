"""Small, PIN-protected shared-room dashboard hosted by the GTK application.

The portal uses Python's standard-library HTTP server so SmoothCast adds no
web framework or runtime dependency. GTK callbacks are supplied by the caller
and are dispatched onto the GTK main context by the application layer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import ipaddress
import json
import math
import re
import secrets
import socket
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import portal_commands
import portal_room
import portal_uploads


PIN_DIGITS = "0123456789"
PIN_LENGTH = 6
FRIENDLY_NAME_MAX = 32
MAX_BODY = 2048
SESSION_SECONDS = 8 * 60 * 60
ATTEMPT_WINDOW_SECONDS = 60
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
REQUEST_TIMEOUT = 5


@dataclass
class _Session:
    csrf: str
    expiry: float
    participant_id: str


class PortalError(RuntimeError):
    """Portal configuration, startup, or dispatch failure."""


class PortalRequestError(Exception):
    """A safe request rejection with an HTTP status and user-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def new_pin(*, choice=secrets.choice) -> str:
    """Return a six-digit PIN using a cryptographically secure chooser."""
    return "".join(choice(PIN_DIGITS) for _ in range(PIN_LENGTH))


def _dns_label(value: str) -> str:
    """Reduce arbitrary text to a short, lowercase DNS label."""
    label = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    label = re.sub(r"-{2,}", "-", label).strip("-")
    return label[:FRIENDLY_NAME_MAX].strip("-")


def friendly_name(hostname: str | None = None) -> str:
    """Return a short, human-friendly mDNS name for this machine.

    The system hostname is sanitised and prefixed with ``smoothcast`` so the
    name is memorable and unlikely to collide with another device. A caller may
    pass an explicit hostname to keep the helper deterministic in tests.
    """
    raw = hostname if hostname is not None else socket.gethostname()
    label = _dns_label((raw or "").split(".")[0])
    if not label:
        return "smoothcast"
    if label.startswith("smoothcast"):
        return label
    return _dns_label(f"smoothcast-{label}") or "smoothcast"


def valid_friendly_name(value: str) -> bool:
    """Return whether ``value`` is safe as a single mDNS hostname label."""
    return bool(value) and len(value) <= FRIENDLY_NAME_MAX and bool(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", value)
    )


def _page() -> bytes:
    return _HTML.encode("utf-8")


class _PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, pin: str, dispatch: Callable, *, clock=time.monotonic,
                 uploads: portal_uploads.UploadManager | None = None,
                 hostname: str | None = None,
                 commands: portal_commands.CommandDispatcher | None = None,
                 fence: portal_commands.CommandFence | None = None,
                 room: portal_room.PortalRoom | None = None) -> None:
        super().__init__(address, _Handler)
        self.pin = pin
        self.dispatch = dispatch
        self.uploads = uploads
        self.room = room or portal_room.PortalRoom()
        self.clock = clock
        self.fence = fence or portal_commands.CommandFence(clock=clock)
        self.commands = commands or portal_commands.CommandDispatcher(
            self._apply_default_command, fence=self.fence, clock=clock)
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self.queue_ids: set[str] = set()
        self._attempts: dict[str, deque[float]] = {}
        self._lockouts: dict[str, float] = {}
        port = self.server_address[1]
        self._allowed_hosts = {
            f"{self.server_address[0]}:{port}".lower(),
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        }
        if hostname:
            self._allowed_hosts.update({f"{hostname}.local:{port}", f"{hostname}.local"})

    def _apply_default_command(self, envelope: portal_commands.MutationEnvelope):
        """Apply a command when the caller did not supply a GTK dispatcher."""
        self.fence.check(envelope.expected_session_id, envelope.expected_revision)
        try:
            result = self.dispatch(envelope.action, {"action": envelope.action, **envelope.payload})
        except PortalRequestError as exc:
            raise portal_commands.CommandError(exc.status, exc.message) from exc
        except Exception as exc:
            raise portal_commands.CommandError(
                503, "SmoothCast could not accept that command") from exc
        session_id, revision, _owner = self.fence.rotate()
        return portal_commands.CommandReceipt(
            envelope.command_id, session_id, revision, result or "Command accepted")

    def server_close(self) -> None:
        try:
            self.commands.close()
        finally:
            super().server_close()

    def host_allowed(self, host: str) -> bool:
        return bool(host) and host.lower() in self._allowed_hosts

    def origin_allowed(self, origin: str, host: str) -> bool:
        try:
            parsed = urlsplit(origin)
            return (parsed.scheme == "http" and parsed.netloc.lower() == host.lower()
                    and not parsed.username and not parsed.password
                    and not parsed.path and not parsed.query and not parsed.fragment
                    and self.host_allowed(host))
        except ValueError:
            return False

    @staticmethod
    def _session_key(token: str) -> str:
        return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()

    def _expire_sessions(self, now: float) -> None:
        for key, session in list(self._sessions.items()):
            if session.expiry <= now:
                self._sessions.pop(key, None)
                self.room.leave(session.participant_id)

    def create_session(self, name: object = "Guest") -> tuple[str, str, portal_room.Participant]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        now = self.clock()
        with self._lock:
            self._expire_sessions(now)
            while len(self._sessions) >= 128:
                key, session = self._sessions.popitem()
                self.room.leave(session.participant_id)
            participant = self.room.join(name)
            self._sessions[self._session_key(token)] = _Session(
                csrf, now + SESSION_SECONDS, participant.id,
            )
        return token, csrf, participant

    def session_csrf(self, token: str | None) -> str | None:
        if not token:
            return None
        key = self._session_key(token)
        now = self.clock()
        with self._lock:
            self._expire_sessions(now)
            session = self._sessions.get(key)
            return None if session is None else session.csrf

    def session_participant(self, token: str | None) -> str | None:
        if not token:
            return None
        key = self._session_key(token)
        now = self.clock()
        with self._lock:
            self._expire_sessions(now)
            session = self._sessions.get(key)
            if session is None:
                return None
            try:
                self.room.touch(session.participant_id)
            except portal_room.RoomError:
                self._sessions.pop(key, None)
                return None
            return session.participant_id

    def pin_allowed(self, client: str, pin: str) -> bool:
        now = self.clock()
        with self._lock:
            for address, expiry in list(self._lockouts.items()):
                if expiry <= now:
                    self._lockouts.pop(address, None)
                    self._attempts.pop(address, None)
            if len(self._attempts) > 512:
                for address in list(self._attempts)[:len(self._attempts) - 512]:
                    self._attempts.pop(address, None)
            until = self._lockouts.get(client, 0.0)
            if until > now:
                return False
            attempts = self._attempts.setdefault(client, deque())
            while attempts and now - attempts[0] >= ATTEMPT_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= MAX_ATTEMPTS:
                self._lockouts[client] = now + LOCKOUT_SECONDS
                return False
            if hmac.compare_digest(pin.encode("utf-8"), self.pin.encode("utf-8")):
                attempts.clear()
                self._lockouts.pop(client, None)
                return True
            attempts.append(now)
            return False


class _Handler(BaseHTTPRequestHandler):
    server: _PortalHTTPServer
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT
    server_version = "SmoothCastPortal"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths, cookies, PINs, and remote addresses can contain secrets
        # or private LAN details; the portal deliberately emits no access log.
        return

    def _send(self, status: int, payload: dict | bytes, *, content_type="application/json",
              cookie: str | None = None) -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            return
        self.close_connection = True

    def _error(self, status: int, message: str, **extra: object) -> None:
        payload = {"ok": False, "error": message}
        payload.update(extra)
        self._send(status, payload)

    def _safe_origin(self, *, required: bool) -> bool:
        host = self.headers.get("Host", "")
        if not self.server.host_allowed(host):
            return False
        origin = self.headers.get("Origin", "")
        return self.server.origin_allowed(origin, host) if required else (
            not origin or self.server.origin_allowed(origin, host)
        )

    def _body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise PortalRequestError(400, "Invalid request body") from exc
        if length < 0:
            raise PortalRequestError(400, "Invalid request body")
        if length > MAX_BODY:
            raise PortalRequestError(413, "Request is too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PortalRequestError(400, "Request must be JSON") from exc
        if not isinstance(value, dict):
            raise PortalRequestError(400, "Request must be a JSON object")
        return value

    def _cookie_token(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sc_portal_session":
                return value
        return None

    def _path(self) -> str:
        try:
            return urlsplit(self.path).path
        except ValueError:
            return ""

    def _authenticated(self, *, csrf: bool = False) -> bool:
        if not self._safe_origin(required=csrf):
            return False
        expected = self.server.session_csrf(self._cookie_token())
        if expected is None:
            return False
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if not self._safe_origin(required=False):
            return self._error(400, "Invalid host")
        if path in {"/", "/index.html"}:
            return self._send(200, _page(), content_type="text/html; charset=utf-8")
        if path == "/api/status":
            if not self._authenticated():
                return self._error(401, "Enter the PIN shown in SmoothCast")
            participant_id = self.server.session_participant(self._cookie_token())
            if participant_id is None:
                return self._error(401, "Session expired")
            try:
                state = self.server.dispatch("status", {})
            except Exception:
                return self._error(503, "SmoothCast is not ready to report playback state")
            queue = state.get("queue") if isinstance(state.get("queue"), list) else []
            live_ids: set[str] = set()
            merged = []
            for entry in queue:
                if not isinstance(entry, dict):
                    continue
                item_id = entry.get("id")
                if not isinstance(item_id, str) or not item_id:
                    continue
                live_ids.add(item_id)
                item = dict(entry)
                voters = self.server.room.votes.get(item_id, set())
                item["votes"] = len(voters)
                item["voted"] = participant_id in voters
                merged.append(item)
            self.server.queue_ids = live_ids
            self.server.room.prune(live_ids)
            state["queue"] = merged
            state["room"] = self.server.room.snapshot(participant_id)
            return self._send(200, {"ok": True, "state": state})
        upload_id = self._upload_route(path)
        if upload_id and self._authenticated():
            if self.server.uploads is None:
                return self._error(503, "Upload storage is unavailable")
            try:
                return self._send(200, {"ok": True, **self.server.uploads.status(
                    self._cookie_token() or "", upload_id)})
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
        if upload_id:
            return self._error(401, "Enter the PIN shown in SmoothCast")
        return self._error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        path = self._path()
        if path == "/api/uploads":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            try:
                if self.server.uploads is None:
                    return self._error(503, "Upload storage is unavailable")
                body = self._body()
                created = self.server.uploads.create(
                    self._cookie_token() or "", body.get("name"), body.get("size"),
                    self.client_address[0], queue_only=bool(body.get("queue")))
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
            return self._send(201, {"ok": True, **created})
        upload_id = self._upload_complete_route(path)
        if upload_id:
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            try:
                if self.server.uploads is None:
                    return self._error(503, "Upload storage is unavailable")
                body = self._body()
                try:
                    default_queue = self.server.uploads.is_queue_only(
                        self._cookie_token() or "", upload_id)
                except portal_uploads.UploadError:
                    default_queue = False
                queue_only = bool(body.get("queue", default_queue))
                media_path, name, dispatch = self.server.uploads.finalize(
                    self._cookie_token() or "", upload_id)
                if dispatch:
                    try:
                        self.server.dispatch("queue_add" if queue_only else "cast_upload", {
                            "path": str(media_path), "name": name,
                            "upload_id": upload_id, "early": False,
                            "client": self.client_address[0],
                        })
                    except PortalRequestError:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise
                    except Exception as exc:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise PortalRequestError(503, "SmoothCast could not start this upload") from exc
                return self._send(202, {"ok": True, "message": "Upload received; casting started."})
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        try:
            body = self._body()
        except PortalRequestError as exc:
            return self._error(exc.status, exc.message)
        if path == "/api/login":
            pin = body.get("pin")
            if not isinstance(pin, str):
                pin = ""
            client = self.client_address[0]
            if not self.server.pin_allowed(client, pin):
                return self._error(401, "Incorrect PIN or too many attempts")
            name = body.get("name", "Guest")
            if not isinstance(name, str):
                return self._error(400, "Your name must be text")
            try:
                token, csrf, participant = self.server.create_session(name)
            except portal_room.RoomError as exc:
                return self._error(exc.status, exc.message)
            cookie = (f"sc_portal_session={token}; Path=/; HttpOnly; SameSite=Strict; "
                      f"Max-Age={SESSION_SECONDS}")
            return self._send(200, {
                "ok": True, "csrf": csrf,
                "participant": participant.public(time.time()),
                "room": self.server.room.snapshot(participant.id),
            }, cookie=cookie)
        if path == "/api/action":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            action = body.get("action")
            try:
                envelope = portal_commands.parse_envelope(body)
                if envelope is None:
                    if not isinstance(action, str) or action not in {
                            "play_pause", "stop", "seek", "volume", "music_autogain",
                            "next", "previous", "queue_play", "queue_remove",
                            "queue_move", "queue_vote"}:
                        return self._error(400, "Unsupported action")
                    participant_id = self.server.session_participant(self._cookie_token())
                    if participant_id is None:
                        return self._error(401, "Session expired")
                    if action in {"queue_play", "queue_remove", "queue_move", "queue_vote"}:
                        item_id = body.get("id")
                        if not isinstance(item_id, str) or item_id not in self.server.queue_ids:
                            return self._error(404, "That queue item is no longer here")
                    if action == "queue_move":
                        position = body.get("position")
                        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
                            return self._error(400, "Queue position must be a non-negative integer")
                    if action == "queue_vote":
                        value = body.get("value")
                        if not isinstance(value, bool):
                            return self._error(400, "Vote must be true or false")
                        try:
                            result = self.server.room.vote(participant_id, body["id"], value)
                        except portal_room.RoomError as exc:
                            return self._error(exc.status, exc.message)
                        return self._send(202, {"ok": True, "message": "Vote saved",
                                                "vote": result})
                    if action in {"next", "previous", "queue_play", "queue_remove", "queue_move"}:
                        try:
                            result = self.server.dispatch(action, body)
                        except PortalRequestError as exc:
                            return self._error(exc.status, exc.message)
                        except Exception:
                            return self._error(503, "SmoothCast could not accept that command")
                        self.server.room.record(participant_id, "action",
                                                {"action": action, "id": body.get("id")})
                        return self._send(202, {"ok": True, "message": result or "Command accepted"})
                    if action == "seek":
                        value = body.get("value")
                        if isinstance(value, bool) or not isinstance(value, (float, int)):
                            return self._error(400, "Seek position must be a number")
                        if not math.isfinite(float(value)) or not 0 <= float(value) <= 24 * 60 * 60:
                            return self._error(400, "Seek position is out of range")
                        body["value"] = float(value)
                    if action == "volume":
                        value = body.get("value")
                        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                            return self._error(400, "Volume must be from 0 to 100")
                    if action == "music_autogain" and type(body.get("value")) is not bool:
                        return self._error(400, "Music autogain must be on or off")
                    token = self._cookie_token() or ""
                    envelope = portal_commands.legacy_envelope(
                        body, self.server.fence,
                        client_id="legacy-" + self.server._session_key(token)[:40])
                receipt = self.server.commands.execute(envelope)
            except portal_commands.CommandError as exc:
                extra = {}
                if exc.status == 409:
                    extra["conflict"] = True
                if exc.revision is not None:
                    extra["revision"] = exc.revision
                if exc.session_id is not None:
                    extra["session_id"] = exc.session_id
                return self._error(exc.status, exc.message, **extra)
            return self._send(202, {
                "ok": True, "message": receipt.message,
                "command_id": receipt.command_id,
                "session_id": receipt.session_id,
                "revision": receipt.revision,
            })
        return self._error(404, "Not found")

    @staticmethod
    def _upload_route(path: str) -> str | None:
        prefix = "/api/uploads/"
        if path.startswith(prefix) and "/" not in path[len(prefix):]:
            return path[len(prefix):]
        return None

    @staticmethod
    def _upload_complete_route(path: str) -> str | None:
        prefix, suffix = "/api/uploads/", "/complete"
        if path.startswith(prefix) and path.endswith(suffix):
            upload_id = path[len(prefix):-len(suffix)]
            if upload_id and "/" not in upload_id:
                return upload_id
        return None

    def _start_early_cast(self, upload_id: str, result: dict) -> None:
        """Ask SmoothCast to cast the growing file before it finishes arriving.

        Best-effort: a rejection (busy, unsupported) declines early casting and
        the upload continues, so the completed file is still cast on finalize.
        """
        try:
            self.server.dispatch("cast_upload", {
                "path": result["cast_path"], "name": result["name"],
                "upload_id": upload_id, "early": True,
                "client": result.get("client", ""),
            })
            accepted = True
        except Exception:
            accepted = False
        self.server.uploads.mark_early_cast(upload_id, accepted=accepted)

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.headers.get("Transfer-Encoding"):
            return self._error(400, "Chunked transfer encoding is not supported")
        raw_length = self.headers.get("Content-Length")
        if self.server.uploads is None:
            return self._error(503, "Upload storage is unavailable")
        try:
            length = int(raw_length or "")
        except ValueError:
            return self._error(400, "Invalid upload chunk length")
        if length <= 0 or length > portal_uploads.CHUNK_SIZE:
            return self._error(413, "Upload chunks must be at most 2 MiB")
        try:
            result = self.server.uploads.append(
                self._cookie_token() or "", upload_id,
                self.headers.get("Content-Range", ""), length, self.rfile)
            if result.get("ready_to_cast"):
                self._start_early_cast(upload_id, result)
            return self._send(200, {"ok": True, **result})
        except portal_uploads.UploadError as exc:
            self.close_connection = True
            return self._error(exc.status, exc.message)
        except OSError:
            self.close_connection = True
            return self._error(507, "Could not store this upload chunk")

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.server.uploads is None:
            return self._error(503, "Upload storage is unavailable")
        try:
            self.server.uploads.cancel(self._cookie_token() or "", upload_id)
            return self._send(200, {"ok": True})
        except portal_uploads.UploadError as exc:
            return self._error(exc.status, exc.message)

    def _not_allowed(self) -> None:
        self._error(405, "Method not allowed")

    do_PATCH = do_OPTIONS = do_HEAD = _not_allowed  # noqa: N815


class Portal:
    """One-interface LAN portal with a per-run PIN and clean thread shutdown."""

    def __init__(self, bind_ip: str, dispatch: Callable, *, pin: str | None = None,
                 uploads: portal_uploads.UploadManager | None = None,
                 name: str | None = None,
                 commands: portal_commands.CommandDispatcher | None = None,
                 fence: portal_commands.CommandFence | None = None) -> None:
        if not isinstance(bind_ip, str):
            raise PortalError("A private IPv4 address is required")
        try:
            address = ipaddress.IPv4Address(bind_ip)
        except ValueError as exc:
            raise PortalError("A private IPv4 address is required") from exc
        private_nets = (ipaddress.ip_network("10.0.0.0/8"),
                        ipaddress.ip_network("172.16.0.0/12"),
                        ipaddress.ip_network("192.168.0.0/16"))
        if not any(address in network for network in private_nets):
            raise PortalError("Refusing to host the LAN portal on a non-private interface")
        self.pin = pin or new_pin()
        if len(self.pin) != PIN_LENGTH or any(char not in PIN_DIGITS for char in self.pin):
            raise PortalError("PIN must contain six digits")
        self.name = name or friendly_name()
        if not valid_friendly_name(self.name):
            raise PortalError("Friendly name must be a short lowercase DNS label")
        self.bind_ip = str(address)
        self.uploads = uploads or portal_uploads.UploadManager()
        self.room = portal_room.PortalRoom()
        self.server = _PortalHTTPServer((self.bind_ip, 0), self.pin, dispatch,
                                        uploads=self.uploads, hostname=self.name,
                                        commands=commands, fence=fence,
                                        room=self.room)
        self.port = int(self.server.server_address[1])
        self.url = f"http://{self.bind_ip}:{self.port}/"
        self.friendly_url = f"http://{self.name}.local:{self.port}/"
        self._zeroconf = None
        self._service_info = None
        self._advertise()
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.1},
                                       name="smoothcast-portal", daemon=True)
        self.thread.start()

    def _advertise(self) -> None:
        """Best-effort mDNS advertisement so the friendly name resolves."""
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            return
        zeroconf = None
        try:
            info = ServiceInfo(
                "_http._tcp.local.",
                f"SmoothCast on {self.name}._http._tcp.local.",
                addresses=[socket.inet_aton(self.bind_ip)],
                port=self.port,
                properties={"path": "/", "name": self.name},
                server=f"{self.name}.local.",
            )
            zeroconf = Zeroconf(interfaces=[self.bind_ip])
            zeroconf.register_service(info)
        except Exception:
            if zeroconf is not None:
                try:
                    zeroconf.close()
                except Exception:
                    pass
            return
        self._zeroconf = zeroconf
        self._service_info = info

    def _unadvertise(self) -> None:
        zeroconf, info = self._zeroconf, self._service_info
        self._zeroconf = self._service_info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                zeroconf.unregister_service(info)
        except Exception:
            pass
        try:
            zeroconf.close()
        except Exception:
            pass

    def stop(self) -> None:
        self._unadvertise()
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()
        if self.server.uploads is not None:
            self.server.uploads.close()


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>SmoothCast</title>
<style>
:root{font:16px system-ui,sans-serif;color-scheme:light dark;--bg:#101722;--card:#1c2735;--accent:#4d9de0;--muted:#b7c3d0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f4f7fb}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.05rem;margin:0 0 12px}p{color:var(--muted);margin:.35rem 0}
section{background:var(--card);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 26px #0002}
label{display:block;margin:12px 0 6px}input,button{font:inherit;min-height:44px;border-radius:10px;border:1px solid #718096;padding:8px 12px}
input{width:100%;color:inherit;background:#121b27}button{background:var(--accent);color:white;border:0;font-weight:650;cursor:pointer}
#musicAutogain{width:auto;min-height:0;margin-right:8px}
button.secondary{background:#36475d}button:disabled,input:disabled{opacity:.55;cursor:not-allowed}.actions{display:flex;gap:8px;flex-wrap:wrap}
.actions button{flex:1 1 120px}.muted{color:var(--muted)}.big{font-size:1.35rem;font-weight:700}.row{display:flex;justify-content:space-between;gap:12px}
progress{width:100%;height:10px}ul{padding-left:0;list-style:none}li{padding:4px 0;overflow-wrap:anywhere}#error{color:#ffb4a9;min-height:1.4em}
.participants{display:flex;flex-wrap:wrap;gap:7px;margin:4px 0 0}.person{display:flex;align-items:center;gap:6px;background:#121b27;border:1px solid #ffffff12;border-radius:999px;padding:4px 9px 4px 4px;font-size:.82rem}.person.offline{opacity:.45}.avatar{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:.68rem;font-weight:750;color:#08101a}
.queue-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border-top:1px solid #ffffff10;padding:8px 0}.queue-item:first-child{border-top:0}.queue-item strong{display:block;font-size:.88rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue-item .muted{font-size:.74rem}.queue-actions{display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.tiny{min-height:32px;padding:4px 8px;font-size:.76rem;border-radius:8px}.vote{background:#1c3555;border:1px solid #4d9de066;color:#cfe6ff}.vote.on{background:#2e6fae;color:white}.activity{display:grid;gap:4px;font-size:.78rem;color:var(--muted);max-height:160px;overflow:auto}.activity .ev{display:flex;gap:7px}.activity time{color:#8394aa;white-space:nowrap}.empty{color:var(--muted);border:1px dashed #718096;border-radius:10px;padding:12px;text-align:center}
:focus-visible{outline:3px solid #ffd166;outline-offset:2px}@media(max-width:480px){main{padding:12px}section{padding:15px}}
</style></head><body><main><header><h1>SmoothCast</h1><p>Local playback dashboard</p></header>
<section id="login"><h2>Connect to SmoothCast</h2><p>Enter your name and the six-digit PIN shown on the SmoothCast home screen.</p>
<form id="loginForm"><label for="name">Your name</label><input id="name" name="name" maxlength="40" autocomplete="nickname" placeholder="e.g. Sam" required>
<label for="pin">Access PIN</label><input id="pin" name="pin" minlength="6" maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" required>
<p id="error" role="alert" aria-live="polite"></p><button type="submit">Connect</button></form></section>
<div id="dashboard" hidden><section><div class="row"><h2>Now Playing</h2><span id="state" class="muted">—</span></div>
<p id="title" class="big">Nothing playing</p><p id="receiver">Receiver: —</p><progress id="progress" max="1" value="0" aria-label="Playback progress"></progress>
<div class="row"><span id="elapsed">0:00</span><span id="duration">—</span></div>
<label for="seek">Seek</label><input id="seek" type="range" min="0" max="1" value="0" disabled>
<div class="actions"><button data-action="play_pause">Play / pause</button><button class="secondary" data-action="stop">Stop</button><button class="secondary" data-action="previous">Previous</button><button class="secondary" data-action="next">Next</button></div></section>
<section><h2>Volume</h2><label for="volume">Receiver volume</label><input id="volume" type="range" min="0" max="100" value="0" disabled><p id="volumeText">—</p></section>
<section><h2>Music</h2><label><input id="musicAutogain" type="checkbox"> Normalise audio-only tracks</label><p>Targets -16 LUFS with a -1.5 dBTP ceiling. Existing programme/album normalisation takes precedence.</p></section>
<section><h2>In the room</h2><div id="people" class="participants"></div><h2 style="margin-top:18px">Activity</h2><div id="activity" class="activity"></div></section>
<section><div class="row"><h2>Queue</h2><span id="queueCount" class="muted"></span></div><ul id="queue"><li class="empty">No videos queued</li></ul></section>
<section id="networkActivity"><h2>On your network</h2><p>Read-only status from reachable Cast and DLNA receivers; refreshes every 15 seconds. Unreachable receivers are omitted.</p><p id="networkActivitySummary" class="muted" role="status" aria-live="polite">Checking discovered receivers…</p><ul id="networkActivityRows"><li>No active streams reported by reachable receivers</li></ul></section><p id="errorDash" role="status" aria-live="polite"></p></div>
<section id="uploadCard" hidden><h2>Add a video from this device</h2><p>Files transfer in resumable chunks. Add one to the shared queue, or start it now. Supported formats start streaming to your receiver while the rest arrives.</p>
<label for="videoFile">Video file</label><input id="videoFile" type="file" accept="video/*,.mkv,.ts,.wmv">
<label style="display:flex;align-items:center;gap:9px;min-height:44px"><input id="uploadQueue" type="checkbox" style="width:auto;min-height:auto" checked> Add to the shared queue</label>
<progress id="uploadProgress" max="1" value="0" aria-label="Upload progress"></progress><p id="uploadStatus" role="status" aria-live="polite"></p>
<div class="actions"><button id="uploadButton" type="button">Upload and add</button><button id="cancelUpload" class="secondary" type="button" hidden>Cancel upload</button></div></section></main>
<script>
let csrf="",busy=false,uploading=false,cancelUpload=false,casting=false,pendingUpload=null,activeUploadController=null;const $=id=>document.getElementById(id),showError=(id,msg)=>$(id).textContent=msg;
async function post(path,body){const r=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();showError("error","");try{const d=await post("/api/login",{pin:$("pin").value.trim(),name:$("name").value.trim()});csrf=d.csrf;$("login").hidden=true;$("dashboard").hidden=false;$("uploadCard").hidden=false;refresh()}catch(err){showError("error",err.message)}});
function clock(s){if(s==null||!Number.isFinite(s))return "—";s=Math.floor(Math.max(0,s));return `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`}
async function refresh(){if(!csrf||busy)return;try{const r=await fetch("/api/status",{credentials:"same-origin",cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Connection lost");const s=d.state||{};$("state").textContent=s.state||"—";$("title").textContent=s.title||"Nothing playing";$("receiver").textContent="Receiver: "+(s.receiver||"—");
const duration=Number(s.duration)||0,position=Number(s.position)||0;$("progress").max=duration||1;$("progress").value=Math.min(position,duration||position);$("seek").max=duration||1;$("seek").value=Math.min(position,duration||position);$("seek").disabled=!s.can_seek||!duration;$("elapsed").textContent=clock(position);$("duration").textContent=clock(duration);$("volume").disabled=s.volume==null;$("volume").value=s.volume||0;$("volumeText").textContent=s.volume==null?"Volume unavailable":`${s.volume}%`;
$("musicAutogain").checked=!!s.music_autogain;
const queue=$("queue");queue.replaceChildren();if(!s.queue||!s.queue.length){const li=document.createElement("li");li.className="empty";li.textContent="No videos queued";queue.append(li)}else for(const item of s.queue){const li=document.createElement("li");li.className="queue-item";const text=document.createElement("div");const title=document.createElement("strong");title.textContent=item.title||"Video";const meta=document.createElement("div");meta.className="muted";meta.textContent=(item.votes?`▲ ${item.votes} vote${item.votes===1?"":"s"}`:"No votes")+(item.duration?` · ${clock(item.duration)}`:"");text.append(title,meta);const actions=document.createElement("div");actions.className="queue-actions";const vote=document.createElement("button");vote.className="tiny vote"+(item.voted?" on":"");vote.textContent=item.voted?"Voted":"Vote";vote.addEventListener("click",()=>act("queue_vote",!item.voted,{id:item.id}));actions.append(vote);const play=document.createElement("button");play.className="tiny";play.textContent="Play now";play.addEventListener("click",()=>act("queue_play",undefined,{id:item.id}));actions.append(play);const up=document.createElement("button");up.className="tiny secondary";up.textContent="↑";up.title="Move up";up.addEventListener("click",()=>act("queue_move",undefined,{id:item.id,position:Math.max(0,s.queue.indexOf(item)-1)}));actions.append(up);const remove=document.createElement("button");remove.className="tiny secondary";remove.textContent="×";remove.title="Remove";remove.addEventListener("click",()=>act("queue_remove",undefined,{id:item.id}));actions.append(remove);li.append(text,actions);queue.append(li)}
$("queueCount").textContent=s.queue&&s.queue.length?`${s.queue.length} waiting`:"";
renderRoom(s.room);
const streams=Array.isArray(s.network_activity)?s.network_activity:[],activityRows=$("networkActivityRows");activityRows.replaceChildren();$("networkActivitySummary").textContent=streams.length?`${streams.length} active stream${streams.length===1?"":"s"} on reachable receivers`:"No active streams reported by reachable receivers";if(!streams.length){const li=document.createElement("li");li.textContent="When someone starts casting on this network, it appears here. Unreachable receivers are omitted.";activityRows.append(li)}else for(const item of streams){const li=document.createElement("li"),title=document.createElement("strong"),detail=document.createElement("span");title.textContent=item.title||"Media title unavailable";detail.className="muted";const time=n=>Number.isFinite(Number(n))?`${Math.floor(Math.max(0,Number(n))/60)}:${String(Math.floor(Math.max(0,Number(n))%60)).padStart(2,"0")}`:"";const timing=item.position==null?"":` · ${time(item.position)}${item.duration==null?"":` / ${time(item.duration)}`}`;detail.textContent=`${item.receiver||"Unknown receiver"} · ${item.protocol||"Receiver"} · ${item.state||"ACTIVE"}${timing}${item.is_local?" · This SmoothCast":""}`;li.replaceChildren(title,document.createElement("br"),detail);activityRows.append(li)}
document.querySelectorAll("[data-action]").forEach(b=>b.disabled=!!s.busy||!s.active);showError("errorDash","");}catch(err){showError("errorDash",err.message)}}
function initials(name){return (name||"?").trim().split(/\s+/).slice(0,2).map(p=>p[0]).join("").toUpperCase()}
function renderRoom(room){const people=$("people");people.replaceChildren();if(room&&room.participants)for(const person of room.participants){const chip=document.createElement("span");chip.className="person"+(person.online?"":" offline");const avatar=document.createElement("span");avatar.className="avatar";avatar.style.background=person.color;avatar.textContent=initials(person.name);const name=document.createElement("span");name.textContent=person.name+(room.me&&room.me.id===person.id?" (you)":"");chip.append(avatar,name);people.append(chip)}const activity=$("activity");activity.replaceChildren();if(room&&room.activity)for(const event of [...room.activity].slice(-12).reverse()){const line=document.createElement("div");line.className="ev";const time=document.createElement("time");time.textContent=new Date(event.at*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});const text=document.createElement("span");text.textContent=describe(event);line.append(time,text);activity.append(line)}}
function describe(event){const name=(event.data&&event.data.name)||"Someone";switch(event.type){case "joined":return name+" joined";case "left":return name+" left";case "voted":return name+" voted on a film";case "action":return name+" used "+(event.data.action||"a control").replaceAll("_"," ");default:return name+" updated the room"}}
async function act(action,value,extra={}){if(busy)return;busy=true;try{const body={action,...extra};if(value!==undefined)body.value=value;const result=await post("/api/action",body);showError("errorDash",result.message||"Command accepted")}catch(err){showError("errorDash",err.message)}finally{busy=false;refresh()}}
document.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",()=>act(b.dataset.action)));
$("seek").addEventListener("change",()=>act("seek",Number($("seek").value)));$("volume").addEventListener("change",()=>act("volume",Number($("volume").value)));
$("musicAutogain").addEventListener("change",()=>act("music_autogain",$("musicAutogain").checked));
async function uploadRequest(method,path,body,headers={}){
  const controller=new AbortController();activeUploadController=controller;
  const deadline=setTimeout(()=>controller.abort(),60000);
  try{
    const response=await fetch(path,{method,credentials:"same-origin",cache:"no-store",headers:{"X-CSRF-Token":csrf,...headers},body,signal:controller.signal});
    const data=await response.json();
    if(!response.ok)throw Object.assign(Error(data.error||"Upload request failed"),{status:response.status});
    return data;
  }finally{clearTimeout(deadline);if(activeUploadController===controller)activeUploadController=null}
}
async function sendChunk(path,file,offset,end){
  const body=file.slice(offset,end),headers={"Content-Type":"application/octet-stream","Content-Range":`bytes ${offset}-${end-1}/${file.size}`};
  for(let attempt=0;;attempt++){
    if(cancelUpload)throw Error("Upload cancelled");
    try{return await uploadRequest("PUT",path,body,headers)}catch(error){
      if(error.status&&error.status<500&&error.status!==409)throw error;
      if(attempt===4||cancelUpload)throw error;
      showError("uploadStatus","Connection interrupted. Retrying…");
      await new Promise(resolve=>setTimeout(resolve,250*2**attempt));
      if(cancelUpload)throw Error("Upload cancelled");
      try{const state=await uploadRequest("GET",path);if(state.received===end)return state}
      catch(statusError){if(statusError.status===404||statusError.status===401)throw statusError}
    }
  }
}
function updateUploadControls(){
  $("uploadButton").disabled=uploading;$("uploadButton").textContent=pendingUpload?"Resume upload":($("uploadQueue").checked?"Upload and add":"Upload and cast");
  $("videoFile").disabled=uploading||!!pendingUpload;$("uploadQueue").disabled=uploading;$("cancelUpload").hidden=!uploading&&!pendingUpload;$("cancelUpload").disabled=cancelUpload;
}
async function discardUpload(){
  if(pendingUpload){try{await uploadRequest("DELETE",pendingUpload.path)}catch(error){if(error.status!==404)throw error}pendingUpload=null}
  showError("uploadStatus","Upload cancelled");
}
$("uploadButton").addEventListener("click",async()=>{
  const file=$("videoFile").files[0];if(!file||uploading)return;
  const queueOnly=$("uploadQueue").checked;uploading=true;cancelUpload=false;updateUploadControls();const json={"Content-Type":"application/json"};
  try{
    let state;
    if(pendingUpload){showError("uploadStatus","Checking saved progress…");state=await uploadRequest("GET",pendingUpload.path)}
    else{showError("uploadStatus","Preparing upload…");state=await uploadRequest("POST","/api/uploads",JSON.stringify({name:file.name,size:file.size,queue:queueOnly}),json);pendingUpload={path:"/api/uploads/"+state.id,chunkSize:state.chunk_size}}
    const {path,chunkSize}=pendingUpload;$("uploadProgress").max=file.size;$("uploadProgress").value=state.received;
    while(state.received<file.size&&!cancelUpload){const end=Math.min(state.received+chunkSize,file.size);state=await sendChunk(path,file,state.received,end);$("uploadProgress").value=state.received;if(state.ready_to_cast)casting=true;const percent=Math.floor(state.received*100/file.size);showError("uploadStatus",casting?`Casting now — still sending the rest of ${file.name}: ${percent}%`:`${queueOnly?"Adding":"Uploading"} ${file.name}: ${percent}%`)}
    if(cancelUpload)await discardUpload();else{$("cancelUpload").disabled=true;const result=await uploadRequest("POST",path+"/complete",JSON.stringify({queue:queueOnly}),json);pendingUpload=null;showError("uploadStatus",result.message||"Upload complete")}
  }catch(error){if(error.status===404)pendingUpload=null;if(cancelUpload){try{await discardUpload()}catch(cancelError){showError("uploadStatus",cancelError.message)}}else showError("uploadStatus",pendingUpload?error.message+" Select Resume upload to retry.":error.message)}
  finally{uploading=false;cancelUpload=false;updateUploadControls()}
});
$("uploadQueue").addEventListener("change",updateUploadControls);
$("cancelUpload").addEventListener("click",async()=>{
  cancelUpload=true;if(activeUploadController)activeUploadController.abort();$("cancelUpload").disabled=true;showError("uploadStatus","Cancelling upload…");if(uploading)return;
  uploading=true;updateUploadControls();try{await discardUpload()}catch(error){showError("uploadStatus",error.message)}
  finally{uploading=false;cancelUpload=false;updateUploadControls()}
});
setInterval(refresh,2000);
</script></body></html>"""
