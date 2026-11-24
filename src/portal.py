"""Small, PIN-protected shared-room dashboard hosted by the GTK application.

The portal uses Python's standard-library HTTP server so SmoothCast adds no
web framework or runtime dependency. GTK callbacks are supplied by the caller
and are dispatched onto the GTK main context by the application layer.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache, wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import errno
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
from urllib.parse import parse_qs, unquote, urlsplit

import actions
import api_spec
import lan_guard
import mesh_files
import library_replication
import portal_commands
import command_trace
import design_tokens
import error_log
import failure_boundary
import peer_discovery
import portal_room
import room_activity
import room_event_replay
import portal_screen_page
import portal_media
import portal_mesh_http
import portal_mesh_panel
import portal_screens_http
import portal_uploads
import shortcut_map
import version


PIN_DIGITS = "0123456789"
PIN_LENGTH = 6
FRIENDLY_NAME_MAX = 32
MAX_BODY = 2048
SESSION_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 128
ATTEMPT_WINDOW_SECONDS = 60
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
REQUEST_TIMEOUT = 5
UPLOAD_CHUNK_TIMEOUT = 30  # Larger chunks from slower Wi-Fi clients.
EVENT_STREAMS_TOTAL = 64
EVENT_STREAMS_PER_PARTICIPANT = 4
EVENT_POLL_SECONDS = 0.25
EVENT_PING_SECONDS = 15.0
EVENT_RESEND_SECONDS = 10.0
QUEUE_COMMAND_TTL = 120.0
QUEUE_COMMAND_CAPACITY = 512
CLIENT_SCHEMA = 1
MIN_PORT = 49152
MAX_PORT = 65535


def preferred_room_port(value: int, *, pick=secrets.randbelow) -> int:
    """First install chooses a high-range port; later installs reuse saved port."""
    if type(value) is not int:
        raise ValueError("Room port must be an integer")
    if value == 0:
        return MIN_PORT + pick(MAX_PORT - MIN_PORT + 1)
    if not MIN_PORT <= value <= MAX_PORT:
        raise ValueError("Room port must be between 49152 and 65535")
    return value


def bind_room_server(address, pin, dispatch, **kwargs):
    """Bind preferred port; fall back only on an actual port collision."""
    try:
        return _PortalHTTPServer(address, pin, dispatch, **kwargs), False
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        return _PortalHTTPServer((address[0], 0), pin, dispatch, **kwargs), True



@dataclass
class _Session:
    csrf: str
    expiry: float
    participant_id: str


class PortalError(RuntimeError):
    """Portal configuration, startup, or dispatch failure."""


class PortalRequestError(Exception):
    """A safe request rejection with an HTTP status and user-facing message."""

    def __init__(self, status: int, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


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


@lru_cache(maxsize=1)
def page_build() -> str:
    """Version plus the served page's hash, never a duplicated release constant."""
    return version.__version__ + "-" + hashlib.sha256(
        (_HTML + portal_screen_page.panel_html() + portal_mesh_panel.panel_html()
         + shortcut_map.browser_json()).encode("utf-8")
    ).hexdigest()[:12]


def _page() -> bytes:
    # Keep optional panels inside #dashboard: their grid placement and login
    # visibility must follow the rest of the authenticated room controls.
    dashboard_close = '</div>\n<dialog id="shortcutsHelp"'
    markup = _HTML.replace(dashboard_close, portal_screen_page.panel_html()
                           + portal_mesh_panel.panel_html() + dashboard_close, 1)
    return (markup.replace("__SC_BUILD__", page_build())
            .replace("__SC_SCHEMA__", str(CLIENT_SCHEMA))
            .replace("__SC_SHORTCUTS__", shortcut_map.browser_json())
            .replace("__SC_ACCENTS__", json.dumps(json.dumps(design_tokens.web_accents(), separators=(",", ":"))))
            ).encode("utf-8")


class _PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, pin: str, dispatch: Callable, *, clock=time.monotonic,
                 pin_required: bool = True,
                 status_snapshot: Callable[[], dict | None] | None = None,
                 uploads: portal_uploads.UploadManager | None = None,
                 hostname: str | None = None,
                 commands: portal_commands.CommandDispatcher | None = None,
                 fence: portal_commands.CommandFence | None = None,
                 peer_directory: peer_discovery.PeerDirectory | None = None,
                 room: portal_room.PortalRoom | None = None) -> None:
        super().__init__(address, _Handler)
        self.pin = pin
        self.dispatch = dispatch
        self.uploads = uploads
        self.room = room or portal_room.PortalRoom(clock=clock)
        self.peer_directory = peer_directory
        self.clock = clock
        self.fence = fence or portal_commands.CommandFence(clock=clock)
        self.commands = commands or portal_commands.CommandDispatcher(
            self._apply_default_command, fence=self.fence, clock=clock)
        self.request_limiter = portal_commands.ParticipantRateLimiter(clock=clock)
        self.pin_required = bool(pin_required)
        self.status_snapshot = status_snapshot
        self.status_peek: Callable[[], tuple[int, dict] | None] | None = None
        self.stopping = threading.Event()
        self._event_lock = threading.Lock()
        self._event_streams: dict[str, int] = {}
        self.room_events = room_event_replay.RoomEventLedger()
        self.library_search: Callable | None = None
        self.library_search_stream: Callable | None = None
        self.library_browser = None
        self.library_replication = None
        self.mesh_files = None
        self.nodes_provider: Callable | None = None
        self.hostname_label = hostname or ""
        self._lock = threading.RLock()  # A PIN check and login must be atomic with revoke.
        self._queue_command_lock = threading.Lock()
        self._queue_command_cache: OrderedDict[tuple[str, str], tuple] = OrderedDict()
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self.queue_ids: set[str] = set()
        portal_screens_http.attach(self)
        self.mesh_feed = None       # set by the app when the mesh runs (#402/#405)
        self._attempts: dict[str, deque[float]] = {}
        self._lockouts: dict[str, float] = {}
        self.failures = failure_boundary.Notifier()
        port = self.server_address[1]
        self._allowed_hosts = {
            f"{self.server_address[0]}:{port}".lower(),
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        }
        if hostname:
            self._allowed_hosts.update({f"{hostname}.local:{port}", f"{hostname}.local"})
        self._allowed_hosts.update({f"{lan_guard.ENTRY_NAME}:{port}", lan_guard.ENTRY_NAME})

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
            envelope.command_id, session_id, revision, result or "Command received; checking receiver state.")

    def acquire_event_stream(self, participant_id: str) -> bool:
        """Admit one more room event stream: at most 64 in total and 4 per participant."""
        with self._event_lock:
            if (sum(self._event_streams.values()) >= EVENT_STREAMS_TOTAL
                    or self._event_streams.get(participant_id, 0) >= EVENT_STREAMS_PER_PARTICIPANT):
                return False
            self._event_streams[participant_id] = self._event_streams.get(participant_id, 0) + 1
            return True

    def release_event_stream(self, participant_id: str) -> None:
        with self._event_lock:
            left = self._event_streams.get(participant_id, 0) - 1
            if left > 0:
                self._event_streams[participant_id] = left
            else:
                self._event_streams.pop(participant_id, None)

    def server_close(self) -> None:
        # TCPServer.__init__ calls this when the bind fails, before the fields
        # below exist. Guard them all, or the AttributeError replaces the
        # EADDRINUSE that bind_room_server needs to fall back to a free port.
        stopping = getattr(self, "stopping", None)
        if stopping is not None:
            stopping.set()
        try:
            screens = getattr(self, "screens", None)
            if screens is not None:
                screens.close()
            commands = getattr(self, "commands", None)
            if commands is not None:
                commands.close()
        finally:
            super().server_close()

    def service_actions(self) -> None:
        """Expire sessions and stale presence on the server's regular poll."""
        with self._lock:
            self._expire_sessions(self.clock())
            live = frozenset(self._sessions)
        self.screens.retain_owner_keys(live.__contains__)
        self.room.expire_inactive(self.clock())

    def host_allowed(self, host: str) -> bool:
        return bool(host) and (host.lower() in self._allowed_hosts or lan_guard.is_entry_host(host))

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
                self.room_events.forget(session.participant_id)

    def login(self, client: str, pin: str,
              name: object = "Guest") -> tuple[str, str, portal_room.Participant]:
        """Authenticate and create the session under one revocation lock.

        A PIN validated before a rotation must never mint a new cookie after it.
        """
        with self._lock:
            if self.pin_required and not self.pin_allowed(client, pin):
                raise PortalRequestError(401, "Incorrect PIN or too many attempts")
            return self.create_session(name)

    def revoke_participant(self, participant_id: str) -> int:
        """Host-only: drop every session for one room identity, not playback."""
        with self._queue_command_lock, self._lock:
            keys = [key for key, value in self._sessions.items()
                    if value.participant_id == participant_id]
            for key in keys:
                self._sessions.pop(key, None)
            if keys:
                self.room.leave(participant_id)
                self.room_events.forget(participant_id)
                for key in list(self._queue_command_cache):
                    if key[0] == participant_id:
                        self._queue_command_cache.pop(key, None)
                # Invalidate queued/late transport envelopes, never stop media.
                self.fence.rotate()
        if keys:
            self.screens.drop_owner_keys(set(keys))
            if self.mesh_feed is not None:
                self.mesh_feed.close_keys(keys)
        if keys and self.uploads is not None:
            self.uploads.revoke_owner_keys(set(keys))
        return len(keys)

    def revoke_all(self) -> str:
        """Host-only: sign out everyone and rotate the room PIN atomically."""
        with self._queue_command_lock, self._lock:
            owner_keys = set(self._sessions)
            participants = {session.participant_id for session in self._sessions.values()}
            self._sessions.clear()
            self.room_events.clear()
            for participant_id in participants:
                self.room.leave(participant_id)
            # A new PIN starts a new room: previous participants and titles
            # must never appear in a new guest's activity feed.
            self.room.reset_history()
            self._queue_command_cache.clear()
            old_pin = self.pin
            new_pin_value = new_pin()
            while new_pin_value == old_pin:
                new_pin_value = new_pin()
            self.pin = new_pin_value
            self._attempts.clear()
            self._lockouts.clear()
            self.fence.rotate()
        self.screens.drop_owner_keys(owner_keys)
        if self.mesh_feed is not None:
            self.mesh_feed.close_keys(owner_keys)
        if owner_keys and self.uploads is not None:
            self.uploads.revoke_owner_keys(owner_keys)
        return new_pin_value

    def create_session(self, name: object = "Guest") -> tuple[str, str, portal_room.Participant]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        now = self.clock()
        with self._lock:
            self._expire_sessions(now)
            while len(self._sessions) >= MAX_SESSIONS:
                key, session = self._sessions.popitem(last=False)
                self.room.leave(session.participant_id)
                self.room_events.forget(session.participant_id)
            # Move stale clients to the dormant roster before checking capacity.
            self.room.expire_inactive(now)
            participant = self.room.join(name, now=now)
            self._sessions[self._session_key(token)] = _Session(
                csrf, now + SESSION_SECONDS, participant.id,
            )
        return token, csrf, participant

    def session_key_active(self, key: object) -> bool:
        """Verify an internal opaque hashed cookie at the execution boundary."""
        if not isinstance(key, str) or len(key) != 64:
            return False
        with self._lock:
            self._expire_sessions(self.clock())
            return key in self._sessions

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
                self.room.touch(session.participant_id, now=now)
            except portal_room.RoomError:
                self._sessions.pop(key, None)
                return None
            self._sessions.move_to_end(key)
            return session.participant_id

    def resume_session(self, token: str | None) -> tuple[str, portal_room.Participant] | None:
        """Return the existing CSRF token and participant for a valid cookie."""
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
                participant = self.room.touch(session.participant_id, now=now)
            except portal_room.RoomError:
                self._sessions.pop(key, None)
                return None
            self._sessions.move_to_end(key)
            return session.csrf, participant

    def execute_queue_command(self, participant_id: str, body: dict,
                              *, session_key: str | None = None) -> tuple[int, str]:
        """Serialize queue edits and replay the receipt for an identical request."""
        command_id = body.get("queue_command_id")
        revision = body.get("queue_revision")
        if (not isinstance(command_id, str)
                or re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", command_id) is None):
            return 400, "Queue command ID is invalid"
        if (isinstance(revision, bool) or not isinstance(revision, int)
                or not 0 <= revision < 2**63):
            return 400, "Queue revision is invalid"
        try:
            fingerprint = hashlib.sha256(json.dumps({
                "participant": participant_id,
                "body": {key: value for key, value in body.items()
                         if key != "queue_command_id"},
            }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            return 400, "Queue command is invalid"
        key = (participant_id, command_id)
        with self._queue_command_lock:
            now = self.clock()
            for old_key, entry in list(self._queue_command_cache.items()):
                if entry[0] <= now:
                    self._queue_command_cache.pop(old_key, None)
            cached = self._queue_command_cache.get(key)
            if cached is not None:
                with command_trace.scope("portal", str(body.get("action") or "queue"),
                                         command_id=command_id, client_id=participant_id):
                    self._queue_command_cache.move_to_end(key)
                    if cached[1] != fingerprint:
                        command_trace.stage("rejected", code=409)
                        return 409, "Queue command ID was already used with different data"
                    return cached[2], cached[3]
            action = body.get("action")
            with command_trace.scope("portal", str(action or "queue"),
                                     command_id=command_id, client_id=participant_id):
                command_trace.stage("dispatched")
                try:
                    payload = ({**body, "_portal_auth_key": session_key}
                               if session_key is not None else body)
                    message = self.dispatch(action, payload)
                    status, result = 202, str(message or "Queue updated")
                except PortalRequestError as exc:
                    status, result = exc.status, exc.message
                except Exception:
                    status, result = 503, "SmoothCast could not accept that queue edit"
                if status >= 400:
                    command_trace.stage("rejected", code=status)
            self.room.record(participant_id, "action", {
                "action": action, "id": body.get("id"),
                "outcome": ("accepted" if status < 400 else
                            "uncertain" if status >= 500 else "rejected"),
                "reason": room_activity.reason_for_status(status),
            }, command_id=command_id)
            self._queue_command_cache[key] = (
                now + QUEUE_COMMAND_TTL, fingerprint, status, result,
            )
            self._queue_command_cache.move_to_end(key)
            while len(self._queue_command_cache) > QUEUE_COMMAND_CAPACITY:
                self._queue_command_cache.popitem(last=False)
            return status, result

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


def _silent_wav(seconds: int = 1, rate: int = 8000) -> bytes:
    """One second of silence: the audio element phones need for lock-screen controls."""
    import struct
    data = bytes([128]) * (rate * seconds)
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
              + b"data" + struct.pack("<I", len(data)))
    return header + data


SILENT_WAV = _silent_wav()


def _guarded(method):
    """Turn anything escaping a request handler into one civil JSON error (#512).

    The traceback goes only to the private log, once per repeating fault; the
    client never sees an interpreter error page or a dropped connection.
    """
    @wraps(method)
    def wrapper(self):
        self._started = False
        try:
            return method(self)
        except (ConnectionError, TimeoutError):
            self.close_connection = True  # the peer went away; nobody to answer
            return None
        except PortalRequestError as exc:
            if not self._started:
                return self._exception_error(exc)
            return None
        except Exception as exc:
            failure = failure_boundary.describe(exc)
        route = "/".join(self._path().split("/")[:3])
        if self.server.failures.allow(failure):
            error_log.log(f"portal {self.command} {route} failed: {failure.detail}")
        self.close_connection = True
        if not self._started:
            try:
                self._error(500, failure.message, code=failure_boundary.CODE)
            except OSError:
                pass
        return None
    return wrapper


def _guard_handlers(cls):
    for name in ("do_GET", "do_POST", "do_PUT", "do_DELETE", "do_HEAD"):
        if name in cls.__dict__:
            setattr(cls, name, _guarded(cls.__dict__[name]))
    return cls


@_guard_handlers
class _Handler(BaseHTTPRequestHandler):
    server: _PortalHTTPServer
    _started = False
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT
    server_version = "SmoothCastPortal"
    sys_version = ""

    def send_response(self, code, message=None):
        self._started = True
        super().send_response(code, message)

    def parse_request(self) -> bool:
        # The trust boundary is the home LAN: refuse any non-LAN peer outright.
        if not super().parse_request():
            return False
        if not lan_guard.is_lan_address(self.client_address[0]):
            self.send_error(403)
            return False
        return True

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths, cookies, PINs, and remote addresses can contain secrets
        # or private LAN details; the portal deliberately emits no access log.
        return

    def _send(self, status: int, payload: dict | bytes, *, content_type="application/json",
              cookie: str | None = None, extra_headers: dict[str, str] | None = None) -> None:
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
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
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
        self._send(status, payload, extra_headers=(
            {"Retry-After": "1"} if status == 429 else None))

    def _exception_error(self, exc: object) -> None:
        """Preserve public wording; include a stable code only if known."""
        code = getattr(exc, "code", None)
        extra = {"code": code} if isinstance(code, str) and code else {}
        self._error(exc.status, exc.message, **extra)

    def _upload_storage_error(self, exc: OSError, stage: str) -> None:
        """Keep expected upload failures actionable and avoid disclosing paths."""
        self.close_connection = True
        if isinstance(exc, TimeoutError):
            return self._error(408, "Upload timed out. Resume from the saved position.")
        if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}:
            return self._error(507, "Not enough space on the SmoothCast host.",
                               code="upload.disk_full")
        error_log.log(f"portal upload {stage} storage error: {type(exc).__name__}, errno={exc.errno}")
        return self._error(503, f"Host could not {stage} the upload. Retry when storage is available.")

    def _safe_origin(self, *, required: bool) -> bool:
        host = self.headers.get("Host", "")
        if not self.server.host_allowed(host):
            return False
        origin = self.headers.get("Origin", "")
        return self.server.origin_allowed(origin, host) if required else (
            not origin or self.server.origin_allowed(origin, host)
        )

    def _mesh_library(self, path: str) -> None:
        """Replication pages for peers (docs/MESH_SEARCH.md section 2, #410)."""
        handler = getattr(self.server, "library_replication", None)
        if handler is None:
            return self._error(404, "Library sharing is not enabled")
        params = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        status, payload, extra = handler.handle(path, params, self.client_address[0])
        if status >= 400:
            return self._send(status, {"ok": False, **payload}, extra_headers=extra)
        body, headers = library_replication.encode(
            payload, "gzip" in self.headers.get("Accept-Encoding", ""))
        return self._send(status, body, extra_headers={**extra, **headers})

    def _nodes_page(self) -> None:
        """Fallback entry page: live SmoothCast computers, for networks without mDNS."""
        import html
        provider = getattr(self.server, "nodes_provider", None)
        try:
            nodes = list(provider()) if provider else []
        except Exception:
            nodes = []
        rows = "".join(
            f'<li><a href="{html.escape(str(n.get("url", "")), quote=True)}">'
            f'{html.escape(str(n.get("name", "SmoothCast")))}</a></li>'
            for n in nodes if isinstance(n, dict) and str(n.get("url", "")).startswith("http://"))
        mine = html.escape(self.server.hostname_label or "This computer")
        body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,"
                "initial-scale=1'><title>SmoothCast computers</title><h1>SmoothCast in this house</h1>"
                "<p>Open any computer to join the room.</p><ul><li><a href='/'>" + mine
                + " (this one)</a></li>" + rows + "</ul>")
        return self._send(200, body.encode("utf-8"), content_type="text/html; charset=utf-8")

    def _mesh_file(self, path: str, *, head: bool) -> None:
        """Ranged media bytes by content key, served locally or proxied (#422)."""
        files = getattr(self.server, "mesh_files", None)
        key = mesh_files.key_from_path(path)
        if files is None or key is None:
            return self._error(404, "That media is not available right now")

        def write_headers(status: int, headers: dict) -> None:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        try:
            files.serve(self, key, head=head, write_headers=write_headers)
        except portal_media.MediaError as exc:
            return self._exception_error(exc)
        self.close_connection = True

    def _libraries(self) -> None:
        """Libraries on the network: nodes and their shared folders, browsable by path (#413)."""
        if not self._authenticated():
            return self._error(401, "Session expired")
        browser = getattr(self.server, "library_browser", None)
        if browser is None:
            return self._send(200, {"origins": []})
        parts = urlsplit(self.path)
        rest = parts.path[len("/api/libraries"):].strip("/")
        if not rest:
            return self._send(200, browser.libraries())
        origin, _, folder = rest.partition("/")
        query = parse_qs(parts.query)
        try:
            result = browser.browse(unquote(origin), unquote(folder),
                                    (query.get("path") or [""])[0],
                                    (query.get("cursor") or [None])[0])
        except ValueError:
            return self._error(400, "That folder path is not valid.")
        if result is None:
            return self._error(404, "That library isn't available right now.")
        return self._send(200, result)

    def _room_payload(self, participant_id: str) -> dict:
        """The authenticated status document shared by /api/status and /api/events."""
        try:
            if self.server.status_snapshot is None:
                state = self.server.dispatch("status", {})
            else:
                state = self.server.status_snapshot()
                if state is None:
                    raise PortalRequestError(503, "Status snapshot is not ready")
        except Exception as exc:
            raise PortalRequestError(503, "SmoothCast is not ready to report playback state") from exc
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
        self.server.room.remember({m["id"]: m.get("title") for m in merged})
        self.server.room.prune(live_ids)
        state["queue"] = merged
        state["room"] = self.server.room.snapshot(participant_id)
        directory = self.server.peer_directory
        state["screens"] = self.server.screens.snapshot()
        state["peers"] = directory.snapshot() if directory is not None else []
        state["peer_discovery_available"] = directory is not None
        return {"ok": True, "state": state, "build": page_build(),
                "client_schema": CLIENT_SCHEMA, "stream_epoch": self.server.room_events.epoch}

    def _event_key(self) -> tuple | None:
        """Cheap change detector over the published snapshot; ignores the moving playhead."""
        peeked = self.server.status_peek() if self.server.status_peek is not None else None
        if peeked is None:
            return None
        state = peeked[1]
        queue = state.get("queue") if isinstance(state.get("queue"), list) else []
        items = tuple((q.get("id"), q.get("title")) for q in queue if isinstance(q, dict))
        fields = tuple(state.get(k) for k in (
            "title", "state", "receiver", "duration", "volume", "can_seek", "active", "busy",
            "session_id", "revision", "queue_revision", "music_autogain"))
        return fields, items, self.server.room.seq

    def _events(self) -> None:
        """GET /api/events: server-sent room state, one event per change (#316 slice 1)."""
        if not self._authenticated():
            return self._error(401, "Session expired")
        participant_id = self.server.session_participant(self._cookie_token())
        if participant_id is None:
            return self._error(401, "Session expired")
        if not self.server.acquire_event_stream(participant_id):
            return self._send(429, {"ok": False, "error": "Too many room streams are open. Close one and retry.",
                                    "code": "room.rate_limited"}, extra_headers={"Retry-After": "5"})
        try:
            first = self._room_payload(participant_id)
        except PortalRequestError as exc:
            self.server.release_event_stream(participant_id)
            return self._error(exc.status, exc.message)
        # Last-Event-ID is an untrusted hint; authentication has already passed.
        # Replay is scoped to the participant, then a full current snapshot
        # reconciles any changes made during the disconnected interval.
        replay, resync = self.server.room_events.replay(
            participant_id, self.headers.get("Last-Event-ID"))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        clock, server = self.server.clock, self.server
        key = self._event_key()
        last_write = last_state = clock()
        payload = first
        try:
            for frame in replay:
                self.wfile.write(frame)
            if replay:
                self.wfile.flush()
            while True:
                if payload is not None:
                    self.wfile.write(server.room_events.publish(
                        participant_id, payload, resync=resync))
                    resync = None
                    self.wfile.flush()
                    last_write = last_state = clock()
                    payload = None
                if server.stopping.wait(EVENT_POLL_SECONDS):
                    return
                if server.session_participant(self._cookie_token()) is None:
                    return
                now = clock()
                current = self._event_key()
                if current != key or now - last_state >= EVENT_RESEND_SECONDS:
                    try:
                        payload = self._room_payload(participant_id)
                        key = current
                    except PortalRequestError:
                        pass
                elif now - last_write >= EVENT_PING_SECONDS:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_write = now
        except (OSError, ValueError):
            pass
        finally:
            server.release_event_stream(participant_id)

    def _search_stream(self) -> None:
        """Server-sent events: cached results at once, late origins as they answer."""
        if not self._authenticated():
            return self._error(401, "Session expired")
        stream = getattr(self.server, "library_search_stream", None)
        text = (parse_qs(urlsplit(self.path).query).get("q") or [""])[0]
        if not text.strip():
            return self._error(400, "Type something to search.")
        if stream is None:
            return self._error(404, "House search is not enabled")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event, payload in stream(text, 50):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        self.close_connection = True

    def _search(self) -> None:
        """GET /api/search?q=&limit=&cursor= over the local library (#409)."""
        if not self._authenticated():
            return self._error(401, "Session expired")
        if self._throttle("read"):
            return
        engine = getattr(self.server, "library_search", None)
        query = parse_qs(urlsplit(self.path).query)
        text = (query.get("q") or [""])[0]
        if not text.strip():
            return self._error(400, "Type something to search.")
        if engine is None:
            return self._send(200, {"q": text[:200], "partial": False, "groups": [], "next": None})
        try:
            limit = int((query.get("limit") or ["50"])[0])
        except ValueError:
            limit = 50
        cursor = (query.get("cursor") or [None])[0]
        try:
            return self._send(200, engine(text, limit, cursor))
        except Exception:
            return self._error(503, "Search is unavailable right now.")

    def _body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise PortalRequestError(400, "Request could not be read. Retry the action.") from exc
        if length < 0:
            raise PortalRequestError(400, "Request could not be read. Retry the action.")
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
        # Any valid authenticated request is activity, including upload chunks
        # and media status reads from a client whose regular roster poll paused.
        if self.server.session_participant(self._cookie_token()) is None:
            return False
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
        return True

    def _throttle(self, route_class: str) -> bool:
        """Bound authenticated traffic; internal desktop callbacks bypass HTTP."""
        participant = self.server.session_participant(self._cookie_token())
        if participant is None:
            self._error(401, "Session expired")
            return True
        delay = self.server.request_limiter.retry_after(participant, route_class)
        if delay <= 0:
            return False
        self._send(
            429, {"ok": False, "error": "Too many room requests. Try again shortly.",
                  "code": "room.rate_limited"},
            extra_headers={"Retry-After": str(max(1, math.ceil(delay)))},
        )
        return True

    def _client_compatible(self) -> bool:
        """Reject stale browser writes before mutation or GTK dispatch."""
        schema = self.headers.get("X-SmoothCast-Client-Schema")
        build = self.headers.get("X-SmoothCast-Client-Build")
        # Older headless/CLI integrations omit Fetch Metadata. An old browser
        # tab, however, sends Sec-Fetch-Mode and must reload before mutating.
        browser_fetch = bool(self.headers.get("Sec-Fetch-Mode"))
        if schema is None and build is None and not browser_fetch:
            return True
        if schema == str(CLIENT_SCHEMA) and build == page_build():
            return True
        self._error(
            409, "SmoothCast was updated. Reload this page to continue.",
            code="client_reload_required",
            build=page_build(), client_schema=CLIENT_SCHEMA,
        )
        return False

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if not self._safe_origin(required=False):
            return self._error(400, "Invalid host")
        if path == "/nodes":
            return self._nodes_page()
        if path == "/api/openapi.json":
            return self._send(200, api_spec.spec())
        if path == "/silence.wav":
            return self._send(200, SILENT_WAV, content_type="audio/wav")
        if path in {"/", "/index.html"}:
            page = _page().replace(
                b"__PIN_REQUIRED__", b"1" if self.server.pin_required else b"0")
            return self._send(200, page, content_type="text/html; charset=utf-8")
        if portal_screens_http.route(self, "GET", path):
            return
        if portal_mesh_http.route(self, "GET", path):
            return
        if path == "/api/libraries" or path.startswith("/api/libraries/"):
            return self._libraries()
        if path == "/api/search/stream":
            return self._search_stream()
        if path == "/api/search":
            return self._search()
        if path.startswith("/mesh/library/"):
            return self._mesh_library(path)
        if path.startswith("/mesh/file/"):
            return self._mesh_file(path, head=False)
        if path == "/api/config":
            return self._send(200, {"pin_required": self.server.pin_required,
                                    "name": self.server.hostname_label})
        if path == "/api/session":
            resumed = self.server.resume_session(self._cookie_token())
            if resumed is None:
                return self._error(401, "Session expired")
            if self._throttle("read"):
                return
            csrf, participant = resumed
            return self._send(200, {
                "ok": True, "csrf": csrf,
                "participant": participant.public(self.server.clock()),
                "build": page_build(), "client_schema": CLIENT_SCHEMA,
            })
        if path == "/api/events":
            return self._events()
        if path == "/api/status":
            if not self._authenticated():
                return self._error(401, "Enter the PIN shown in SmoothCast")
            if self._throttle("read"):
                return
            participant_id = self.server.session_participant(self._cookie_token())
            if participant_id is None:
                return self._error(401, "Session expired")
            try:
                payload = self._room_payload(participant_id)
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            return self._send(200, payload)
        upload_id = self._upload_route(path)
        if upload_id and self._authenticated():
            if self._throttle("upload"):
                return
            if self.server.uploads is None:
                return self._error(503, "Upload storage is unavailable")
            try:
                return self._send(200, {"ok": True, **self.server.uploads.status(
                    self._cookie_token() or "", upload_id)})
            except portal_uploads.UploadError as exc:
                return self._exception_error(exc)
        if upload_id:
            return self._error(401, "Enter the PIN shown in SmoothCast")
        return self._error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        path = self._path()
        if (path in {"/api/login", "/api/action", "/api/profile"}
                or path.startswith("/api/uploads")) and not self._client_compatible():
            return
        if (path in {"/api/action", "/api/profile"} or path.startswith("/api/uploads")):
            if self._authenticated(csrf=True) and self._throttle(
                    "upload" if path.startswith("/api/uploads") else "mutation"):
                return
        if portal_screens_http.route(self, "POST", path):
            return  # parses its own body; must run before the generic parse
        if path == "/api/uploads":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            try:
                if self.server.uploads is None:
                    return self._error(503, "Upload storage is unavailable")
                body = self._body()
                token = self._cookie_token() or ""
                created = self.server.uploads.create(
                    token, body.get("name"), body.get("size"),
                    self.client_address[0], queue_only=bool(body.get("queue", True)))
                key = self.server._session_key(token)
                if not self.server.session_key_active(key):
                    self.server.uploads.revoke_owner_keys({key})
                    return self._error(403, "Room access was revoked")
            except PortalRequestError as exc:
                return self._exception_error(exc)
            except portal_uploads.UploadError as exc:
                return self._exception_error(exc)
            except OSError as exc:
                return self._upload_storage_error(exc, "prepare")
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
                    default_queue = True
                queue_only = default_queue or bool(body.get("queue", default_queue))
                token = self._cookie_token() or ""
                key = self.server._session_key(token)
                media_path, name, dispatch = self.server.uploads.finalize(
                    token, upload_id)
                if not self.server.session_key_active(key):
                    self.server.uploads.finish_dispatch(token, upload_id, accepted=False)
                    self.server.uploads.revoke_owner_keys({key})
                    return self._error(403, "Room access was revoked")
                if dispatch:
                    try:
                        self.server.dispatch("queue_add" if queue_only else "cast_upload", {
                            "path": str(media_path), "name": name,
                            "upload_id": upload_id, "early": False,
                            "client": self.client_address[0],
                            "_portal_auth_key": key,
                        })
                    except PortalRequestError:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise
                    except Exception as exc:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise PortalRequestError(503, "SmoothCast could not start this upload") from exc
                message = ("Added to the shared queue." if queue_only else
                           "Upload received; casting started.")
                return self._send(202, {"ok": True, "message": message})
            except PortalRequestError as exc:
                return self._exception_error(exc)
            except portal_uploads.UploadError as exc:
                return self._exception_error(exc)
            except OSError as exc:
                return self._upload_storage_error(exc, "finalise")
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        try:
            body = self._body()
        except PortalRequestError as exc:
            return self._exception_error(exc)
        if path == "/api/login":
            pin = body.get("pin")
            if not isinstance(pin, str):
                pin = ""
            client = self.client_address[0]
            name = body.get("name", "Guest")
            if not isinstance(name, str):
                return self._error(400, "Your name must be text")
            token = self._cookie_token()
            resumed = self.server.resume_session(token)
            try:
                if resumed is not None:
                    csrf, participant = resumed
                    assert token is not None
                else:
                    token, csrf, participant = self.server.login(client, pin, name)
            except (portal_room.RoomError, PortalRequestError) as exc:
                return self._exception_error(exc)
            cookie = (f"sc_portal_session={token}; Path=/; HttpOnly; SameSite=Strict; "
                      f"Max-Age={SESSION_SECONDS}")
            return self._send(200, {
                "ok": True, "csrf": csrf,
                "participant": participant.public(self.server.clock()),
                "room": self.server.room.snapshot(participant.id),
                "build": page_build(), "client_schema": CLIENT_SCHEMA,
            }, cookie=cookie)
        if path == "/api/profile":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            name = body.get("name")
            if not isinstance(name, str):
                return self._error(400, "Your name must be text")
            participant_id = self.server.session_participant(self._cookie_token())
            if participant_id is None:
                return self._error(401, "Session expired")
            try:
                participant = self.server.room.rename(participant_id, name)
            except portal_room.RoomError as exc:
                return self._exception_error(exc)
            return self._send(200, {"ok": True,
                                    "participant": participant.public(self.server.clock())})
        if path == "/api/action":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            action = body.get("action")
            envelope: portal_commands.MutationEnvelope | None = None
            participant_id: str | None = None
            try:
                envelope = portal_commands.parse_envelope(body)
                participant_id = self.server.session_participant(self._cookie_token())
                if participant_id is None:
                    return self._error(401, "Session expired")
                if envelope is None:
                    if not isinstance(action, str) or action not in actions.WEB_ACTIONS:
                        return self._error(400, "Unsupported action")
                    if action == "queue_add_key" and not (
                            isinstance(body.get("key"), str)
                            and re.fullmatch(r"qh:[0-9a-f]{32}", body["key"])):
                        return self._error(400, "That search result is not valid")
                    participant_id = self.server.session_participant(self._cookie_token())
                    if participant_id is None:
                        return self._error(401, "Session expired")
                    if action in {"queue_play", "queue_remove", "queue_move", "queue_next", "queue_vote"}:
                        item_id = body.get("id")
                        if not isinstance(item_id, str) or item_id not in self.server.queue_ids:
                            return self._error(
                                404, "That queue item is no longer here", code="room.queue_item_gone")
                    if action == "queue_move":
                        position = body.get("position")
                        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
                            return self._error(400, "Queue position must be a non-negative integer")
                    if action == "queue_vote":
                        value = body.get("value")
                        if not isinstance(value, bool):
                            return self._error(400, "Vote must be true or false")
                        try:
                            with command_trace.scope("portal", "queue_vote"):
                                command_trace.stage("dispatched")
                                result = self.server.room.vote(participant_id, body["id"], value)
                        except portal_room.RoomError as exc:
                            return self._exception_error(exc)
                        return self._send(202, {"ok": True, "message": "Vote saved",
                                                "vote": result})
                    if action in {"queue_remove", "queue_move", "queue_next", "queue_clear"}:
                        status, message = self.server.execute_queue_command(
                            participant_id, body,
                            session_key=self.server._session_key(self._cookie_token() or ""),
                        )
                        if status >= 400:
                            return self._error(status, message, **(
                                {"conflict": True} if status == 409 else {}
                            ))
                        return self._send(status, {
                            "ok": True, "message": message,
                            "queue_command_id": body.get("queue_command_id"),
                        })
                    if action in {"next", "previous", "queue_play", "queue_add_key"}:
                        try:
                            with command_trace.scope("portal", action):
                                command_trace.stage("dispatched")
                                result = self.server.dispatch(action, {
                                    **body, "_portal_auth_key": self.server._session_key(
                                        self._cookie_token() or ""),
                                })
                        except PortalRequestError as exc:
                            self.server.room.record(participant_id, "action", {
                                "action": action, "id": body.get("id"),
                                "outcome": "rejected" if exc.status < 500 else "uncertain",
                                "reason": room_activity.reason_for_status(exc.status),
                            })
                            return self._exception_error(exc)
                        except Exception:
                            self.server.room.record(participant_id, "action", {
                                "action": action, "outcome": "uncertain", "reason": "error",
                            })
                            return self._error(503, "SmoothCast could not accept that command")
                        self.server.room.record(participant_id, "action",
                                                {"action": action, "id": body.get("id"),
                                                 "outcome": "accepted"})
                        return self._send(202, {"ok": True, "message": result or "Command received; checking receiver state."})
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
                receipt = self.server.commands.execute(envelope, participant_key=participant_id)
            except portal_commands.CommandError as exc:
                if envelope is not None and participant_id is not None:
                    self.server.room.record(participant_id, "action", {
                        "action": envelope.action,
                        "outcome": "uncertain" if exc.status >= 500 else "rejected",
                        "reason": room_activity.reason_for_status(exc.status),
                    }, command_id=envelope.command_id)
                extra = {}
                if exc.status == 409:
                    extra["conflict"] = True
                if exc.revision is not None:
                    extra["revision"] = exc.revision
                if exc.session_id is not None:
                    extra["session_id"] = exc.session_id
                if exc.code is not None:
                    extra["code"] = exc.code
                return self._error(exc.status, exc.message, **extra)
            if envelope is not None and participant_id is not None:
                self.server.room.record(participant_id, "action", {
                    "action": envelope.action, "outcome": "accepted",
                }, command_id=envelope.command_id)
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

    def _start_early_cast(self, upload_id: str, result: dict) -> bool:
        """Ask SmoothCast to cast the growing file before it finishes arriving.

        Best-effort: a rejection (busy, unsupported) declines early casting and
        the upload continues, so the completed file is still cast on finalize.
        """
        try:
            self.server.dispatch("cast_upload", {
                "path": result["cast_path"], "name": result["name"],
                "upload_id": upload_id, "early": True,
                "client": result.get("client", ""),
                "_portal_auth_key": self.server._session_key(self._cookie_token() or ""),
            })
            accepted = True
        except Exception:
            accepted = False
        self.server.uploads.mark_early_cast(upload_id, accepted=accepted)
        return accepted

    def do_PUT(self) -> None:  # noqa: N802
        if self._path().startswith("/api/uploads") and not self._client_compatible():
            return
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        if self._throttle("upload"):
            return
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
            return self._error(413, f"Upload chunks must be at most {portal_uploads.CHUNK_SIZE // (1024 * 1024)} MiB")
        # A valid 8 MiB upload may take longer than an ordinary API request
        # on congested Wi-Fi; never extend the timeout for unrelated routes.
        self.connection.settimeout(UPLOAD_CHUNK_TIMEOUT)
        try:
            result = self.server.uploads.append(
                self._cookie_token() or "", upload_id,
                self.headers.get("Content-Range", ""), length, self.rfile)
            if result.get("ready_to_cast"):
                result["early_cast_accepted"] = self._start_early_cast(upload_id, result)
            # The staged path is an internal dispatch detail, never part of
            # the browser's diagnostic or transfer receipt.
            result.pop("cast_path", None)
            return self._send(200, {"ok": True, **result})
        except portal_uploads.UploadError as exc:
            self.close_connection = True
            return self._exception_error(exc)
        except OSError as exc:
            return self._upload_storage_error(exc, "store")
        finally:
            self.connection.settimeout(REQUEST_TIMEOUT)

    def do_DELETE(self) -> None:  # noqa: N802
        if self._path().startswith("/api/uploads") and not self._client_compatible():
            return
        if portal_screens_http.route(self, "DELETE", self._path()):
            return
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        if self._throttle("upload"):
            return
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.server.uploads is None:
            return self._error(503, "Upload storage is unavailable")
        try:
            self.server.uploads.cancel(self._cookie_token() or "", upload_id)
            return self._send(200, {"ok": True})
        except portal_uploads.UploadError as exc:
            return self._exception_error(exc)

    def _not_allowed(self) -> None:
        self._error(405, "Method not allowed")

    def do_HEAD(self) -> None:  # noqa: N802
        # Only authenticated media may answer HEAD; every other path stays 405.
        if not self._safe_origin(required=False):
            return self._error(400, "Invalid host")
        if self._path().startswith("/mesh/file/"):
            return self._mesh_file(self._path(), head=True)
        if not portal_screens_http.route(self, "HEAD", self._path()):
            self._not_allowed()

    do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815


class Portal:
    """One-interface LAN portal with a per-run PIN and clean thread shutdown."""

    def __init__(self, bind_ip: str, dispatch: Callable, *, pin: str | None = None,
                 uploads: portal_uploads.UploadManager | None = None,
                 status_snapshot: Callable[[], dict | None] | None = None,
                 status_peek: Callable[[], tuple[int, dict] | None] | None = None,
                 name: str | None = None,
                 commands: portal_commands.CommandDispatcher | None = None,
                 fence: portal_commands.CommandFence | None = None,
                 pin_required: bool = True,
                 preferred_port: int = 0) -> None:
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
        requested = preferred_room_port(preferred_port)
        self.server, self.port_fallback = bind_room_server(
            (self.bind_ip, requested), self.pin, dispatch,
            uploads=self.uploads, hostname=self.name,
            status_snapshot=status_snapshot,
            commands=commands, fence=fence,
            room=self.room, pin_required=pin_required,
        )
        self.port = int(self.server.server_address[1])
        self.server.status_peek = status_peek
        self.url = f"http://{self.bind_ip}:{self.port}/"
        self.friendly_url = f"http://{self.name}.local:{self.port}/"
        self._zeroconf = None
        self._service_info = None
        self._advertise()
        self.peer_discovery_available = False
        try:
            self.peers = peer_discovery.PeerDirectory(
                self.bind_ip, self.name, self.port, zeroconf=self._zeroconf,
            )
            self.peer_discovery_available = True
        except Exception:
            self.peers = None
        self.server.peer_directory = self.peers
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.1},
                                       name="smoothcast-portal", daemon=True)
        self.thread.start()

    def revoke_guest(self, participant_id: str) -> int:
        """Host desktop operation: eject one participant without affecting playback."""
        return self.server.revoke_participant(participant_id)

    def end_guest_access(self) -> str:
        """Host desktop operation: invalidate every cookie and replace the PIN."""
        self.pin = self.server.revoke_all()
        return self.pin

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
        peers, self.peers = self.peers, None
        if peers is not None:
            peers.close()
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
:root{font:16px system-ui,sans-serif;color-scheme:light dark}/*TOKENS*/
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.05rem;margin:0 0 12px}p{color:var(--muted);margin:.35rem 0}
section{background:var(--card);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 26px var(--shadow)}
label{display:block;margin:12px 0 6px}input,button{font:inherit;min-height:44px;border-radius:10px;border:1px solid var(--border);padding:8px 12px}
input{width:100%;color:inherit;background:var(--input)}button{background:var(--accent);color:white;border:0;font-weight:650;cursor:pointer}
#musicAutogain{width:auto;min-height:0;margin-right:8px}
dialog#shortcutsHelp{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:14px;max-width:min(92vw,480px);width:100%;padding:20px}
dialog#shortcutsHelp::backdrop{background:var(--scrim)}
#shortcutsList{display:grid;gap:8px}
#shortcutsList li{display:flex;justify-content:space-between;gap:12px;align-items:center}
#shortcutsList kbd{border:1px solid var(--border);border-radius:6px;padding:4px 7px;white-space:nowrap}
button.secondary{background:var(--secondary);color:var(--on-secondary)}button:disabled,input:disabled{opacity:.55;cursor:not-allowed}.actions{display:flex;gap:8px;flex-wrap:wrap}
.actions button{flex:1 1 120px}.actions input{flex:1 1 160px;min-width:0}.muted{color:var(--muted)}.big{font-size:1.35rem;font-weight:700}.row{display:flex;justify-content:space-between;gap:12px}
progress{width:100%;height:10px}ul{padding-left:0;list-style:none}li{padding:4px 0;overflow-wrap:anywhere}#error{color:var(--danger);min-height:1.4em}
.participants{display:flex;flex-wrap:wrap;gap:7px;margin:4px 0 0}.person{display:flex;align-items:center;gap:6px;background:var(--input);border:1px solid var(--chip-line);border-radius:999px;padding:4px 9px 4px 4px;font-size:.82rem}.person.offline{opacity:.45}.avatar{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:.68rem;font-weight:750;color:var(--avatar-text)}
.queue-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border-top:1px solid var(--line);padding:8px 0}.queue-item:first-child{border-top:0}.queue-item strong{display:block;font-size:.88rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue-item .muted{font-size:.74rem}.queue-actions{display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.tiny{min-height:32px;padding:4px 8px;font-size:.76rem;border-radius:8px}.vote{background:var(--vote);border:1px solid var(--vote-line);color:var(--on-vote)}.vote.on{background:var(--vote-on);color:white}.activity{display:grid;gap:4px;font-size:.78rem;color:var(--muted);max-height:160px;overflow:auto}.activity .ev{display:flex;gap:7px}.activity time{color:var(--dim);white-space:nowrap}.empty{color:var(--muted);border:1px dashed var(--border);border-radius:10px;padding:12px;text-align:center}
header{padding:16px 0;border-bottom:1px solid var(--header-line)}header h1{font-size:clamp(1.6rem,5vw,2.2rem);letter-spacing:-.04em}
nav{display:flex;flex-wrap:wrap;gap:4px;margin:12px 0}nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 12px;border-radius:10px;background:var(--nav);color:var(--on-nav);text-decoration:none}nav a:hover{background:var(--nav-hover)}
#login{max-width:30rem;margin:24px auto}#login button{width:100%}#pin{letter-spacing:.25em}button:not(.secondary):not(.vote){color:var(--on-accent)}
@media(max-width:480px){.queue-item{grid-template-columns:minmax(0,1fr)}.queue-actions{justify-content:flex-start}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}@media(max-width:480px){main{padding:12px}section{padding:15px}}

/* Guest-first room layout: semantic tokens, progressive disclosure and touch-safe help. */
[hidden]{display:none!important}
main{max-width:1120px;padding:clamp(12px,3vw,28px)}
.site-head{display:flex;align-items:center;gap:14px;padding:18px 0 22px}
.site-mark{display:grid;place-items:center;flex:none;width:48px;height:48px;border-radius:14px;background:var(--accent);color:var(--on-accent);font-size:1.6rem;font-weight:800}
.site-head p{line-height:1.5}
.eyebrow{font-size:.74rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
#login{max-width:660px;margin:24px auto}
#login h2{font-size:clamp(1.4rem,4vw,1.85rem);letter-spacing:-.025em}
#login .steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0;margin:22px 0;list-style:none}
#login .steps li{background:var(--input);border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0;font-size:.88rem}
.steps strong{display:block;margin-bottom:4px;color:var(--text)}
.field-hint,.section-desc{font-size:.88rem;line-height:1.5;color:var(--muted);margin:0 0 12px}
.field-hint{margin:6px 0}
#dashboard{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
#dashboard>section,#dashboard>details,#dashboard>.welcome,#dashboard>p{margin:0;min-width:0}
#dashboard>nav,#dashboard>.welcome,#dashboard>#errorDash,#dashboard>#advancedPanel,#dashboard>#castEntry,#dashboard>#screensPanel,#dashboard>#meshPanel{grid-column:1/-1}
#dashboard nav{position:sticky;top:0;z-index:10;display:flex;flex-wrap:nowrap;overflow-x:auto;gap:6px;margin:0;padding:8px 0;background:var(--bg);scrollbar-width:thin}
#dashboard nav a{white-space:nowrap;flex:none}
.welcome{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 20px}
.welcome h2{font-size:1.2rem;margin:6px 0}
.quick-links{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.quick-links a{display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;border-radius:10px;border:1px solid var(--border);text-decoration:none;color:var(--text);background:var(--input);font-weight:650}
.quick-links a:hover{background:var(--nav-hover)}
.room-link{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end;border-top:1px solid var(--line);padding-top:12px;margin-top:14px}
.room-link label{grid-column:1/-1;margin:0;font-weight:650}
.room-link input{min-width:0;margin:0;background:var(--input)}
.room-link button{white-space:nowrap;min-height:44px}
.room-link #roomLinkStatus{grid-column:1/-1;margin:0;min-height:1.2em}
@media(max-width:350px){.room-link{grid-template-columns:minmax(0,1fr)}.room-link button{width:100%}}
.room-heading{display:flex;gap:10px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}
.room-heading h2{margin:0 0 9px}
#dashboard section{scroll-margin-top:78px}
#playback .actions button{min-height:52px}
#playback #title{overflow-wrap:anywhere}
#playback #volume{margin-top:5px}
#findChips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
#findChips button[aria-pressed="true"]{outline:2px solid var(--focus);outline-offset:1px}
#queuePanel #clearQueue{margin:8px 0 4px}
#queuePanel #queue{margin:12px 0 0}
#queuePanel .queue-actions button{min-height:44px;min-width:44px}
#queuePanel #clearQueue,#findChips .tiny{min-height:44px}
.toggle{display:flex;align-items:flex-start;gap:10px;min-height:44px;padding:8px 0}
.toggle input[type="checkbox"]{width:20px;min-height:20px;height:20px;flex:none;margin:1px 0 0;accent-color:var(--accent)}
.toggle span{flex:1;min-width:0}
.help{border-top:1px solid var(--line);margin-top:14px;padding-top:11px}
.help summary{font-weight:650;cursor:pointer;min-height:44px;display:flex;align-items:center;gap:7px;color:var(--text)}
.help summary::marker{color:var(--accent)}
.help .help-body{background:var(--input);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:7px;font-size:.87rem;line-height:1.55}
.help .help-body p{margin:.4rem 0}.help .help-body p:first-child{margin-top:0}.help .help-body p:last-child{margin-bottom:0}
#advancedPanel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 20px;scroll-margin-top:78px}
#advancedPanel>summary{cursor:pointer;font-size:1.05rem;font-weight:750;min-height:44px;align-content:center}
#advancedPanel>p{font-size:.88rem;margin:6px 0}
.advanced-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-top:14px}
.advanced-grid>section{margin:0;box-shadow:none;border:1px solid var(--line);min-width:0}
.advanced-grid h3{font-size:1rem;margin:0 0 8px}
#dashboard #errorDash:not(:empty){background:var(--input);padding:12px;border-radius:10px}
#uploadCard #videoFile{max-width:100%}
.transfer-journey{margin:14px 0;padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--input);min-width:0}
.transfer-steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px;padding:0;margin:0 0 14px;list-style:none}
.transfer-steps li{display:grid;justify-items:center;text-align:center;align-content:start;gap:6px;font-size:.69rem;line-height:1.25;color:var(--muted);min-width:0}
.stage-dot{display:grid;place-items:center;width:27px;height:27px;border:1px solid var(--line);border-radius:50%;font-weight:700;background:var(--card);color:var(--text)}
.transfer-steps li.done .stage-dot{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.transfer-steps li.active{font-weight:750;color:var(--text)}.transfer-steps li.active .stage-dot{outline:2px solid var(--focus);outline-offset:2px}
.transfer-route{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:7px;font-size:.78rem;padding:10px 6px;border-radius:10px;border:1px dashed var(--line);overflow-wrap:anywhere}
.transfer-route strong{color:var(--text)}
.transfer-meter,.transfer-stats{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.transfer-meter{margin:13px 0 7px}.transfer-stats{margin:8px 0 0;font-variant-numeric:tabular-nums;color:var(--muted);font-size:.8rem}
#uploadStatus{overflow-wrap:anywhere;min-height:1.3em}
.transfer-live{border-top:1px solid var(--line);margin-top:14px;padding-top:12px;min-width:0}
.transfer-live h3{font-size:.95rem;margin:0 0 8px}
.transfer-live-file{font-weight:650;overflow-wrap:anywhere;margin:0 0 8px}
.transfer-live-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,145px),1fr));gap:8px;margin:0}
.transfer-live-grid div{border:1px solid var(--line);border-radius:9px;padding:8px;min-width:0}
.transfer-live-grid dt{font-size:.72rem;color:var(--muted);margin-bottom:4px}
.transfer-live-grid dd{margin:0;font-size:.84rem;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.transfer-live #transferEvents{white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;margin:8px 0 0;font-size:.76rem;line-height:1.55;font-family:inherit;color:var(--text)}
.transfer-live details{margin-top:10px}
.transfer-live summary{cursor:pointer;font-weight:650;min-height:44px;align-content:center}
#uploadCard.drop-active{outline:3px dashed var(--focus);outline-offset:3px}
#uploadCard .upload-view-queue{display:inline-flex;align-items:center;min-height:44px;padding:9px 10px;font-weight:650;color:var(--accent);text-decoration:underline;text-underline-offset:3px}
#uploadCard .actions{align-items:center}
#queuePanel .queue-position{display:inline-block;margin-right:8px;padding:2px 7px;border-radius:7px;background:var(--input);color:var(--muted);font-variant-numeric:tabular-nums}
#queuePanel .queue-actions button[data-queue-action="play"]{background:var(--accent);color:var(--on-accent)}
#queuePanel .queue-actions button[data-queue-action="remove"]{border:1px solid var(--line)}
#queuePanel .queue-actions{justify-content:flex-start;row-gap:6px}
#queuePanel .queue-actions button{min-height:44px;padding:7px 11px;white-space:nowrap}
#queueFeedback{min-height:1.4em;padding:7px 10px;border-radius:8px;background:var(--input)}
#queuePanel .queue-item{padding:13px 0;gap:10px}
@media(min-width:560px){#queuePanel .queue-item{grid-template-columns:minmax(0,1fr)}#queuePanel .queue-actions{justify-content:flex-start}}
@media(max-width:380px){.transfer-journey{padding:10px}.transfer-steps{gap:2px}.transfer-steps li{font-size:.62rem}.stage-dot{width:23px;height:23px}}

@media(min-width:820px){
  #dashboard{grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr)}
  #dashboard>nav,#dashboard>.welcome,#dashboard>#errorDash,#dashboard>#advancedPanel,#dashboard>#castEntry,#dashboard>#screensPanel,#dashboard>#meshPanel{grid-column:1/-1}
  #playback,#uploadCard{grid-column:1}
  #findPanel,#queuePanel{grid-column:2}
  #peoplePanel{grid-column:1/-1}
  .advanced-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:560px){
  #login .steps{grid-template-columns:1fr}
  #login .steps li{padding:9px 12px}
  .site-mark{width:42px;height:42px}
  .welcome{padding:14px}
  .actions button{flex:1 1 42%}
  #dashboard nav{margin-inline:-4px}
}

</style></head><body><main><header class="site-head"><span class="site-mark" aria-hidden="true">S</span><div><h1>SmoothCast</h1><p>Watch, listen and build the queue together — on your own Wi-Fi.</p></div></header>
<div id="updateNotice" role="alert" hidden><strong>SmoothCast was updated</strong><p>Reload to reconnect safely.</p><button id="reloadNow" type="button">Reload page</button></div>
<section id="login" aria-labelledby="joinTitle"><p class="eyebrow">Welcome to the shared room</p><h2 id="joinTitle">Join the house</h2>
<p>Use your phone or computer as a remote, add your own music or films, and help choose what's next. No app, account or cloud connection needed.</p>
<ol class="steps" aria-label="How SmoothCast works"><li><strong>1. Join</strong>Enter a name so everyone knows who's here.</li><li><strong>2. Add or find</strong>Choose something from the house or upload a file.</li><li><strong>3. Share the queue</strong>Vote, move items and control the room together.</li></ol>
<form id="loginForm"><label for="name">Your display name</label><p class="field-hint" id="nameHint">Shown to others in this room. You can change it later.</p>
<input id="name" name="name" maxlength="40" autocomplete="nickname" placeholder="e.g. Sam" aria-describedby="nameHint" required>
<div id="pinRow"><label for="pin">House PIN</label><p class="field-hint" id="pinHint">Ask the host for the six-digit House PIN shown in SmoothCast.</p>
<input id="pin" name="pin" minlength="6" maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" aria-describedby="pinHint" required></div>
<p id="loginHint" class="field-hint">You must be on the same local network. A House PIN is required only if the host has enabled one.</p>
<p id="error" role="alert" aria-live="polite"></p><button type="submit">Join</button></form>
<details class="help"><summary>Room privacy and what guests can do</summary><div class="help-body"><p>Everyone who joins can control playback and contribute to the same Up Next queue. Playback actions affect the selected TV or speaker, not just your phone.</p><p>The room runs on the host's local network, not in the cloud. Only join rooms you trust, and ask the host if you are unsure.</p></div></details>
</section>
<div id="dashboard" hidden>
<nav aria-label="Jump to room section"><a href="#playback">Now Playing</a><a href="#findPanel">Find</a><a href="#uploadCard">Add files</a><a href="#queuePanel">Up Next</a><a href="#screensPanel">Screens</a><a id="meshNavLink" href="#meshPanel" hidden>Network</a><a href="#peoplePanel">People</a><a href="#advancedPanel">More</a></nav>
<div class="welcome"><p class="eyebrow">Connected to the room</p><h2>You're part of the queue</h2><p class="field-hint"><span id="joinedAs" aria-live="polite"></span> · <a href="#nameForm">Change name</a></p><p class="section-desc">Choose something to watch or listen to, or vote on what's next. Changes here are shared with everybody in the room.</p><div class="quick-links"><a href="#castEntry">Cast with SmoothCast</a><a href="#findPanel">Find something</a><a href="#uploadCard">Add from this device</a><a href="#queuePanel">See Up Next</a></div><div class="room-link"><label for="roomLinkText">Share this room link</label><input id="roomLinkText" type="text" readonly aria-describedby="roomLinkHint" title="Local address guests can open in their browser"><button id="roomLinkCopy" type="button">Copy link</button><p id="roomLinkHint" class="field-hint">Send this address to someone on the same Wi-Fi. The link contains no PIN or account information.</p><p id="roomLinkStatus" role="status" aria-live="polite"></p></div></div>
<section id="castEntry" aria-labelledby="castEntryHeading"><h2 id="castEntryHeading">Cast with SmoothCast</h2><p class="section-desc">Choose media already available in your room or transfer a file from this device. This page uses SmoothCast room controls; it does not appear in Chrome’s native Cast… menu, which is not yet supported.</p><div class="quick-links"><a href="#findPanel">Find something on the network</a><a href="#uploadCard">Add a file from this device</a></div></section>
<p id="errorDash" role="status" aria-live="polite"></p>
<section id="playback" aria-labelledby="playbackHeading">
<div class="room-heading"><h2 id="playbackHeading" tabindex="-1">Now Playing</h2><span id="state" class="muted">—</span></div>
<p class="section-desc">These controls affect the room's selected TV or speaker.</p>
<p id="title" class="big">Nothing playing</p><p id="receiver">Receiver: —</p>
<progress id="progress" max="1" value="0" aria-label="Playback progress"></progress>
<div class="row"><span id="elapsed">0:00</span><span id="duration">—</span></div>
<label for="seek">Playback position</label><p id="seekHelp" class="field-hint">Drag to a point in the film or track. Seeking is unavailable if its length is unknown or the receiver cannot seek.</p>
<input id="seek" type="range" min="0" max="1" value="0" aria-describedby="seekHelp" title="Seek within the current film or track" disabled>
<div class="actions"><button data-action="play_pause" title="Toggle playback for everyone using this receiver">Play / pause</button><button class="secondary" data-action="stop" title="Stop playing on the room receiver">Stop</button><button class="secondary" data-action="previous" title="Go to the previous item for everyone">Previous</button><button class="secondary" data-action="next" title="Skip to the next item for everyone">Next</button></div>
<label for="volume">Receiver volume</label><p class="field-hint" id="volumeHelp">Changes the selected receiver's volume, not the volume of this phone.</p>
<input id="volume" type="range" min="0" max="100" value="0" aria-describedby="volumeHelp" title="Change the room receiver volume" disabled><p id="volumeText" class="muted">—</p>
<details class="help"><summary>Explain playback controls</summary><div class="help-body"><p><strong>Play / pause</strong> resumes or pauses the selected receiver. <strong>Stop</strong> ends its current playback. <strong>Previous</strong> and <strong>Next</strong> change what everybody hears or sees.</p><p><strong>Seek</strong> changes the current position without changing the shared queue. If a control is dimmed, the receiver is not ready or does not support that action.</p></div></details>
</section>
<section id="findPanel" aria-labelledby="findHeading"><h2 id="findHeading">Find something to play</h2>
<p class="section-desc">Search shared libraries on nearby SmoothCast computers, then choose an available result.</p>
<label for="findInput">Search films, shows and music</label><input id="findInput" type="search" placeholder="Search the house" autocomplete="off" maxlength="200">
<div id="findChips" role="group" aria-label="Filter search results"><button type="button" class="tiny secondary" data-kind="film" aria-pressed="false">Films</button><button type="button" class="tiny secondary" data-kind="show" aria-pressed="false">Shows</button><button type="button" class="tiny secondary" data-kind="music" aria-pressed="false">Music</button><button type="button" class="tiny secondary" data-kind="video" aria-pressed="false">Videos</button><button type="button" class="tiny secondary" data-available="1" aria-pressed="false">Available now</button></div>
<p id="findStatus" class="muted" role="status" aria-live="polite"></p><div id="findResults" aria-label="Search results"></div>
<details id="libraries" class="help"><summary>Browse libraries on the network</summary><div id="libBody" class="muted">Loading libraries...</div></details>
<details class="help"><summary>How search and availability work</summary><div class="help-body"><p>Search finds media advertised by SmoothCast hosts on your network. <strong>Available now</strong> limits results to items that can currently be reached; an unavailable host may return later.</p><p>Use the result's action to play or add it to Up Next. If you have a file on your own device, use <strong>Add files</strong> instead.</p></div></details>
</section>
<section id="uploadCard" aria-labelledby="uploadHeading" hidden><h2 id="uploadHeading">Add files from this device</h2>
<p class="section-desc">Choose music or video stored on your phone or computer; SmoothCast transfers it to the host over your local network.</p>
<label for="videoFile">Audio or video files</label><input id="videoFile" type="file" accept="audio/*,video/*,.mkv,.ts,.wmv" multiple title="Choose media stored on this device">
<p id="uploadSelectionHint" class="field-hint">Choose files, or drop them anywhere in this panel. Audio always goes to Up Next. You can pause safely and resume while this browser still has the file.</p>
<label class="toggle" for="uploadQueue"><input id="uploadQueue" type="checkbox" checked><span><strong>Add to Up Next</strong><span class="field-hint" style="display:block">Recommended. Keep what's playing uninterrupted.</span></span></label>
<div id="transferJourney" class="transfer-journey" aria-label="File transfer stages">
<ol id="transferSteps" class="transfer-steps" aria-label="Transfer stages">
<li data-stage="choose" class="done"><span class="stage-dot">1</span><span>Choose file</span></li>
<li data-stage="prepare"><span class="stage-dot">2</span><span>Prepare</span></li>
<li data-stage="transfer"><span class="stage-dot">3</span><span>Transfer</span></li>
<li data-stage="verify"><span class="stage-dot">4</span><span>Check media</span></li>
<li data-stage="deliver"><span class="stage-dot">5</span><span>Queue / play</span></li>
</ol>
<div class="transfer-route" aria-label="Current file route"><span>Your device</span><span aria-hidden="true">→</span><strong id="transferHost">SmoothCast host</strong><span aria-hidden="true">→</span><strong id="transferDestination">Up Next</strong></div>
<div class="transfer-meter"><strong id="transferStage" aria-live="polite">Ready to choose</strong><span id="transferPercent">0%</span></div>
<progress id="uploadProgress" max="1" value="0" aria-label="File transfer bytes received"></progress>
<div class="transfer-stats"><span id="transferBytes">0 B of 0 B</span><span id="transferRate">—</span><span id="transferEta">—</span></div>
<div class="transfer-live" aria-labelledby="transferLiveHeading">
<h3 id="transferLiveHeading">Live transfer monitor</h3>
<p id="transferFileName" class="transfer-live-file">No active file</p>
<dl class="transfer-live-grid">
<div><dt>Current operation</dt><dd id="transferOperation">Idle</dd></div>
<div><dt>Time in operation</dt><dd id="transferElapsed">—</dd></div>
<div><dt>Current chunk sent by browser</dt><dd id="transferInFlight">—</dd></div>
<div><dt>Last host response</dt><dd id="transferResponse">—</dd></div>
<div><dt>Room action</dt><dd id="transferDelivery">Not submitted</dd></div>
<div><dt>Last confirmed offset</dt><dd id="transferAck">—</dd></div>
<div><dt>Current room receiver (independent of upload)</dt><dd id="transferRoomState">Awaiting room status</dd></div>
</dl>
<details open><summary>Transfer activity · newest first</summary><pre id="transferEvents" aria-label="Recent transfer activity" tabindex="0">Choose a file to begin. Events appear here as they happen.</pre></details>
</div>
<p id="transferExplanation" class="field-hint">A percentage measures bytes received by this host. Bytes sent by the browser are not yet confirmed on disk. Media checks and queue or playback confirmation follow afterwards. Cross-node routing will appear only when a mesh transfer session confirms it.</p>
</div><p id="uploadStatus" role="status" aria-live="polite"></p>
<div class="actions"><button id="uploadButton" type="button" title="Transfer the selected files to the room" aria-describedby="uploadSelectionHint" disabled>Upload and add</button><button id="pauseUpload" class="secondary" type="button" hidden>Pause transfer</button><button id="cancelUpload" class="secondary" type="button" hidden>Cancel upload</button><a class="upload-view-queue" href="#queuePanel">View shared Up Next</a></div>
<details class="help"><summary>How uploads and Play now work</summary><div class="help-body"><p><strong>With Add to Up Next selected:</strong> media goes into the shared waiting queue when it is ready; current playback is not replaced.</p><p><strong>With it unticked:</strong> compatible video may start playing on the selected room receiver as it transfers. <strong>Audio always goes into Up Next</strong>, even when this option is unticked.</p><p>Transfers happen on the local network and may resume after a brief interruption. Keep this page open until the transfer has finished.</p></div></details>
</section>
<section id="queuePanel" aria-labelledby="queueHeading"><div class="room-heading"><h2 id="queueHeading">Up Next</h2><span id="queueCount" class="muted"></span></div>
<p class="section-desc">Choose <strong>Play now</strong> to request immediate room playback, or <strong>Next</strong> to put an item first in line without stopping the current film. Everyone here can reorder or remove waiting items.</p>
<p id="queueFeedback" class="field-hint" role="status" aria-live="polite">Queue changes appear here when accepted by the host.</p>
<button id="clearQueue" class="secondary tiny" type="button" title="Remove waiting items without stopping what is playing" disabled>Clear Up Next</button>
<ul id="queue" aria-label="Shared Up Next queue" tabindex="-1"><li class="empty">Nothing in Up Next yet</li></ul>
<details class="help"><summary>What do the queue buttons mean?</summary><div class="help-body"><p><strong>Vote</strong> shows you want this item played; it does not automatically reorder the queue. <strong>Play now</strong> starts the item on the room receiver; <strong>Next</strong> moves it to be played after the current item.</p><p><strong>↑ / ↓</strong> move a waiting item earlier or later. <strong>×</strong> removes it from Up Next. <strong>Clear Up Next</strong> empties waiting items without stopping the currently playing item.</p><p>If someone else edits the queue at the same time, SmoothCast refreshes before letting you retry.</p></div></details>
</section>
<section id="peoplePanel" aria-labelledby="peopleHeading"><h2 id="peopleHeading">People in the room</h2>
<p class="section-desc">See who is connected, update your own name and follow recent room activity.</p>
<div id="people" class="participants"></div>
<form id="nameForm"><label for="displayName">Your display name</label><div class="actions"><input id="displayName" maxlength="40" autocomplete="nickname" required><button class="secondary" type="submit">Update name</button></div></form>
<h3 style="margin:18px 0 8px;font-size:1rem">Recent activity</h3><label for="activityFilter" class="muted">Show</label> <select id="activityFilter" aria-controls="activity"><option value="all">Everything</option><option value="playback">Playback</option><option value="queue">Up Next</option><option value="people">People</option><option value="problems">Problems</option></select><p id="activityEmpty" class="muted" hidden>Nothing here yet for this filter.</p><div id="activity" class="activity" role="log" aria-live="polite" aria-relevant="additions" aria-label="Room activity"></div>
<details class="help"><summary>Who can see my name and actions?</summary><div class="help-body"><p>Your display name and activity such as joining, voting and queue changes can be seen by people in this shared room. Only you can change your display name.</p></div></details>
</section>
<details id="advancedPanel"><summary>More settings and network information</summary><p>Optional controls for phones, music and other devices. Most guests will not need to change these.</p>
<div class="advanced-grid">
<section aria-labelledby="phoneHeading"><h3 id="phoneHeading">Phone remote</h3>
<label class="toggle"><input id="lockControls" type="checkbox" checked><span><strong>Lock-screen controls</strong><span class="field-hint" style="display:block">Use play, pause and skip from your phone's lock screen or headphones while this page is open.</span></span></label>
<label class="toggle"><input id="keepScreenOn" type="checkbox"><span><strong>Keep screen on</strong><span class="field-hint" style="display:block">Ask your browser to keep the display awake while you use this remote. Your device may not support it.</span></span></label>
<p id="remoteDimHint" role="status" hidden>Your browser may dim the screen. Use Guided Access/kiosk mode for a docked iPad.</p>
</section>
<section aria-labelledby="musicHeading"><h3 id="musicHeading">Music playback</h3>
<label class="toggle"><input id="musicAutogain" type="checkbox"><span><strong>Normalise audio-only tracks</strong><span class="field-hint" style="display:block">Reduce big volume differences between tracks. Existing programme or album normalisation takes precedence.</span></span></label>
<details class="help"><summary>Audio normalisation details</summary><div class="help-body"><p>Targets -16 LUFS with a -1.5 dBTP true-peak ceiling. This applies to audio-only playback where the host supports processing.</p></div></details>
</section>
<section aria-labelledby="peerHeading"><h3 id="peerHeading">Nearby SmoothCast hosts</h3><p class="section-desc">Open another SmoothCast computer's room if you want to switch hosts. It has its own access settings; discovery does not grant permission.</p><ul id="peers"><li class="empty">No other SmoothCast hosts found</li></ul></section>
<section id="networkActivity" aria-labelledby="networkHeading"><h3 id="networkHeading">On your network</h3><p class="section-desc">Read-only status from reachable Cast and DLNA receivers, refreshed every 15 seconds. No commands are sent to these other receivers.</p><p id="networkActivitySummary" class="muted" role="status" aria-live="polite">Checking discovered receivers…</p><ul id="networkActivityRows"><li>No active streams reported by reachable receivers</li></ul></section>
</div></details></div>
<dialog id="shortcutsHelp" aria-labelledby="shortcutsHeading"><h2 id="shortcutsHeading">Keyboard shortcuts</h2><p>Available when you are not typing in a field.</p><ul id="shortcutsList"></ul><button id="shortcutsClose" type="button">Close</button></dialog></main>
<script>
const PAGE_BUILD="__SC_BUILD__",CLIENT_SCHEMA=Number("__SC_SCHEMA__");
const SHORTCUTS=typeof __SC_SHORTCUTS__==="undefined"?[]:__SC_SHORTCUTS__,shortcutMap=new Map(SHORTCUTS.map(entry=>[entry.key,entry]));
let stalePage=false,shortcutState=null;
function showUpdateNotice(){
  stalePage=true;
  roomEvents.stop();
  void syncRemoteWakeLock();
  document.getElementById("updateNotice").hidden=false;
  document.getElementById("dashboard").hidden=true;
  document.getElementById("uploadCard").hidden=true;
  document.getElementById("reloadNow").focus?.({preventScroll:true});
}
document.getElementById("reloadNow").addEventListener("click",()=>location.reload());
function matchingBuild(data){
  if(data?.build===PAGE_BUILD&&data.client_schema===CLIENT_SCHEMA)return true;
  showUpdateNotice();return false;
}
const clientHeaders={"X-SmoothCast-Client-Schema":String(CLIENT_SCHEMA),"X-SmoothCast-Client-Build":PAGE_BUILD};
let rateDelayUntil=0;
const pendingControls=new Map(),editingControls=new Set();
let csrf="",busy=false,uploading=false,cancelUpload=false,casting=false,pendingUpload=null,batchFiles=null,batchIndex=0,batchAdded=0,batchTotal=0,batchQueueOnly=true,activeUploadController=null,queueRevision=0,queueCommandSeq=0;const $=id=>document.getElementById(id),showError=(id,msg)=>$(id).textContent=msg;

const roomInviteLink=location.origin+"/";
$("roomLinkText").value=roomInviteLink;
$("roomLinkCopy").addEventListener("click",async()=>{
  try{
    if(!navigator.clipboard?.writeText)throw Error("Clipboard unavailable");
    await navigator.clipboard.writeText(roomInviteLink);
    $("roomLinkStatus").textContent="Room link copied. Share it with someone on the same Wi-Fi.";
  }catch(_){
    $("roomLinkText").focus();
    $("roomLinkText").select();
    $("roomLinkStatus").textContent="Link selected. Copy it manually and share it on the same Wi-Fi.";
  }
});

async function post(path,body){if(stalePage)throw Error("Reload required");const r=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf,...clientHeaders},body:JSON.stringify(body)});const d=await r.json();if(d.code==="client_reload_required"){showUpdateNotice();throw Error(d.error||"Reload required")}if(r.status===429){const retryAfter=Math.max(1,Number(r.headers.get("Retry-After"))||1);rateDelayUntil=Date.now()+retryAfter*1000;throw Object.assign(Error("Too many controls at once. Try again shortly."),{status:429,retryAfter})}if(!r.ok)throw Error(d.error||"Request failed");return d}
const keepScreenOn=$("keepScreenOn");
let remoteWakeLock=null,requestingWakeLock=false,remoteDimHintSeen=false;
try{
  keepScreenOn.checked=localStorage.getItem("sc_keep_screen_on")==="1";
  remoteDimHintSeen=localStorage.getItem("sc_remote_dim_hint")==="1";
}catch(_){}
function wantsRemoteWakeLock(){
  return keepScreenOn.checked&&!!csrf&&!stalePage&&!document.hidden;
}
async function syncRemoteWakeLock(){
  if(!wantsRemoteWakeLock()){
    const lock=remoteWakeLock;
    remoteWakeLock=null;
    if(lock&&!lock.released){try{await lock.release()}catch(_){}}
    return;
  }
  if(requestingWakeLock||(remoteWakeLock&&!remoteWakeLock.released))return;
  requestingWakeLock=true;
  try{
    const lock=await navigator.wakeLock.request("screen");
    if(!wantsRemoteWakeLock()){await lock.release();return}
    remoteWakeLock=lock;
    lock.addEventListener("release",()=>{
      if(remoteWakeLock===lock)remoteWakeLock=null;
    });
  }catch(_){
    if(wantsRemoteWakeLock()&&!remoteDimHintSeen){
      remoteDimHintSeen=true;
      $("remoteDimHint").hidden=false;
      try{localStorage.setItem("sc_remote_dim_hint","1")}catch(_){}
    }
  }finally{requestingWakeLock=false}
}
keepScreenOn.addEventListener("change",()=>{
  try{localStorage.setItem("sc_keep_screen_on",keepScreenOn.checked?"1":"0")}catch(_){}
  if(!keepScreenOn.checked)$("remoteDimHint").hidden=true;
  return syncRemoteWakeLock();
});
const PIN_REQUIRED="__PIN_REQUIRED__"!=="0";
const loginButton=$("loginForm").querySelector("button");
function showJoinedName(value){
  const name=typeof value==="string"&&value.trim()?value.trim():"Guest";
  $("joinedAs").textContent="Joined as "+name;
}
function configureOpenJoin(){
  // This is presentation only; the host still decides whether a PIN is required.
  $("pinRow").hidden=true;
  $("pin").required=false;
  $("pin").value="";
  $("loginHint").textContent="Enter your name to join the house.";
  loginButton.textContent="Join";
}
if(!PIN_REQUIRED)configureOpenJoin();
$("loginForm").addEventListener("submit",async e=>{
  e.preventDefault();
  if(loginButton.disabled)return;
  loginButton.disabled=true;
  showError("error","");
  try{
    const d=await post("/api/login",{pin:$("pin").value.trim(),name:$("name").value.trim()});
    if(!matchingBuild(d))return;
    csrf=d.csrf;
    $("pin").value="";
    try{localStorage.setItem("sc_name",d.participant.name)}catch(_){}
    $("displayName").value=d.participant.name;
    showJoinedName(d.participant.name);
    $("login").hidden=true;
    void syncRemoteWakeLock();
    void restoreUpload();
    refresh();
  }catch(err){showError("error",err.message)}
  finally{loginButton.disabled=false}
});
(()=>{
  async function restoreSession(){
    try{
      const response=await fetch("/api/session",{credentials:"same-origin",cache:"no-store"});
      if(!response.ok)return false;
      const data=await response.json();
      if(!data.ok||!data.csrf||!data.participant)return false;
      if(!matchingBuild(data))return true;
      csrf=data.csrf;
      try{localStorage.setItem("sc_name",data.participant.name)}catch(_){}
      $("displayName").value=data.participant.name;
      showJoinedName(data.participant.name);
      $("login").hidden=true;
      void syncRemoteWakeLock();
      void restoreUpload();
      refresh();
      return true;
    }catch(_){return false}
  }
  restoreSession().then(restored=>{
    if(restored||PIN_REQUIRED)return;
    let saved="";try{saved=localStorage.getItem("sc_name")||""}catch(_){}
    if(saved){$("name").value=saved;loginButton.click()}
  });
})();
function expireSession(){
  csrf="";
  roomEvents.stop();
  void syncRemoteWakeLock();
  shortcutState=null;
  pendingControls.clear();
  statusFailures=0;
  $("dashboard").hidden=true;
  $("uploadCard").hidden=true;
  $("login").hidden=false;
  loginButton.disabled=uploading;
  if(activeUploadController)activeUploadController.abort();
  if(!uploading)resetUploadBatch();
  showError("errorDash","");
  showError("error",PIN_REQUIRED
    ?"Room access expired. Enter the current PIN to reconnect."
    :"Room access expired. Enter your name to rejoin.");
  $(PIN_REQUIRED?"pin":"name").focus();
}
function clock(s){if(s==null||!Number.isFinite(s))return "--:--";s=Math.floor(Math.max(0,s));const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;return h?`${h}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`:`${m}:${String(sec).padStart(2,"0")}`}
function projectPosition(s,ageMs,sinceMs){const p=Number(s.position),d=Number(s.duration),dur=Number.isFinite(d)&&d>0?d:0;if(!Number.isFinite(p)||p<0)return 0;if(s.state!=="PLAYING")return dur?Math.min(p,dur):p;const rate=s.rate,speed=typeof rate==="number"&&Number.isFinite(rate)&&rate>=0.05&&rate<=4?rate:1;const lead=Math.min(Math.max(0,Number(ageMs)||0)+Math.max(0,Number(sinceMs)||0),21600000)/1000,v=p+lead*speed;return dur?Math.min(v,dur):v}
let playhead=null,paintedAt=-1;
function trackPlayhead(s){playhead={s,age:Number(s.snapshot_age_ms)||0,at:performance.now()};paintedAt=-1;paintPlayhead()}
function paintPlayhead(){if(!playhead)return;const pos=projectPosition(playhead.s,playhead.age,performance.now()-playhead.at);if(Math.abs(pos-paintedAt)<0.2)return;paintedAt=pos;const dur=Number(playhead.s.duration)||0;$("progress").value=Math.min(pos,dur||pos);$("elapsed").textContent=clock(pos);if(!editingControls.has("seek"))$("seek").value=Math.min(pos,dur||pos)}
function playheadFrame(){if(!document.hidden)paintPlayhead();requestAnimationFrame(playheadFrame)}
let queueRenderKey=null,queuePressed=false,deferredQueue=null,queueState=[];
const queueElement=$("queue");
function queueAction(button){
  const row=button.closest("[data-queue-id]");
  if(!row)return;
  const id=row.dataset.queueId;
  const index=queueState.findIndex(item=>String(item.id)===id);
  if(index<0){showError("errorDash","That queue item is no longer here");return}
  const item=queueState[index];
  const verb={vote:"Vote",play:"Requesting playback", "move-earlier":"Move earlier", "move-later":"Move later",next:"Move to play next",remove:"Remove"}[button.dataset.queueAction];
  const feedback=$("queueFeedback");
  if(feedback&&verb)feedback.textContent=verb+" · "+(item.title||"selected item")+" · sending request…";
  switch(button.dataset.queueAction){
    case "vote":return act("queue_vote",!item.voted,{id});
    case "play":return act("queue_play",undefined,{id});
    case "move-earlier":return act("queue_move",undefined,{id,position:Math.max(0,index-1)});
    case "move-later":return act("queue_move",undefined,{id,position:Math.min(queueState.length-1,index+1)});
    case "next":return act("queue_next",undefined,{id});
    case "remove":return act("queue_remove",undefined,{id});
  }
}
queueElement.addEventListener("click",event=>{
  const button=event.target?.closest?.("[data-queue-action]");
  if(button&&queueElement.contains(button))queueAction(button);
});
queueElement.addEventListener("pointerdown",event=>{
  if(event.target?.closest?.("[data-queue-action]"))queuePressed=true;
});
function releaseQueuePointer(){
  if(!queuePressed)return;
  queuePressed=false;
  const pending=deferredQueue;
  deferredQueue=null;
  if(pending)renderQueue(pending);
}
// Click follows pointerup, so retain the pressed button until its click runs.
document.addEventListener("pointerup",()=>setTimeout(releaseQueuePointer,0));
document.addEventListener("pointercancel",releaseQueuePointer);
function renderQueue(items){
  const queue=queueElement,rows=Array.isArray(items)?items:[];
  if(queuePressed){deferredQueue=rows;return}
  queueState=rows;
  const key=JSON.stringify(rows.map(item=>[
    item.id,item.title,item.duration,item.votes,item.voted,
  ]));
  if(key===queueRenderKey)return;
  const focused=document.activeElement;
  const focusedRow=focused?.closest?.("[data-queue-id]");
  const focusTarget=focusedRow&&focused.dataset?.queueAction
    ?{id:focusedRow.dataset.queueId,action:focused.dataset.queueAction}:null;
  queueRenderKey=key;
  const oldRows=new Map(Array.from(queue.children)
    .filter(row=>row.dataset?.queueId).map(row=>[row.dataset.queueId,row]));
  const nodes=[];
  if(!rows.length){
    const empty=document.createElement("li");
    empty.className="empty";
    empty.textContent="Nothing in Up Next yet";
    nodes.push(empty);
  }else rows.forEach((item,index)=>{
    const itemTitle=typeof item.title==="string"&&item.title?item.title:"Video";
    const id=String(item.id||"");
    let li=oldRows.get(id);
    if(!li){
      li=document.createElement("li");
      li.className="queue-item";
      li.dataset.queueId=id;
      const text=document.createElement("div");
      text.append(document.createElement("strong"),document.createElement("div"));
      text.children[1].className="muted";
      const actions=document.createElement("div");
      actions.className="queue-actions";
      for(const action of ["vote","play","move-earlier","move-later","next","remove"]){
        const button=document.createElement("button");
        button.dataset.queueAction=action;
        actions.append(button);
      }
      li.append(text,actions);
    }
    li.setAttribute("aria-posinset",String(index+1));
    li.setAttribute("aria-setsize",String(rows.length));
    li.children[0].children[0].textContent=itemTitle;
    li.children[0].children[1].textContent="Position "+(index+1)+" of "+rows.length+" · "+(item.votes?"▲ "+item.votes+" vote"+(item.votes===1?"":"s"):"No votes")
      +(item.duration?" · "+clock(item.duration):"");
    const buttons=li.children[1].children;
    const labels=[
      (item.voted?"Remove vote for":"Vote for")+" "+itemTitle,
      "Play "+itemTitle+" now",
      "Move "+itemTitle+" earlier in Up Next",
      "Move "+itemTitle+" later in Up Next",
      "Play "+itemTitle+" next",
      "Remove "+itemTitle+" from Up Next",
    ];
    const captions=[item.voted?"Voted":"Vote","Play now","↑ Earlier","↓ Later","Play next","Remove"];
    Array.from(buttons).forEach((button,i)=>{
      button.textContent=captions[i];
      button.setAttribute("aria-label",labels[i]);
      button.title=labels[i];
      button.className="tiny"+(i===0?" vote"+(item.voted?" on":""):"")
        +([2,3,4,5].includes(i)?" secondary":"");
      button.disabled=(i===2&&index===0)||(i===3&&index===rows.length-1);
    });
    nodes.push(li);
  });
  queue.replaceChildren(...nodes);
  if(focusTarget){
    const row=nodes.find(item=>item.dataset?.queueId===focusTarget.id);
    const target=row&&Array.from(row.children[1].children)
      .find(item=>item.dataset.queueAction===focusTarget.action);
    (target||queue).focus({preventScroll:true});
  }
}
let statusRequest=null,statusTimer=null,statusFailures=0;
function scheduleRefresh(){
  clearTimeout(statusTimer);
  if(!csrf||stalePage||document.hidden||roomEvents.healthy())return;
  const delay=statusFailures?Math.min(30000,2000*2**statusFailures+Math.random()*500):2000;
  statusTimer=setTimeout(refresh,Math.max(delay,rateDelayUntil-Date.now()));
}
function makeRoomEvents(env){
  let source=null,retry=null,watch=null,failures=0,last=0,healthy=false;
  const delays=[1000,2000,4000,8000,15000];
  function stop(){env.clearTimeout(retry);retry=null;env.clearInterval(watch);watch=null;if(source){source.close();source=null}healthy=false}
  function fail(){stop();if(!env.canRun())return;env.fallback();retry=env.setTimeout(start,delays[Math.min(failures++,4)])}
  function start(){
    if(!env.EventSource||source||!env.canRun())return;
    const es=new env.EventSource("/api/events");source=es;last=env.now();
    es.addEventListener("state",e=>{let d;try{d=JSON.parse(e.data)}catch(x){return}last=env.now();healthy=true;failures=0;env.apply(d)});
    es.onerror=fail;
    watch=env.setInterval(()=>{if(env.now()-last>30000)fail()},5000);
  }
  return {start,stop,healthy:()=>healthy};
}
const roomEvents=makeRoomEvents({
  EventSource:typeof EventSource==="function"?EventSource:null,
  apply:d=>{if(!busy)applyStatus(d)},
  canRun:()=>!!csrf&&!stalePage&&!document.hidden,
  fallback:()=>scheduleRefresh(),
  setTimeout:(f,ms)=>setTimeout(f,ms),clearTimeout:id=>clearTimeout(id),
  setInterval:(f,ms)=>setInterval(f,ms),clearInterval:id=>clearInterval(id),
  now:()=>Date.now()
});
// Raw markup is also executed by headless browser contract tests before
// server-side placeholders are substituted. Treat that as no preset data.
const ROOM_ACCENTS=(()=>{try{return JSON.parse(__SC_ACCENTS__)}catch(_){return {}}})();
let appliedAccent="";
function applyAccentPreset(value){
  const preset=Object.hasOwn(ROOM_ACCENTS,value)?value:"default";
  const colours=ROOM_ACCENTS[preset];
  if(!colours||preset===appliedAccent)return;
  appliedAccent=preset;
  const root=document.documentElement.style;
  for(const scheme of ["dark","light"]){
    root.setProperty("--sc-user-accent-"+scheme,colours[scheme].accent);
    root.setProperty("--sc-user-on-accent-"+scheme,colours[scheme].on_accent);
  }
}
let roomSnapshotEpoch="",roomSnapshotVersion=-1;
// A delayed poll or SSE frame must never roll a newer same-run film state back.
function acceptRoomSnapshot(d){const epoch=d&&d.stream_epoch,ver=d&&d.state&&d.state.snapshot_version;if(typeof epoch!=="string"||!epoch||epoch.length>64||!Number.isSafeInteger(ver)||ver<0)return true;if(epoch!==roomSnapshotEpoch){roomSnapshotEpoch=epoch;roomSnapshotVersion=ver;return true}if(ver<roomSnapshotVersion)return false;roomSnapshotVersion=ver;return true}
function playbackToggleCopy(state){
  if(state==="PLAYING"||state==="BUFFERING")return ["Pause","Pause playback on the selected room receiver for everyone"];
  if(state==="PAUSED")return ["Resume","Resume playback on the selected room receiver for everyone"];
  return ["Play / pause","Toggle playback on the selected room receiver for everyone"];
}
function renderPlaybackToggle(state){
  const button=document.querySelector('[data-action="play_pause"]');
  if(!button)return;
  const [label,description]=playbackToggleCopy(state);
  if(button.textContent!==label)button.textContent=label;
  button.title=description;
  button.setAttribute("aria-label",description);
}
function showJoinedRoom(){
  const entering=$("dashboard").hidden;
  $("dashboard").hidden=false;
  $("uploadCard").hidden=false;
  if(entering)$("playbackHeading").focus({preventScroll:true});
}
function applyStatus(d){
  if(!matchingBuild(d))return false;
  if(!acceptRoomSnapshot(d))return true;
    const s=d.state||{};applyAccentPreset(s.accent);shortcutState=s;syncMediaSession(s);renderPlaybackToggle(s.state);$("state").textContent=s.state_label||"State unavailable";$("title").textContent=s.title||"Nothing playing";$("receiver").textContent="Receiver: "+(s.receiver||"—");monitorText("transferRoomState",(s.receiver||"No receiver selected")+" · "+(s.state_label||"State unavailable"));
queueRevision=Number.isSafeInteger(s.queue_revision)?s.queue_revision:0;const duration=Number(s.duration)||0,position=Number(s.position)||0;$("progress").max=duration||1;$("progress").value=Math.min(position,duration||position);if(!editingControls.has("seek")){$("seek").max=duration||1;$("seek").value=Math.min(position,duration||position);$("seek").disabled=!s.can_seek||!duration;}$("elapsed").textContent=clock(position);$("duration").textContent=clock(duration);trackPlayhead(s);if(!editingControls.has("volume")){$("volume").disabled=s.volume==null;$("volume").value=s.volume||0;$("volumeText").textContent=s.volume==null?"Volume unavailable":`${s.volume}%`;}
$("musicAutogain").checked=!!s.music_autogain;
renderQueue(s.queue);
$("queueCount").textContent=s.queue&&s.queue.length?`${s.queue.length} waiting`:"";$("clearQueue").disabled=!s.queue||!s.queue.length;
renderRoom(s.room);renderPeers(s.peers,s.peer_discovery_available);window.scRenderScreens&&window.scRenderScreens(s);
const streams=Array.isArray(s.network_activity)?s.network_activity:[],activityRows=$("networkActivityRows");activityRows.replaceChildren();$("networkActivitySummary").textContent=streams.length?`${streams.length} active stream${streams.length===1?"":"s"} on reachable receivers`:"No active streams reported by reachable receivers";if(!streams.length){const li=document.createElement("li");li.textContent="When someone starts casting on this network, it appears here. Unreachable receivers are omitted.";activityRows.append(li)}else for(const item of streams){const li=document.createElement("li"),title=document.createElement("strong"),detail=document.createElement("span");title.textContent=item.title||"Media title unavailable";detail.className="muted";const timing=item.position==null?"":` · ${clock(item.position)}${item.duration==null?"":` / ${clock(item.duration)}`}`;detail.textContent=`${item.receiver||"Unknown receiver"} · ${item.protocol||"Receiver"} · ${item.state||"ACTIVE"}${timing}${item.is_local?" · This SmoothCast":""}`;li.replaceChildren(title,document.createElement("br"),detail);activityRows.append(li)}
document.querySelectorAll("[data-action]").forEach(b=>b.disabled=!!s.busy||!s.active);statusFailures=0;showJoinedRoom();showError("errorDash","");
  return true;
}
async function refresh(){
  clearTimeout(statusTimer);
  if(!csrf||stalePage||document.hidden||busy||statusRequest)return;
  const controller=new AbortController();
  statusRequest=controller;
  const deadline=setTimeout(()=>controller.abort(),5000);
  try{
    const r=await fetch("/api/status",{credentials:"same-origin",cache:"no-store",signal:controller.signal});
    const d=await r.json();
    if(controller.signal.aborted||busy)return;
    if(r.status===401){expireSession();return}
    if(r.status===429){const seconds=Math.max(1,Number(r.headers.get("Retry-After"))||1);rateDelayUntil=Date.now()+seconds*1000;throw Error("Room updates are busy. Retrying shortly…")}
    if(!r.ok)throw Error(d.error||"Connection lost");
    if(applyStatus(d)===false)return;
    roomEvents.start();
  }catch(err){
    if(!busy&&!document.hidden&&controller.signal.reason!=="superseded"){
      statusFailures=Math.min(statusFailures+1,4);
      showError("errorDash",err.name==="AbortError"?"Room update timed out. Retrying…":err.message);
    }
  }finally{
    clearTimeout(deadline);
    statusRequest=null;
    scheduleRefresh();
  }
}
function initials(name){return (name||"?").trim().split(/\s+/).slice(0,2).map(p=>p[0]).join("").toUpperCase()}
const activityLines=new Map();
let lastRoom=null;function renderRoom(room){lastRoom=room;const people=$("people");people.replaceChildren();if(room&&room.participants)for(const person of room.participants){const chip=document.createElement("span");chip.className="person"+(person.online?"":" offline");const avatar=document.createElement("span");avatar.className="avatar";avatar.style.background=person.color;avatar.textContent=initials(person.name);const name=document.createElement("span");name.textContent=person.name+(room.me&&room.me.id===person.id?" (you)":"");chip.append(avatar,name);people.append(chip)}const activity=$("activity");if(room&&room.activity){const filter=$("activityFilter").value,events=[...room.activity].filter(e=>activityMatches(e,filter)).slice(-12);$("activityEmpty").hidden=events.length>0||!room.activity.length;const keep=new Set(events.map(e=>e.seq));for(const [seq,line] of activityLines)if(!keep.has(seq)){line.remove();activityLines.delete(seq)}for(const event of events){let line=activityLines.get(event.seq);if(!line){line=document.createElement("div");line.className="ev";const time=document.createElement("time"),text=document.createElement("span");text.textContent=describe(event);line.append(time,text);activityLines.set(event.seq,line)}const time=line.firstChild;time.textContent=ago(event.at);time.title=new Date(event.at*1000).toLocaleString()}[...events].reverse().forEach((event,index)=>{const line=activityLines.get(event.seq);if(activity.children[index]!==line)activity.insertBefore(line,activity.children[index]||null)})}}
$("activityFilter").addEventListener("change",()=>{if(lastRoom)renderRoom(lastRoom)});
function renderPeers(peers,available){
  const list=$("peers");
  const entries=available&&Array.isArray(peers)?peers:[];
  const focused=document.activeElement;
  if(!entries.length){
    const message=available?"No other SmoothCast hosts found":"Peer discovery is unavailable on this network";
    if(list.firstElementChild?.className==="empty"&&list.firstElementChild.textContent===message)return;
    const empty=document.createElement("li");
    empty.className="empty";
    empty.textContent=message;
    list.replaceChildren(empty);
    return;
  }
  const counts=new Map();
  for(const peer of entries){
    const key=peer.name.toLowerCase();
    counts.set(key,(counts.get(key)||0)+1);
  }
  const rows=new Map(Array.from(list.children,row=>[row.dataset.peerId,row]));
  const ordered=[];
  for(const peer of entries){
    const row=rows.get(peer.id)||document.createElement("li");
    rows.delete(peer.id);
    row.dataset.peerId=peer.id;
    const label=peer.name+(counts.get(peer.name.toLowerCase())>1?" · "+peer.id.slice(0,6):"");
    if(peer.compatible){
      let link=row.firstElementChild;
      if(!link){
        link=document.createElement("a");
        link.target="_blank";
        link.rel="noopener noreferrer";
        row.replaceChildren(link,document.createTextNode(" · video upload and Cast control after PIN"));
      }
      if(link.textContent!==label)link.textContent=label;
      if(link.getAttribute("href")!==peer.url)link.href=peer.url;
    }else{
      const message=label+" · incompatible version";
      if(row.textContent!==message)row.textContent=message;
    }
    ordered.push(row);
  }
  for(const row of rows.values())row.remove();
  ordered.forEach((row,index)=>{
    const current=list.children[index]||null;
    if(row!==current)list.insertBefore(row,current);
  });
  if(focused&&list.contains(focused)&&document.activeElement!==focused){
    focused.focus({preventScroll:true});
  }
}
function activityMatches(event,filter){const d=(event&&event.data)||{},type=event&&event.type;if(!filter||filter==="all")return true;if(filter==="problems")return type==="action"&&(d.outcome==="rejected"||d.outcome==="uncertain");const a=String(d.action||"");if(filter==="queue")return type==="voted"||(type==="action"&&a.startsWith("queue_"));if(filter==="playback")return type==="action"&&!a.startsWith("queue_");if(filter==="people")return ["joined","left","renamed","screen"].includes(type);return false}
function describe(event){const d=event.data||{},name=d.name||"Someone",q=d.title?" \u201c"+d.title+"\u201d":"";switch(event.type){case "joined":return name+(d.reconnected?" reconnected":" joined");case "left":return name+" left";case "renamed":return "You are now "+name;case "voted":return name+(d.voted===false?" removed a vote from":" voted for")+(q||" an item");case "action":{const a=d.action||"";const words={queue_play:"played"+q+" now",queue_remove:"removed"+q,queue_move:"moved"+q,queue_next:"queued"+q+" next",queue_add_key:"added"+q,queue_clear:"cleared Up Next",play_pause:"paused or resumed playback",stop:"stopped playback",seek:"changed the playback position",volume:"changed the volume",mute:"toggled mute",next:"skipped to the next item",previous:"went back to the previous item",music_autogain:"changed music normalisation"};const sentence=name+" "+(words[a]||"used "+(a||"a control").replaceAll("_"," "));const result={accepted:"request accepted; confirmation pending",rejected:"request refused",uncertain:"receiver confirmation unavailable",confirmed:"confirmed"}[d.outcome];return result?sentence+" \u00b7 "+result:sentence}case "screen":return name+" used a browser screen";default:return name+" updated the room"}}
function ago(at){const s=Math.max(0,Date.now()/1000-Number(at));if(!Number.isFinite(s))return "";if(s<45)return "just now";if(s<3600)return Math.max(1,Math.round(s/60))+" min ago";return new Date(at*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}
function showShortcutHelp(){
  const dialog=$("shortcutsHelp"),list=$("shortcutsList");
  if(!list.children.length)for(const entry of SHORTCUTS){
    const item=document.createElement("li"),description=document.createElement("span"),key=document.createElement("kbd");
    description.textContent=entry.description;
    key.textContent=entry.label==="space"?"Space":entry.label==="question"?"?":entry.label;
    item.append(description,key);
    list.append(item);
  }
  if(!dialog.open)dialog.showModal();
}
$("shortcutsClose").addEventListener("click",()=>$("shortcutsHelp").close());

function shortcutCommand(action,state,seek,volume){
  if(!state||state.busy||!state.active)return null;
  if(action==="seek_back"||action==="seek_forward"){
    if(!state.can_seek||!Number.isFinite(state.duration)||state.duration<=0)return null;
    const delta=action==="seek_back"?-10:10;
    return {action:"seek",value:Math.max(0,Math.min(state.duration,seek+delta))};
  }
  if(action==="volume_up"||action==="volume_down"){
    if(state.volume==null||!Number.isFinite(volume))return null;
    return {action:"volume",value:Math.max(0,Math.min(100,volume+(action==="volume_up"?5:-5)))};
  }
  if(action==="mute"&&state.volume==null)return null;
  if(["play_pause","next","previous","mute"].includes(action))return {action};
  return null;
}

window.addEventListener("keydown",event=>{
  if(event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.altKey)return;
  if(event.target instanceof Element&&event.target.closest("input,textarea,select,button,[contenteditable],[role=textbox],[role=slider]"))return;
  if($("shortcutsHelp").open)return;
  const key=event.key.length===1?event.key.toLowerCase():event.key;
  const shortcut=shortcutMap.get(key);
  if(!shortcut)return;
  event.preventDefault();
  if(shortcut.action==="help"){showShortcutHelp();return;}
  const command=shortcutCommand(shortcut.action,shortcutState,Number($("seek").value),Number($("volume").value));
  if(!command||stalePage||!csrf||busy){
    showError($("dashboard").hidden?"error":"errorDash","This shortcut is unavailable until the room and receiver are ready.");
    return;
  }
  if(["play_pause","next","previous"].includes(command.action)){
    const button=document.querySelector('[data-action="'+command.action+'"]');
    if(!button||button.disabled){
      showError("errorDash","This control is not available right now.");
      return;
    }
  }
  act(command.action,command.value);
});

async function act(action,value,extra={}){
  if(!csrf||stalePage){showError("errorDash","Reconnect to control this room");return}
  if(busy){
    const key=action+":"+(extra.id||"");
    if(!pendingControls.has(key)&&pendingControls.size>=16){
      showError("errorDash","Too many controls are waiting; try again shortly");
      return;
    }
    pendingControls.delete(key);
    pendingControls.set(key,{action,value,extra});
    showError("errorDash","Control waiting; your latest change will be sent");
    return;
  }
  if(Date.now()<rateDelayUntil){
    showError("errorDash","Too many controls at once. Try again shortly.");
    return;
  }
  busy=true;
  statusRequest?.abort("superseded");
  try{
    const body={action,...extra};
    if(["queue_remove","queue_move","queue_next","queue_clear"].includes(action)){
      body.queue_revision=queueRevision;
      body.queue_command_id="q"+Date.now().toString(36)+"-"+(++queueCommandSeq).toString(36);
    }
    if(value!==undefined)body.value=value;
    const result=await post("/api/action",body);
    showError("errorDash",result.message||"Command accepted");
    if(action.startsWith("queue_"))$("queueFeedback").textContent=result.message||"Queue change accepted by the host; awaiting room refresh.";
  }catch(err){showError("errorDash",err.message);if(action.startsWith("queue_"))$("queueFeedback").textContent="Queue action was not applied: "+err.message;}
  finally{
    busy=false;
    if(pendingControls.size&&csrf&&!stalePage){
      const first=pendingControls.keys().next().value;
      const next=pendingControls.get(first);
      pendingControls.delete(first);
      if(next)void act(next.action,next.value,next.extra);
    }else refresh();
  }
}
function confirmClearQueue(){
  const count=queueState.length;
  if(!count)return false;
  return window.confirm(`Clear ${count} waiting item${count===1?"":"s"} from Up Next for everyone? This does not stop what is currently playing.`);
}
$("clearQueue").addEventListener("click",()=>{
  if(confirmClearQueue())void act("queue_clear");
});
document.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",()=>act(b.dataset.action)));
for(const id of ["seek","volume"]){
  const control=$(id);
  control.addEventListener("pointerdown",()=>editingControls.add(id));
  control.addEventListener("input",()=>editingControls.add(id));
  control.addEventListener("pointercancel",()=>editingControls.delete(id));
  control.addEventListener("blur",()=>editingControls.delete(id));
}
// Preview source-film time while dragging, without ever issuing a seek.
// A cancelled pointer gesture must not submit a delayed change event.
let seekCanceled=false;
function cancelSeekPreview(){
  seekCanceled=true;
  editingControls.delete("seek");
  const pos=playhead
    ?projectPosition(playhead.s,playhead.age,performance.now()-playhead.at)
    :Math.max(0,Number($("progress").value)||0);
  $("seek").value=pos;
  $("elapsed").textContent=clock(pos);
}
function commitSeekPreview(){
  const value=Number($("seek").value);
  editingControls.delete("seek");
  if(seekCanceled){cancelSeekPreview();seekCanceled=false;return}
  if(!Number.isFinite(value)||value<0)return;
  $("elapsed").textContent=clock(value);
  void act("seek",value); // zero is valid; exactly one mutation on commit
}
$("seek").addEventListener("pointerdown",()=>{seekCanceled=false});
$("seek").addEventListener("input",()=>{
  if(!seekCanceled)$("elapsed").textContent=clock(Number($("seek").value));
});
$("seek").addEventListener("pointercancel",cancelSeekPreview);
$("seek").addEventListener("keydown",event=>{
  if(event.key==="Escape"){event.preventDefault();cancelSeekPreview()}
});
$("seek").addEventListener("change",commitSeekPreview);
let volumeTimer=null,lastVolumeSent=0,volumePending=null;
function flushVolume(){
  volumeTimer=null;
  if(volumePending===null)return;
  const value=volumePending;
  volumePending=null;
  lastVolumeSent=Date.now();
  void act("volume",value);
}
function queueVolume(value){
  volumePending=value;
  if(volumeTimer===null){
    volumeTimer=setTimeout(flushVolume,Math.max(0,150-(Date.now()-lastVolumeSent)));
  }
}
$("volume").addEventListener("input",()=>{
  const value=Number($("volume").value);
  $("volumeText").textContent=value+"%";
  queueVolume(value);
});
$("volume").addEventListener("change",()=>{
  editingControls.delete("volume");
  queueVolume(Number($("volume").value));
});
$("nameForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await post("/api/profile",{name:$("displayName").value});$("displayName").value=d.participant.name;showJoinedName(d.participant.name);showError("errorDash","Display name updated");refresh()}catch(err){showError("errorDash",err.message)}});
$("musicAutogain").addEventListener("change",()=>act("music_autogain",$("musicAutogain").checked));
// A bounded, in-page diagnostic trail. Never log cookies, CSRF, upload IDs
// or paths. Host ACKs and browser send progress are deliberately separate.
let transferEvents=[];
function monitorText(id,value){const node=$(id);if(node)node.textContent=value;}
function transferEvent(message){
  const stamp=new Date().toLocaleTimeString();
  transferEvents.push(stamp+"  "+message);
  if(transferEvents.length>24)transferEvents.shift();
  monitorText("transferEvents",transferEvents.slice().reverse().join("\n"));
}
function resetTransferMonitor(){
  transferEvents=[];
  monitorText("transferFileName","No active file");
  monitorText("transferOperation","Idle");
  monitorText("transferElapsed","—");
  monitorText("transferInFlight","—");
  monitorText("transferResponse","—");
  monitorText("transferDelivery","Not submitted");
  monitorText("transferAck","—");
  monitorText("transferRoomState","Awaiting room status");
  monitorText("transferEvents","Choose a file to begin. Events appear here as they happen.");
}
function transferOperationName(method,path){
  if(method==="PUT")return "Sending chunk / waiting for disk";
  if(method==="GET")return "Checking saved host offset";
  if(method==="DELETE")return "Cancelling upload";
  return path.endsWith("/complete")?"Finalising media and submitting action":"Reserving host storage";
}
function uploadTransport(path,options){
  // XHR exposes sender-side progress. Keep Fetch for headless/older clients.
  if(options.method!=="PUT"||typeof XMLHttpRequest==="undefined")return fetch(path,options);
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    xhr.open(options.method,path,true);
    for(const [name,value] of Object.entries(options.headers))xhr.setRequestHeader(name,value);
    const abort=()=>xhr.abort();
    const finish=(callback,value)=>{
      options.signal.removeEventListener("abort",abort);
      callback(value);
    };
    xhr.upload.onprogress=event=>{
      const total=event.lengthComputable?event.total:options.body.size;
      monitorText("transferInFlight",fileUnits(event.loaded)+" of "+fileUnits(total)+" (not yet confirmed)");
      if(event.lengthComputable&&event.loaded===event.total)
        monitorText("transferOperation","Chunk sent — waiting for host storage");
    };
    xhr.onload=()=>finish(resolve,{
      status:xhr.status,ok:xhr.status>=200&&xhr.status<300,
      headers:{get:name=>xhr.getResponseHeader(name)},
      json:async()=>JSON.parse(xhr.responseText),
    });
    xhr.onerror=()=>finish(reject,Error("Connection to SmoothCast interrupted"));
    xhr.onabort=()=>finish(reject,Error("Upload request interrupted"));
    if(options.signal.aborted){reject(Error("Upload request interrupted"));return;}
    options.signal.addEventListener("abort",abort,{once:true});
    xhr.send(options.body);
  });
}
async function uploadRequest(method,path,body,headers={}){
  if(stalePage)throw Error("Reload required");
  if(!csrf)throw Object.assign(Error("Room access expired"),{status:401});
  const controller=new AbortController();activeUploadController=controller;
  let timedOut=false;
  const deadline=setTimeout(()=>{timedOut=true;controller.abort();},60000);
  const operation=transferOperationName(method,path),started=Date.now();
  monitorText("transferOperation",operation);
  monitorText("transferInFlight",method==="PUT"?"Sending…":"—");
  monitorText("transferElapsed","0 sec");
  if(method!=="PUT")transferEvent(operation);
  const tick=setInterval(()=>monitorText("transferElapsed",Math.floor((Date.now()-started)/1000)+" sec"),500);
  try{
    const response=await uploadTransport(path,{method,credentials:"same-origin",cache:"no-store",headers:{"X-CSRF-Token":csrf,...clientHeaders,...headers},body,signal:controller.signal});
    monitorText("transferResponse","HTTP "+response.status);
    let data;
    try{data=await response.json()}catch(_){
      throw Object.assign(Error("The SmoothCast host returned an unreadable upload response."),{status:response.status, retryAfter:1});
    }
    if(data?.code==="client_reload_required")showUpdateNotice();
    if(!response.ok||!data||data.ok===false)throw Object.assign(Error(response.status===429?"Upload requests are busy. Retrying shortly…":data?.error||"Upload request failed"),{status:response.status,code:data?.code,retryAfter:Math.max(1,Number(response.headers.get("Retry-After"))||1)});
    if(validUploadProgress(data.received,data.size))monitorText("transferAck",fileUnits(data.received));
    if(method==="PUT")monitorText("transferInFlight","Chunk acknowledged by host");
    else transferEvent(operation+" · HTTP "+response.status);
    monitorText("transferOperation","Host response received");
    return data;
  }catch(error){
    if(timedOut)error=Object.assign(Error("Host did not respond within 60 seconds"),{status:408});
    const message=error?.message||"Unknown upload failure";
    monitorText("transferOperation","Request interrupted");
    monitorText("transferResponse",(error?.status?"HTTP "+error.status+": ":"")+message);
    transferEvent(operation+" · "+(error?.status?"HTTP "+error.status+" · ":"")+message);
    throw error;
  }finally{
    clearTimeout(deadline);clearInterval(tick);
    monitorText("transferElapsed",Math.floor((Date.now()-started)/1000)+" sec");
    if(activeUploadController===controller)activeUploadController=null;
  }
}
async function sendChunk(path,file,offset,end){
  const body=file.slice(offset,end),headers={"Content-Type":"application/octet-stream","Content-Range":`bytes ${offset}-${end-1}/${file.size}`};
  for(let attempt=0;;attempt++){
    if(cancelUpload)throw Error("Upload cancelled");
    if(pauseRequested)throw Error("Transfer paused");
    try{return await uploadRequest("PUT",path,body,headers)}catch(error){
      if(pauseRequested)throw Error("Transfer paused");
      if(error.code==="upload.disk_full"||(error.status&&error.status<500&&![408,409,429].includes(error.status)))throw error;
      if(attempt===4||cancelUpload||!csrf)throw error;
      if(typeof transferEvent==="function")transferEvent("Retry "+(attempt+1)+" of 4 — checking the saved host offset");
      showError("uploadStatus","Connection interrupted. Retrying…");
      await new Promise(resolve=>setTimeout(resolve,Math.max(250*2**attempt,(error.status===429?error.retryAfter:0)*1000)));
      if(cancelUpload)throw Error("Upload cancelled");
      try{
        const state=await uploadRequest("GET",path);
        if(state.received===end)return state;
        if(state.received!==offset){
          throw Object.assign(Error("Upload position changed. Choose the file again to resume safely."),{status:409,offsetMismatch:true});
        }
      }catch(statusError){
        if(statusError.offsetMismatch||statusError.status===404||statusError.status===401||statusError.status===403)throw statusError;
      }
    }
  }
}
// Keep only upload metadata. The server still owns the offset and checks the cookie.
async function uploadStorage(mode, operation){
  try{
    const db=await new Promise((resolve,reject)=>{
      const request=indexedDB.open("smoothcast-uploads",1);
      request.onupgradeneeded=()=>request.result.createObjectStore("pending",{keyPath:"id"});
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>reject(request.error);
    });
    try{
      return await new Promise((resolve,reject)=>{
        const transaction=db.transaction("pending",mode);
        const request=operation(transaction.objectStore("pending"));
        transaction.oncomplete=()=>resolve(request.result);
        transaction.onabort=()=>reject(transaction.error);
      });
    }finally{db.close()}
  }catch(_){return undefined}
}
const UPLOAD_FINGERPRINT_BYTES=64*1024;
async function firstChunkHash(file,chunkSize,version=3){
  // Recognition only, NOT a content digest. v3 samples first, middle and last
  // blocks to reject most accidental file substitutions without an 8 MiB hash
  // on the browser main thread; bytes read are bounded to 192 KiB.
  if(version===3){
    const width=Math.min(file.size,UPLOAD_FINGERPRINT_BYTES);
    const offsets=[0,Math.floor((file.size-width)/2),file.size-width];
    let a=0x811c9dc5,b=0x9e3779b9;
    for(const offset of [...new Set(offsets)]){
      // Include sample position so moving blocks cannot alias each other.
      for(let n=offset;n>0;n=Math.floor(n/256)){
        const byte=n%256;
        a=Math.imul(a^byte,0x01000193);
        b=Math.imul(b^byte,0x85ebca6b);
      }
      const bytes=new Uint8Array(await file.slice(offset,offset+width).arrayBuffer());
      for(const byte of bytes){
        a=Math.imul(a^byte,0x01000193);
        b=Math.imul(b^byte,0x85ebca6b);
      }
      await new Promise(resolve=>setTimeout(resolve,0));
    }
    return [a,b].map(value=>(value>>>0).toString(16).padStart(8,"0")).join("");
  }
  if(version===2){
    // Existing v2 IndexedDB records used only the first 64 KiB.
    const bytes=new Uint8Array(await file.slice(0,Math.min(file.size,UPLOAD_FINGERPRINT_BYTES)).arrayBuffer());
    let a=0x811c9dc5,b=0x9e3779b9;
    for(const byte of bytes){
      a=Math.imul(a^byte,0x01000193);
      b=Math.imul(b^byte,0x85ebca6b);
    }
    return [a,b].map(value=>(value>>>0).toString(16).padStart(8,"0")).join("");
  }
  // Legacy v1 FNV-1a 64 over the full negotiated chunk. Yield for UI health.
  // Corrupt/stale IndexedDB records must never trigger an unbounded legacy hash.
  const count=Math.min(file.size,chunkSize,8*1024*1024);
  let hash=0xcbf29ce484222325n;
  for(let offset=0;offset<count;offset+=16*1024){
    const bytes=new Uint8Array(await file.slice(offset,Math.min(count,offset+16*1024)).arrayBuffer());
    for(const byte of bytes)hash=BigInt.asUintN(64,(hash^BigInt(byte))*0x100000001b3n);
    await new Promise(resolve=>setTimeout(resolve,0));
  }
  return hash.toString(16).padStart(16,"0");
}
async function matchesPendingFile(file,upload){
  return file.name===upload.name&&file.size===upload.size&&file.lastModified===upload.lastModified
    &&await firstChunkHash(file,upload.chunkSize,upload.hashVersion||1)===upload.hash;
}
// Real host-ingest stages. Mesh forwarding is not claimed until #569 supplies a route.
const TRANSFER_STAGES=["choose","prepare","transfer","verify","deliver"];
let pauseRequested=false;
let transferSample=null;
function fileUnits(bytes){
  if(!Number.isFinite(bytes)||bytes<0)return "—";
  if(bytes<1024)return Math.floor(bytes)+" B";
  const units=["KiB","MiB","GiB","TiB"];
  let size=bytes,index=-1;
  do{size/=1024;index++}while(size>=1024&&index<units.length-1);
  return size.toFixed(size<10?1:0)+" "+units[index];
}
function transferView(phase,received=0,total=0,note=""){
  const stage=TRANSFER_STAGES.includes(phase)?phase:"choose";
  const index=TRANSFER_STAGES.indexOf(stage);
  for(const item of ($("transferSteps")?.children||[])){
    const offset=TRANSFER_STAGES.indexOf(item.dataset.stage);
    item.classList.toggle("done",offset<index);
    item.classList.toggle("active",offset===index);
    if(offset===index)item.setAttribute("aria-current","step");
    else item.removeAttribute("aria-current");
  }
  const valid=Number.isSafeInteger(total)&&total>0&&Number.isSafeInteger(received)&&received>=0&&received<=total;
  const pct=valid?Math.floor(received*100/total):0;
  $("uploadProgress").max=valid?total:1;
  $("uploadProgress").value=valid?received:0;
  $("transferPercent").textContent=valid?pct+"%":"—";
  $("transferBytes").textContent=valid?fileUnits(received)+" of "+fileUnits(total):"No file selected";
  $("transferDestination").textContent=$("uploadQueue").checked?"Up Next":"Room receiver (pending)";
  const names={choose:"Choose media",prepare:"Preparing private transfer",transfer:"Sending to SmoothCast host",verify:"Checking received media",deliver:"Submitting to shared room"};
  $("transferStage").textContent=names[stage]+(note?" · "+note:"");
  if(stage==="transfer"&&valid){
    const now=performance.now();
    if(!transferSample||received<transferSample.received||transferSample.total!==total)
      transferSample={at:now,received,total,rate:0};
    const elapsed=(now-transferSample.at)/1000,delta=received-transferSample.received;
    if(elapsed>=0.5&&delta>0){
      const instant=delta/elapsed;
      transferSample.rate=transferSample.rate?transferSample.rate*0.65+instant*0.35:instant;
      transferSample.at=now;transferSample.received=received;
    }
    const rate=transferSample.rate;
    $("transferRate").textContent=rate>0?fileUnits(rate)+"/s":"Measuring speed…";
    const seconds=rate>0?(total-received)/rate:Infinity;
    $("transferEta").textContent=received===total?"Bytes received":Number.isFinite(seconds)&&seconds<86400
      ?"About "+(seconds<60?Math.max(1,Math.ceil(seconds))+" sec":Math.ceil(seconds/60)+" min")+" remaining":"ETA calculating…";
  }else{
    if(stage==="choose"||stage==="prepare")transferSample=null;
    $("transferRate").textContent="—";
    $("transferEta").textContent=stage==="verify"?"Checking…":stage==="deliver"?"Awaiting result":"—";
  }
}
const MAX_UPLOAD_CHUNK_BYTES=8*1024*1024;
function validUploadChunkSize(size){
  return Number.isSafeInteger(size)&&size>0&&size<=MAX_UPLOAD_CHUNK_BYTES;
}
function validUploadProgress(value,size){
  return Number.isSafeInteger(size)&&size>0&&size<=2**40
    &&Number.isSafeInteger(value)&&value>=0&&value<=size;
}
function validSavedUpload(record){
  return record&&typeof record.id==="string"&&/^[A-Za-z0-9_-]{32}$/.test(record.id)
    &&typeof record.name==="string"&&record.name.length>0
    &&validUploadChunkSize(record.chunkSize)
    &&validUploadProgress(record.received,record.size);
}
async function clearPendingUpload(){
  const id=pendingUpload?.id;
  pendingUpload=null;
  if(id)await uploadStorage("readwrite",store=>store.delete(id));
}
async function restoreUpload(){
  if(uploading||!csrf)return;
  const session=csrf;
  uploading=true;
  updateUploadControls();
  try{
    const records=await uploadStorage("readonly",store=>store.getAll());
    // IndexedDB is client-controlled and may contain stale/malformed entries.
    // Validate *before* sorting; a null entry must never crash room restoration.
    const candidates=Array.isArray(records)?records.filter(validSavedUpload):[];
    const started=record=>Number.isSafeInteger(record.started)&&record.started>=0?record.started:0;
    candidates.sort((a,b)=>started(b)-started(a));
    for(const record of candidates){
      if(csrf!==session)return;
      try{
        const state=await uploadRequest("GET","/api/uploads/"+record.id);
        if(csrf!==session)return;
        if(!validUploadProgress(state.received,record.size)){
          showError("uploadStatus","Saved upload progress is invalid. Reload to check it again.");
          return;
        }
        pendingUpload={...record,received:state.received};
        monitorText("transferFileName",record.name);
        monitorText("transferDelivery",record.queueOnly?"Up Next requested":"Play now requested");
        transferEvent("Interrupted upload found; choose the original file to resume");
        $("uploadQueue").checked=record.queueOnly;
        transferView("transfer",state.received,record.size,"Resumable");
        showError("uploadStatus",`Choose ${record.name} again to resume from ${state.received} bytes.`);
        return;
      }catch(error){
        if(error.status===404){await uploadStorage("readwrite",store=>store.delete(record.id));continue}
        // Avoid exposing stored filenames until the current cookie has been checked.
        if(csrf===session&&!stalePage)showError("uploadStatus","Could not check for interrupted uploads. Reload to try again.");
        return;
      }
    }
  }finally{finishUpload()}
}
function updateUploadControls(){
  const file=batchFiles&&batchFiles[batchIndex]||$("videoFile").files[0],audio=file&&/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name);
  if(audio)$("uploadQueue").checked=true;
  const resumeLabel=pendingUpload&&`Resume ${pendingUpload.name} (${Math.floor(pendingUpload.received*100/pendingUpload.size)}%)`;
  $("uploadButton").disabled=uploading||!file;
  $("uploadButton").textContent=resumeLabel||(batchFiles?"Continue upload batch":($("uploadQueue").checked?"Upload and add":"Upload and cast"));
  $("videoFile").disabled=uploading||!!batchFiles;
  $("videoFile").multiple=!pendingUpload||!!batchFiles;
  $("uploadQueue").disabled=uploading||!!batchFiles||!!pendingUpload||!!audio;
  const destination=$("transferDestination");
  if(destination&&!uploading&&!pendingUpload&&!batchFiles)destination.textContent=$("uploadQueue").checked||audio?"Up Next":"Room receiver (pending)";
  const pause=$("pauseUpload");if(pause){pause.hidden=!uploading||!pendingUpload;pause.disabled=cancelUpload;}
  $("cancelUpload").hidden=!pendingUpload&&!batchFiles;
  $("cancelUpload").disabled=cancelUpload;
}
function resetUploadBatch(){
  resetTransferMonitor();
  pendingUpload=null;
  batchFiles=null;
  batchIndex=0;
  $("videoFile").value="";
  transferView("choose");
  showError("uploadStatus","");
  updateUploadControls();
}
function finishUpload(){
  uploading=false;
  cancelUpload=false;
  if(csrf)updateUploadControls();
  else{
    resetUploadBatch();
    loginButton.disabled=false;
  }
}
async function discardUpload(){
  if(pendingUpload){
    try{await uploadRequest("DELETE","/api/uploads/"+pendingUpload.id)}
    catch(error){if(error.status!==404)throw error}
    await clearPendingUpload();
  }
  batchFiles=null;batchIndex=0;
  transferView("choose");
  monitorText("transferOperation","Cancelled");
  monitorText("transferDelivery","Not submitted");
  transferEvent("Upload cancelled");
  showError("uploadStatus","Upload cancelled");
}
$("uploadButton").addEventListener("click",async()=>{
  if(uploading)return;
  const selected=Array.from($("videoFile").files);
  if(!batchFiles&&!selected.length)return;
  const session=csrf,json={"Content-Type":"application/json"};
  uploading=true;
  cancelUpload=false;
  pauseRequested=false;
  updateUploadControls();
  try{
    if(!batchFiles){
      if(pendingUpload&&(selected.length!==1||!await matchesPendingFile(selected[0],pendingUpload))){
        $("videoFile").value="";
        showError("uploadStatus",`This file does not match the original. Choose ${pendingUpload.name} to resume.`);
        return;
      }
      if(cancelUpload){await discardUpload();return}
      if(!session||csrf!==session)return;
      batchFiles=selected;
      batchIndex=0;
      batchAdded=0;
      batchTotal=selected.length;
      batchQueueOnly=pendingUpload?.queueOnly??$("uploadQueue").checked;
    }
    while(batchIndex<batchFiles.length&&!cancelUpload){
      const file=batchFiles[batchIndex],audio=/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name);
      const queueOnly=audio||batchQueueOnly;
      monitorText("transferFileName",(batchIndex+1)+"/"+batchFiles.length+" · "+file.name);
      monitorText("transferDelivery",queueOnly?"Up Next requested":"Play now requested");
      monitorText("transferAck",pendingUpload?fileUnits(pendingUpload.received):"0 B");
      transferEvent((pendingUpload?"Resuming file ":"Preparing file ")+(batchIndex+1)+" of "+batchFiles.length+" · "+fileUnits(file.size));
      let state;
      if(pendingUpload){
        transferView("prepare",pendingUpload.received,file.size,"Resuming");
        showError("uploadStatus",`Checking ${file.name}…`);
        state=await uploadRequest("GET","/api/uploads/"+pendingUpload.id);
      }else{
        transferView("prepare",0,file.size,"File "+(batchIndex+1)+" of "+batchFiles.length);
        showError("uploadStatus",`Preparing ${batchIndex+1}/${batchFiles.length}: ${file.name}…`);
        state=await uploadRequest("POST","/api/uploads",JSON.stringify({name:file.name,size:file.size,queue:queueOnly}),json);
        const {id,chunk_size:chunkSize}=state;
        if(typeof id!=="string"||!/^[A-Za-z0-9_-]{32}$/.test(id)||!validUploadChunkSize(chunkSize))
          throw Error("Upload setup returned invalid transfer parameters. Reload and retry.");
        pendingUpload={id,chunkSize,name:file.name,size:file.size,lastModified:file.lastModified,queueOnly,started:Date.now(),received:0};
        monitorText("transferOperation","Reading local file fingerprint");
        const record={...pendingUpload,hashVersion:3,hash:await firstChunkHash(file,chunkSize)};
        await uploadStorage("readwrite",store=>store.put(record));
        transferEvent("Host reserved storage; chunk size "+fileUnits(chunkSize));
      }
      const {id,chunkSize}=pendingUpload,path="/api/uploads/"+id;
      if(!validUploadChunkSize(chunkSize)||!validUploadProgress(state.received,file.size))
        throw Error("Upload progress is invalid. Reload and choose the file again.");
      casting=!!state.ready_to_cast;
      if(casting)monitorText("transferDelivery","Early playback requested — not confirmed");
      transferView("transfer",state.received,file.size);
      pendingUpload.received=state.received;
      let milestone=Math.floor(state.received*4/file.size);
      while(state.received<file.size&&!cancelUpload){
        const end=Math.min(state.received+chunkSize,file.size);
        state=await sendChunk(path,file,state.received,end);
        if(!validUploadProgress(state.received,file.size)||state.received!==end)
          throw Error("Host returned an unexpected upload offset. Resume to check the saved position.");
        pendingUpload.received=state.received;
        transferView("transfer",state.received,file.size);
        if(state.ready_to_cast&&!casting){
          if(state.early_cast_accepted===false){
            monitorText("transferDelivery","Early cast declined — retry after upload");
            transferEvent("Early playback declined; continuing the upload");
          }else{
            casting=true;
            monitorText("transferDelivery","Early playback requested — not confirmed");
            transferEvent("Early playback request sent; continuing transfer");
          }
        }
        const reached=Math.floor(state.received*4/file.size);
        if(reached>milestone){
          milestone=reached;
          transferEvent("Host acknowledged "+Math.floor(state.received*100/file.size)+"% · "+fileUnits(state.received));
        }
        const percent=Math.floor(state.received*100/file.size);
        showError("uploadStatus",(casting?"Early playback requested; ":"")+
          `${batchIndex+1}/${batchFiles.length} · ${file.name}: ${percent}% received by host`);
      }
      if(cancelUpload){await discardUpload();break}
      $("cancelUpload").disabled=true;
      transferView("verify",file.size,file.size);
      $("pauseUpload").hidden=true;
      await uploadRequest("POST",path+"/complete",JSON.stringify({queue:queueOnly}),json);
      monitorText("transferOperation","Transfer complete");
      monitorText("transferDelivery",queueOnly?"Added to Up Next":"Playback requested — receiver not confirmed");
      monitorText("transferAck",fileUnits(file.size));
      transferEvent(queueOnly?"Host accepted queue addition":"Host accepted playback request; receiver confirmation is separate");
      transferView("deliver",file.size,file.size,queueOnly?"Queue request accepted":"Playback request submitted");
      for(const step of $("transferSteps").children){step.classList.add("done");step.classList.remove("active");step.removeAttribute("aria-current");}
      $("transferStage").textContent=queueOnly?"Added to shared Up Next":"Playback requested — awaiting receiver";
      $("transferEta").textContent="Complete";
      await clearPendingUpload();
      batchIndex++;
      batchAdded++;
      showError("uploadStatus",queueOnly?"Added to shared Up Next.":"Playback requested; receiver confirmation is separate.");
    }
    if(batchFiles&&batchIndex>=batchFiles.length){
      const count=batchAdded,total=batchTotal;
      batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;
      showError("uploadStatus",`${count} of ${total} files added`);
    }
  }catch(error){
    if(!pauseRequested&&!cancelUpload){
      monitorText("transferOperation","Upload needs attention");
      transferEvent("Transfer paused by error: "+(error?.message||"Unknown upload failure"));
    }
    if(error.status===404){
      await clearPendingUpload();
      showError("uploadStatus",error.message+" Select the upload button to start this file again.");
    }else if(error.status===413||error.status===422){
      await clearPendingUpload();
      batchIndex++;
      if(batchIndex>=batchFiles.length){
        batchFiles=null;batchIndex=0;
        showError("uploadStatus",`${error.message} No files remain in this batch.`);
      }else showError("uploadStatus",`${error.message} Skipped this file; select Continue upload batch to add the rest.`);
    }else if(pauseRequested){
      monitorText("transferOperation","Paused");
      transferEvent("Paused; resume from the last host-confirmed offset");
      if(pendingUpload)transferView("transfer",pendingUpload.received,pendingUpload.size,"Paused — Resume available");
      showError("uploadStatus","Paused safely. Select Resume to continue; the host decides the saved offset.");
    }else if(cancelUpload){
      try{await discardUpload()}catch(cancelError){showError("uploadStatus",cancelError.message)}
    }else {if(pendingUpload)transferView("transfer",pendingUpload.received,pendingUpload.size,"Paused — resume available");
      showError("uploadStatus",pendingUpload?error.message+" Select Resume to retry.":error.message);}
  }
  finally{finishUpload()}
});
$("pauseUpload").addEventListener("click",()=>{
  if(!uploading||!pendingUpload||cancelUpload)return;
  // Abort only the current HTTP chunk; the durable server offset remains
  // authoritative, and Resume performs a fresh status GET before sending.
  pauseRequested=true;
  activeUploadController?.abort();
  $("pauseUpload").disabled=true;
  showError("uploadStatus","Transfer paused. Select Resume to continue from the saved position.");
});
const uploadPanel=$("uploadCard");
uploadPanel.addEventListener("dragover",event=>{
  if(uploading||!event.dataTransfer?.types?.includes("Files"))return;
  event.preventDefault();event.dataTransfer.dropEffect="copy";
  uploadPanel.classList.add("drop-active");
});
uploadPanel.addEventListener("dragleave",event=>{
  if(!uploadPanel.contains(event.relatedTarget))uploadPanel.classList.remove("drop-active");
});
uploadPanel.addEventListener("drop",event=>{
  uploadPanel.classList.remove("drop-active");
  if(uploading||!event.dataTransfer?.files?.length)return;
  event.preventDefault();
  try{$("videoFile").files=event.dataTransfer.files;updateUploadControls();}
  catch(_){showError("uploadStatus","This browser cannot accept dropped files. Use Choose files instead.");}
});
$("uploadQueue").addEventListener("change",updateUploadControls);
$("videoFile").addEventListener("change",()=>{updateUploadControls();const file=$("videoFile").files[0];if(file)transferView("choose",0,file.size,($("videoFile").files.length>1?$("videoFile").files.length+" files":"Ready"));});
$("cancelUpload").addEventListener("click",async()=>{
  cancelUpload=true;if(activeUploadController)activeUploadController.abort();$("cancelUpload").disabled=true;showError("uploadStatus","Cancelling upload…");if(uploading)return;
  uploading=true;updateUploadControls();try{await discardUpload()}catch(error){showError("uploadStatus",error.message)}
  finally{finishUpload()}
});
if(typeof requestAnimationFrame==="function")requestAnimationFrame(playheadFrame);
document.addEventListener("visibilitychange",()=>{
  void syncRemoteWakeLock();
  if(document.hidden){clearTimeout(statusTimer);statusRequest?.abort("superseded");roomEvents.stop();return}
  statusFailures=0;
  refresh();
});
window.addEventListener("online",()=>{statusFailures=0;refresh()});

const MEDIA={audio:null,bound:false};
function lockControlsOn(){try{return localStorage.getItem("sc_lockscreen")!=="0"}catch(_){return true}}
function mediaSupported(){return typeof navigator!=="undefined"&&"mediaSession" in navigator&&typeof MediaMetadata==="function"}
function bindMediaSession(){
  if(MEDIA.bound)return;MEDIA.bound=true;
  const ms=navigator.mediaSession,state=()=>shortcutState||{};
  const set=(name,fn)=>{try{ms.setActionHandler(name,fn)}catch(_){}};
  set("play",()=>{if(state().state!=="PLAYING")act("play_pause")});
  set("pause",()=>{if(state().state==="PLAYING")act("play_pause")});
  set("nexttrack",()=>act("next"));
  set("previoustrack",()=>act("previous"));
  set("seekto",d=>{if(d&&Number.isFinite(d.seekTime))act("seek",Math.max(0,d.seekTime))});
  set("seekbackward",d=>act("seek",Math.max(0,(Number(state().position)||0)-((d&&d.seekOffset)||10))));
  set("seekforward",d=>act("seek",(Number(state().position)||0)+((d&&d.seekOffset)||10)));
}
function mediaAudio(){
  if(!MEDIA.audio){const a=new Audio("/silence.wav");a.loop=true;a.volume=0.0001;a.setAttribute("aria-hidden","true");MEDIA.audio=a}
  return MEDIA.audio;
}
function syncMediaSession(s){
  if(!mediaSupported()||!lockControlsOn()||!s)return;
  const ms=navigator.mediaSession,playing=s.state==="PLAYING";
  const active=playing||s.state==="PAUSED"||s.state==="BUFFERING";
  if(!s.title||!active){
    ms.playbackState="none";if(MEDIA.audio)MEDIA.audio.pause();return;
  }
  bindMediaSession();
  const a=mediaAudio();
  if(a.paused){const p=a.play();if(p&&p.catch)p.catch(()=>{})}
  try{ms.metadata=new MediaMetadata({title:String(s.title),artist:String(s.artist||""),album:s.receiver?"SmoothCast - "+s.receiver:"SmoothCast"})}catch(_){}
  ms.playbackState=playing?"playing":"paused";
  const duration=Number(s.duration)||0,position=projectPosition(s,s.snapshot_age_ms,0);
  const rate=typeof s.rate==="number"&&Number.isFinite(s.rate)&&s.rate>=0.05&&s.rate<=4?s.rate:1;
  if(duration>0&&Number.isFinite(duration)){try{ms.setPositionState({duration,position:Math.min(Math.max(0,position),duration),playbackRate:rate})}catch(_){}}
}
(()=>{
  const box=$("lockControls");if(!box)return;
  box.checked=lockControlsOn();
  box.addEventListener("change",()=>{
    try{localStorage.setItem("sc_lockscreen",box.checked?"1":"0")}catch(_){}
    if(!box.checked){if(MEDIA.audio)MEDIA.audio.pause();if(mediaSupported())navigator.mediaSession.playbackState="none"}
    else syncMediaSession(shortcutState);
  });
})();

(()=>{
  const input=$("findInput"),out=$("findResults"),status=$("findStatus");
  if(!input||!out||!status)return;
  let timer=null,source=null,controller=null;
  const clock=s=>{s=Math.round(Number(s)||0);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return(h?h+":"+String(m).padStart(2,"0"):m)+":"+String(s%60).padStart(2,"0")};
  const LABELS={films:"Films",shows:"Shows",artists:"Artists",albums:"Albums",songs:"Songs",other:"Other"};
  function where(copies){
    const list=copies||[];if(!list.length)return"";
    const online=list.filter(c=>c.online),names=c=>c.origin==="local"?"This computer":(c.origin_name||"Another computer");
    if(!online.length)return names(list[0])+" is offline"+(list[0].last_seen?" - last seen "+new Date(list[0].last_seen*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"");
    return"On "+online.map(names).join(" - also on ");
  }
  function item(it,type){
    const li=document.createElement("li");li.className="queue-item";
    const text=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("div");
    title.textContent=it.title||it.name||"Untitled";meta.className="muted";
    if(type==="artists"||type==="albums"){
      meta.textContent=(it.artist?it.artist+" - ":"")+it.count+" "+(it.count===1?"song":"songs");
      text.append(title,meta);li.append(text);
      const go=document.createElement("button");go.className="tiny secondary";go.type="button";go.textContent="Show";
      go.addEventListener("click",()=>{input.value=(type==="artists"?"artist:":"album:")+JSON.stringify(it.name);run()});
      const a=document.createElement("div");a.className="queue-actions";a.append(go);li.append(a);return li;
    }
    if(type==="shows"){
      meta.textContent=it.count+" episode"+(it.count===1?"":"s");text.append(title,meta);li.append(text);return li;
    }
    const bits=[it.year,it.artist,it.album,it.duration?clock(it.duration):""].filter(Boolean);
    meta.textContent=bits.join(" - ");
    const where_=document.createElement("div");where_.className="muted";where_.textContent=where(it.copies);
    text.append(title,meta,where_);li.append(text);
    const add=document.createElement("button");add.className="tiny";add.type="button";add.textContent="Add to Up Next";
    if(!(it.copies||[]).some(c=>c.online)){add.disabled=true;add.title="Its computer is offline"}
    add.addEventListener("click",async()=>{
      add.disabled=true;
      try{const d=await post("/api/action",{action:"queue_add_key",key:it.id});showError("errorDash",d.message||"Added to Up Next");add.textContent="Added"}
      catch(err){showError("errorDash",err.message);add.disabled=false}
    });
    const a=document.createElement("div");a.className="queue-actions";a.append(add);li.append(a);return li;
  }
  function render(d){
    out.replaceChildren();let n=0;
    for(const g of d.groups||[]){
      const h=document.createElement("h3");h.textContent=LABELS[g.type]||g.type;
      const ul=document.createElement("ul");ul.setAttribute("aria-label",h.textContent);ul.className="find-list";
      for(const it of g.items||[]){
        if(availableOnly&&g.type!=="artists"&&g.type!=="albums"&&g.type!=="shows"&&!(it.copies||[]).some(c=>c.online))continue;
        ul.append(item(it,g.type));n++}
      out.append(h,ul);
    }
    const pending=(d.pending_origins||[]).length;
    status.textContent=n?n+(n===1?" result":" results")+(pending?" - still checking "+pending+(pending===1?" computer":" computers"):""):
      (pending?"Still checking "+pending+(pending===1?" computer":" computers")+"...":"Nothing in the house matches "+JSON.stringify(input.value.trim())+".");
  }
  function stop(){if(source){source.close();source=null}if(controller){controller.abort();controller=null}}
  async function run(){
    stop();const typed=input.value.trim();
    if(!typed&&!kind){out.replaceChildren();status.textContent="";return}
    const q=(typed+(kind?" kind:"+kind:"")).trim();
    const url="/api/search"+(typeof EventSource==="function"?"/stream":"")+"?q="+encodeURIComponent(q);
    if(typeof EventSource==="function"){
      source=new EventSource(url);
      source.addEventListener("results",e=>render(JSON.parse(e.data)));
      source.addEventListener("more",e=>render(JSON.parse(e.data)));
      source.addEventListener("done",()=>stop());
      source.onerror=()=>stop();
      return;
    }
    controller=new AbortController();
    try{const r=await fetch(url,{credentials:"same-origin",signal:controller.signal});const d=await r.json();if(!r.ok)throw Error(d.error||"Search failed");render(d)}
    catch(err){if(err.name!=="AbortError")status.textContent=err.message}
  }

  let kind="",availableOnly=false;
  for(const chip of document.querySelectorAll("#findChips button")){
    chip.addEventListener("click",()=>{
      if(chip.dataset.available){availableOnly=!availableOnly;chip.setAttribute("aria-pressed",String(availableOnly))}
      else{const on=kind!==chip.dataset.kind;kind=on?chip.dataset.kind:"";
        for(const other of document.querySelectorAll("#findChips button[data-kind]"))other.setAttribute("aria-pressed",String(other.dataset.kind===kind))}
      run();
    });
  }
  const lib=$("libraries"),body=$("libBody");
  let libLoaded=false;
  const crumb=(parts)=>{const p=document.createElement("p");p.className="muted";p.textContent=parts.join(" / ");return p};
  async function getJSON(url){const r=await fetch(url,{credentials:"same-origin"});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
  function showOrigins(d){
    body.replaceChildren();
    if(!(d.origins||[]).some(o=>(o.folders||[]).length)){body.textContent="No computers are sharing a library yet. Add one in SmoothCast, Preferences, Library.";return}
    for(const o of d.origins){
      if(!(o.folders||[]).length)continue;
      const h=document.createElement("h3");h.textContent=o.name+(o.online?"":" (offline)");body.append(h);
      const ul=document.createElement("ul");ul.className="find-list";
      for(const f of o.folders){
        const li=document.createElement("li");li.className="queue-item";
        const t=document.createElement("div"),s=document.createElement("strong"),m=document.createElement("div");
        s.textContent=f.label;m.className="muted";m.textContent=f.count+(f.count===1?" item":" items");t.append(s,m);
        const a=document.createElement("div");a.className="queue-actions";
        const b=document.createElement("button");b.type="button";b.className="tiny";b.textContent="Browse";
        b.addEventListener("click",()=>browse(o.id,o.name,f.label,""));a.append(b);li.append(t,a);ul.append(li);
      }
      body.append(ul);
    }
  }
  async function browse(origin,name,folder,path,cursor){
    try{
      const url="/api/libraries/"+encodeURIComponent(origin)+"/"+encodeURIComponent(folder)+"?path="+encodeURIComponent(path)+(cursor?"&cursor="+encodeURIComponent(cursor):"");
      const d=await getJSON(url);
      if(!cursor)body.replaceChildren();
      else{const old=body.querySelector(".more");if(old)old.remove()}
      if(!cursor){
        const back=document.createElement("button");back.type="button";back.className="tiny secondary";
        back.textContent=path?"Up":"All libraries";
        back.addEventListener("click",()=>{if(!path)showAll();else browse(origin,name,folder,path.split("/").slice(0,-1).join("/"))});
        body.append(back,crumb([name,folder,...(path?path.split("/"):[])]));
      }
      const ul=document.createElement("ul");ul.className="find-list";
      for(const dir of d.dirs||[]){
        const li=document.createElement("li");li.className="queue-item";
        const t=document.createElement("div"),s=document.createElement("strong"),m=document.createElement("div");
        s.textContent=dir.name;m.className="muted";m.textContent=dir.count+(dir.count===1?" item":" items");t.append(s,m);
        const a=document.createElement("div");a.className="queue-actions";
        const b=document.createElement("button");b.type="button";b.className="tiny secondary";b.textContent="Open";
        b.addEventListener("click",()=>browse(origin,name,folder,(path?path+"/":"")+dir.name));a.append(b);li.append(t,a);ul.append(li);
      }
      for(const it of d.items||[])ul.append(item(it,"songs"));
      body.append(ul);
      if(d.next){const more=document.createElement("button");more.type="button";more.className="tiny more";more.textContent="Load more";
        more.addEventListener("click",()=>browse(origin,name,folder,path,d.next));body.append(more)}
    }catch(err){body.textContent=err.message}
  }
  async function showAll(){try{showOrigins(await getJSON("/api/libraries"))}catch(err){body.textContent=err.message}}
  lib.addEventListener("toggle",()=>{if(lib.open&&!libLoaded){libLoaded=true;showAll()}});
  input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(run,120)});
})();
</script></body></html>"""
_HTML = _HTML.replace("/*TOKENS*/", design_tokens.css())
