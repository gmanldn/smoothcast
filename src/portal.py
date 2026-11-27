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
import guest_messages
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
import demo_mode
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
import link_acquisition
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
    markup = _HTML.replace("<!--SC_MESH_DETAILS-->", portal_mesh_panel.panel_html(), 1)
    markup = markup.replace(dashboard_close, portal_screen_page.panel_html() + dashboard_close, 1)
    return (markup.replace("__SC_BUILD__", page_build())
            .replace("__SC_VERSION__", version.identity_label())
            .replace("<!--SC_DEMO-->", _demo_badge())
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
        self.link_jobs = None
        self.mesh_acquisition_activity = None
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
            jobs = getattr(self, "link_jobs", None)
            if jobs is not None:
                jobs.close()
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
        if keys and self.link_jobs is not None:
            self.link_jobs.revoke(set(keys))
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
        if self.link_jobs is not None:
            self.link_jobs.revoke(owner_keys)
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

    def session_display_name(self, key: object) -> str | None:
        """Resolve a contributor from an internal authenticated session key."""
        if not isinstance(key, str) or len(key) != 64:
            return None
        with self._lock:
            now = self.clock()
            self._expire_sessions(now)
            session = self._sessions.get(key)
            if session is None:
                return None
            try:
                return self.room.touch(session.participant_id, now=now).name
            except portal_room.RoomError:
                return None

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
            return self._error(408, guest_messages.UPLOAD_TIMED_OUT)
        if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}:
            return self._error(507, guest_messages.NO_SPACE,
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
        body = (_NODES_HTML.replace("/*TOKENS*/", design_tokens.css())
                .replace("__MINE__", mine).replace("__ROWS__", rows)
                .replace("__SC_VERSION__", version.identity_label())
                .replace("<!--SC_DEMO-->", _demo_badge()))
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
        uploads = self.server.uploads
        state["room_transfers"] = uploads.room_transfers() if uploads is not None else []
        state["room"] = self.server.room.snapshot(participant_id)
        jobs = self.server.link_jobs
        state["link_capabilities"] = jobs.capabilities() if jobs is not None else {"youtube": False, "magnet": False}
        state["link_search_available"] = (jobs.search_available() if jobs is not None
                                          and callable(getattr(jobs, "search_available", None))
                                          else bool(state["link_capabilities"].get("youtube")))
        state["magnet_search_available"] = bool(jobs is not None
            and callable(getattr(jobs, "magnet_search_available", None)) and jobs.magnet_search_available())
        state["link_storage_available"] = jobs.storage_available() if jobs is not None else None
        provider = getattr(self.server, "link_readiness_provider", None)
        if provider is not None:
            # Only fixed prerequisite flags, never executable paths or environment values.
            state["link_owner_enabled"] = {kind: kind in provider.kinds for kind in ("youtube", "magnet")}
            # Fixed prerequisite flags, not paths or environment values.
            state["link_local_prerequisites"] = {
                kind: {"engine": bool(provider.tools.get(kind)),
                       "probe": bool(provider.probe),
                       "isolation": bool(provider.launcher)}
                for kind in ("youtube", "magnet")
            }
        state["link_jobs"] = jobs.snapshot(self.server._session_key(self._cookie_token() or "")) if jobs is not None else []
        activity = getattr(self.server, "mesh_acquisition_activity", None)
        state["mesh_link_activity"] = (activity.snapshot() if activity is not None else
                                       {"available": False, "nodes": [], "omitted_jobs": 0})
        directory = self.server.peer_directory
        state["screens"] = self.server.screens.snapshot()
        state["peers"] = directory.snapshot() if directory is not None else []
        state["peer_discovery_available"] = directory is not None
        return {"ok": True, "state": state, "build": page_build(),
                "client_schema": CLIENT_SCHEMA, "stream_epoch": self.server.room_events.epoch}

    def _event_key(self) -> tuple | None:
        """Cheap change detector over the published snapshot; ignores the moving playhead."""
        peeked = self.server.status_peek() if self.server.status_peek is not None else None
        uploads = self.server.uploads
        transfers = tuple(tuple(row.values()) for row in uploads.room_transfers()) if uploads is not None else ()
        if peeked is None:
            return (transfers,)
        state = peeked[1]
        queue = state.get("queue") if isinstance(state.get("queue"), list) else []
        items = tuple((q.get("id"), q.get("title")) for q in queue if isinstance(q, dict))
        fields = tuple(state.get(k) for k in (
            "title", "state", "receiver", "duration", "volume", "can_seek", "active", "busy",
            "session_id", "revision", "queue_revision", "music_autogain"))
        jobs = self.server.link_jobs
        activity = getattr(self.server, "mesh_acquisition_activity", None)
        return (fields, items, self.server.room.seq, jobs.revision() if jobs is not None else 0,
                activity.revision() if activity is not None else 0, transfers)

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
        key = self._event_key()
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
                return self._error(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
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
            return self._error(403, guest_messages.WRONG_ORIGIN)
        path = self._path()
        if (path in {"/api/login", "/api/action", "/api/profile", "/api/link-jobs", "/api/link-jobs/cancel",
                     "/api/link-jobs/retry", "/api/search/youtube", "/api/search/magnets"}
                or path.startswith("/api/uploads")) and not self._client_compatible():
            return
        if (path in {"/api/action", "/api/profile", "/api/link-jobs", "/api/link-jobs/cancel",
                     "/api/link-jobs/retry", "/api/search/youtube", "/api/search/magnets"}
                or path.startswith("/api/uploads")):
            if self._authenticated(csrf=True) and self._throttle(
                    "upload" if path.startswith("/api/uploads") else "mutation"):
                return
        if portal_screens_http.route(self, "POST", path):
            return  # parses its own body; must run before the generic parse
        if path == "/api/uploads/target":
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
            try:
                self._body()
                target = self.server.dispatch("upload_target", {
                    "_portal_auth_key": self.server._session_key(self._cookie_token() or ""),
                })
                return self._send(200, {"ok": True, **target})
            except PortalRequestError as exc:
                return self._exception_error(exc)
        if path == "/api/uploads":
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
            try:
                if self.server.uploads is None:
                    return self._error(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
                body = self._body()
                token = self._cookie_token() or ""
                queue_only = bool(body.get("queue", True))
                cast_target = body.get("cast_target")
                if cast_target is not None and not queue_only:
                    if not isinstance(cast_target, str) or not re.fullmatch(r"[0-9a-f]{64}", cast_target):
                        raise PortalRequestError(400, "Invalid casting target confirmation")
                    target = self.server.dispatch("upload_target", {
                        "_portal_auth_key": self.server._session_key(token),
                    })
                    if target.get("target_id") != cast_target:
                        raise PortalRequestError(409, "Casting target changed. Confirm the current receiver again.")
                bi, bt = body.get("batch_index"), body.get("batch_total")
                batch = (bi, bt) if type(bi) is int and type(bt) is int else None
                created = self.server.uploads.create(
                    token, body.get("name"), body.get("size"),
                    self.client_address[0], queue_only=queue_only, cast_target=cast_target if not queue_only else None,
                    batch=batch)
                key = self.server._session_key(token)
                if not self.server.session_key_active(key):
                    self.server.uploads.revoke_owner_keys({key})
                    return self._error(403, guest_messages.ACCESS_REMOVED)
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
                return self._error(403, guest_messages.SESSION_ENDED)
            try:
                if self.server.uploads is None:
                    return self._error(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
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
                    token, upload_id, queue_only=queue_only)
                if not self.server.session_key_active(key):
                    if dispatch:
                        self.server.uploads.finish_dispatch(token, upload_id, accepted=False)
                    self.server.uploads.revoke_owner_keys({key})
                    return self._error(403, guest_messages.ACCESS_REMOVED)
                if dispatch:
                    try:
                        self.server.dispatch("queue_add" if queue_only else "cast_upload", {
                            "path": str(media_path), "name": name,
                            "upload_id": upload_id, "early": False,
                            "cast_target": self.server.uploads.cast_target(token, upload_id),
                            "_portal_source": "upload",
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
                    self.server.uploads.finish_dispatch(token, upload_id, accepted=True)
                message = ("Added to the shared queue." if queue_only else
                           "Upload received; playback request accepted.")
                return self._send(202, {"ok": True, "message": message, "queue_only": queue_only})
            except PortalRequestError as exc:
                return self._exception_error(exc)
            except portal_uploads.UploadError as exc:
                return self._exception_error(exc)
            except OSError as exc:
                return self._upload_storage_error(exc, "finalise")
        if not self._safe_origin(required=True):
            return self._error(403, guest_messages.WRONG_ORIGIN)
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
        if path == "/api/search/magnets":
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
            jobs = self.server.link_jobs
            if jobs is None or not callable(getattr(jobs, "search_magnets", None)):
                return self._error(503, "Archive search is unavailable in this room.")
            owner = self.server._session_key(self._cookie_token() or "")
            try:
                return self._send(200, {"results": jobs.search_magnets(owner, body.get("q"))})
            except link_acquisition.LinkError as exc:
                return self._error(exc.status, exc.message)
        if path == "/api/search/youtube":
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
            jobs = self.server.link_jobs
            if jobs is None:
                return self._error(503, guest_messages.YOUTUBE_OFF)
            owner = self.server._session_key(self._cookie_token() or "")
            try:
                return self._send(200, {"results": jobs.search_youtube(owner, body.get("q"))})
            except link_acquisition.LinkError as exc:
                return self._error(exc.status, exc.message)
        if path in {"/api/link-jobs", "/api/link-jobs/cancel", "/api/link-jobs/retry"}:
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
            jobs = self.server.link_jobs
            if jobs is None:
                return self._error(503, guest_messages.LINK_DOWNLOADS_OFF)
            owner = self.server._session_key(self._cookie_token() or "")
            try:
                if path.endswith("/cancel"):
                    jobs.cancel(owner, body.get("id"))
                    return self._send(202, {"ok": True, "message": "Cancellation requested"})
                if path.endswith("/retry"):
                    job_id = jobs.retry(owner, body.get("id"))
                    return self._send(202, {"ok": True, "id": job_id,
                                            "message": "Retry accepted; Up Next updates when the media is ready"})
                if body.get("authorised") is not True:
                    return self._error(400, "Confirm that you are authorised to download this media")
                job_id = jobs.submit(owner, body.get("url"), body.get("request_id"))
                return self._send(202, {"ok": True, "id": job_id,
                                        "message": "Download accepted; Up Next updates when the media is ready"})
            except link_acquisition.LinkError as exc:
                return self._error(exc.status, exc.message)
        if path == "/api/profile":
            if not self._authenticated(csrf=True):
                return self._error(403, guest_messages.SESSION_ENDED)
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
                return self._error(403, guest_messages.SESSION_ENDED)
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
                            return self._error(400, guest_messages.SEEK_OUT_OF_RANGE)
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
                "cast_target": self.server.uploads.cast_target(self._cookie_token() or "", upload_id),
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
            return self._error(403, guest_messages.SESSION_ENDED)
        if self._throttle("upload"):
            return
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.headers.get("Transfer-Encoding"):
            return self._error(400, "Chunked transfer encoding is not supported")
        raw_length = self.headers.get("Content-Length")
        if self.server.uploads is None:
            return self._error(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
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
            return self._error(403, guest_messages.SESSION_ENDED)
        if self._throttle("upload"):
            return
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.server.uploads is None:
            return self._error(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
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
                 preferred_port: int = 0,
                 link_sources: tuple[str, ...] = ()) -> None:
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
        provider = link_acquisition.CommandProvider(link_sources)
        self.server.link_readiness_provider = provider
        if any(provider.capabilities().values()):
            def deliver(owner, path):
                # Existing authenticated GTK queue authority; never cast now.
                self.server.dispatch("queue_add", {"path": str(path), "name": path.name,
                                                   "_portal_source": "link",
                                                   "_portal_auth_key": owner})
            self.server.link_jobs = link_acquisition.LinkJobs(
                self.uploads.root / "link-acquisitions", provider, deliver,
                self.server.session_key_active)
        self.url = f"http://{self.bind_ip}:{self.port}/"
        self.friendly_url = f"http://{self.name}.local:{self.port}/"
        self._entry = None
        # Screens/QR read the live join URL so a claimed stable name is used.
        self.server.join_url = self.join_url
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

    def attach_entry(self, entry: object | None) -> None:
        """Point the join URL at a claimed stable entry name, or back at the numeric URL."""
        self._entry = entry

    def join_url(self) -> str:
        """The address a QR should encode: the stable entry name if claimed, else numeric."""
        entry = self._entry
        url = getattr(entry, "url", None) if entry is not None else None
        return url if isinstance(url, str) and url else self.url

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


# Fallback computer list (#591): same tokens and permanent Home control as the room.
def _demo_badge() -> str:
    """A visible DEMO marker on every page of an isolated demo host (#454), else nothing."""
    if not demo_mode.active():
        return ""
    return ('<span class="sc-demo" role="status" aria-label="Demo mode: no real receivers" '
            'style="font-size:.74rem;font-weight:700;letter-spacing:.06em;color:#fff;'
            'background:#b45309;border-radius:999px;padding:2px 9px;margin-left:6px">DEMO</span>')


_NODES_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><meta name="theme-color" content="#101722" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">
<meta name="color-scheme" content="light dark"><title>SmoothCast computers</title>
<style>/*TOKENS*/
:root{font:16px ui-rounded,"SF Pro Rounded","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}
.app-bar{position:sticky;top:0;display:flex;align-items:center;gap:12px;height:64px;padding:0 16px;border-bottom:1px solid var(--line);background:var(--bg)}
.home-btn{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 18px 0 13px;border-radius:999px;background:var(--accent);color:var(--on-accent);font-weight:750;text-decoration:none}
.home-btn svg{width:22px;height:22px;fill:currentColor}
.app-bar strong{font-size:1.1rem;letter-spacing:-.02em}
.sc-version{font-size:.74rem;font-weight:650;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 8px;white-space:normal;line-height:1.2;text-align:center}
main{max-width:640px;margin:auto;padding:24px 16px}
h1{font-size:clamp(1.5rem,5vw,2rem);letter-spacing:-.025em;margin:8px 0}p{color:var(--muted);line-height:1.5}
ul{list-style:none;padding:0;display:grid;gap:10px}
li a{display:flex;align-items:center;min-height:56px;padding:0 18px;border-radius:16px;border:1px solid var(--line);background:var(--card);color:var(--text);font-weight:650;text-decoration:none;overflow-wrap:anywhere}
li a:hover{border-color:var(--accent)}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
@media(max-width:560px){.app-bar{gap:8px;padding:0 12px}.home-btn{padding:0 15px 0 11px}.app-bar strong{display:none}}
@media(forced-colors:active){.home-btn{border:2px solid ButtonText}}
</style></head><body>
<header class="app-bar"><a class="home-btn" href="/" title="Back to this computer's room"><svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 3.2 2.6 11a1 1 0 0 0 1.3 1.5l.8-.7V20a1 1 0 0 0 1 1h4.3v-5.5h4v5.5h4.3a1 1 0 0 0 1-1v-8.2l.8.7a1 1 0 1 0 1.3-1.5z"/></svg><span>Home</span></a><strong>SmoothCast</strong><span class="sc-version" id="scVersion" aria-label="Host version __SC_VERSION__">__SC_VERSION__</span><!--SC_DEMO--></header>
<main><h1>SmoothCast in this house</h1><p>Open any computer to join its room.</p>
<ul><li><a href="/">__MINE__ (this one)</a></li>__ROWS__</ul></main></body></html>"""


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><meta name="theme-color" content="#101722" media="(prefers-color-scheme: dark)"><meta name="theme-color" content="#f4f7fb" media="(prefers-color-scheme: light)">
<meta name="color-scheme" content="light dark"><title>SmoothCast</title>
<style>
:root{font:16px system-ui,sans-serif;color-scheme:light dark}/*TOKENS*/
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.05rem;margin:0 0 12px}p{color:var(--muted);margin:.35rem 0}
section{background:var(--card);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 26px var(--shadow)}
label{display:block;margin:12px 0 6px}select{font:inherit;min-height:44px;max-width:100%;padding:0 10px;border-radius:10px;border:1px solid var(--border);background:var(--input);color:inherit}input,button{font:inherit;min-height:44px;border-radius:10px;border:1px solid var(--border);padding:8px 12px}
input{width:100%;color:inherit;background:var(--input)}button{background:var(--accent);color:white;border:0;font-weight:650;cursor:pointer}
#musicAutogain{width:auto;min-height:0;margin-right:8px}
dialog#shortcutsHelp{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:14px;max-width:min(92vw,480px);width:100%;padding:20px}
dialog#shortcutsHelp::backdrop{background:var(--scrim)}
#shortcutsList{display:grid;gap:8px}
#shortcutsList li{display:flex;justify-content:space-between;gap:12px;align-items:center}
#shortcutsList kbd{border:1px solid var(--border);border-radius:6px;padding:4px 7px;white-space:nowrap}
button.secondary{background:var(--secondary);color:var(--on-secondary)}button:disabled,input:disabled{opacity:.55;cursor:default}.actions{display:flex;gap:8px;flex-wrap:wrap}
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
.site-mark{display:grid;place-items:center;flex:none;width:48px;height:48px;border-radius:14px;background:var(--accent);color:var(--on-accent);font-size:1.6rem;font-weight:800}
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
#findPanel .find-intro{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap}
#findPanel .find-intro h2{margin:0}
#findPanel .find-search{background:var(--input);border:1px solid var(--line);border-radius:16px;padding:clamp(12px,2.5vw,22px);margin:14px 0 18px;min-width:0}
#findPanel .find-field{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}
#findPanel #findInput{min-width:0;margin:0;font-size:1.05rem;min-height:48px;background:var(--card)}
#findPanel #findClear{min-height:48px;padding-inline:12px}
#findPanel .find-sources{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:8px;margin-top:12px}
#findPanel .find-source{padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--card);min-width:0}
#findPanel .find-source button{width:100%;min-height:44px}
#findPanel .find-source p{margin:6px 0 0}
#findChips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
#findPanel #findChips button{min-height:44px;padding:8px 13px}
#findPanel #findChips button[aria-pressed="true"]{background:var(--accent);color:var(--on-accent)}
#findPanel .find-results-head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-top:18px}
#findPanel .find-results-head h3{margin:0;font-size:1.1rem}
#findPanel #findStatus{margin:6px 0 12px;overflow-wrap:anywhere}
#findPanel .find-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:8px;margin:8px 0 18px}
#findPanel .find-list .queue-item{display:flex;flex-direction:column;align-items:stretch;justify-content:space-between;gap:10px;border:1px solid var(--line);border-radius:12px;padding:12px;background:var(--input);min-width:0}
#findPanel .find-list .queue-item strong{font-size:1rem;white-space:normal;overflow-wrap:anywhere;line-height:1.35}
#findPanel .find-list .queue-item .muted{font-size:.85rem;line-height:1.45}
#findPanel .find-list .queue-actions{justify-content:flex-start}
#findPanel .find-list .queue-actions button{min-height:44px;padding:8px 12px;width:100%}
#findPanel .find-list .field-hint:empty{display:none}
#findPanel .find-availability{font-weight:650}
#findPanel #youtubeResultsPanel{box-shadow:none;margin-top:12px}
#findPanel #libraries{margin-top:16px}
#findPanel #findEmpty{padding:18px;text-align:left}
#findPanel #findEmpty p{margin:5px 0}
@media(max-width:360px){#findPanel .find-field{grid-template-columns:minmax(0,1fr)}#findPanel #findClear{width:100%}}
#findChips button[aria-pressed="true"]{outline:2px solid var(--focus);outline-offset:1px}
#queuePanel{border-top:3px solid var(--accent)}
#queuePanel .contribute{margin:0 0 16px;padding:12px;border:1px solid var(--line);border-radius:14px;background:var(--input)}
#queuePanel .contribute h3{margin:0;font-size:1.1rem}
#queuePanel .queue-add-links{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:8px;margin-top:10px}
#queuePanel .queue-add-links a{display:flex;flex-direction:column;justify-content:center;gap:3px;min-height:64px;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--card);color:var(--text);text-decoration:none;overflow-wrap:anywhere}
#queuePanel .queue-add-links a:first-child{border-color:var(--accent)}
#queuePanel .queue-add-links a:hover{background:var(--nav-hover)}
#queuePanel .queue-add-links a:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
#queuePanel .queue-add-links span{font-size:.82rem;color:var(--muted);line-height:1.4}
#queuePanel #linkAcquisition{margin-top:12px;min-width:0;box-shadow:none;border:1px solid var(--line);padding:12px}
#linkAcquisition>summary{font-weight:750;cursor:pointer;min-height:44px;align-content:center}
#linkForm{display:grid;gap:8px}#linkForm label{margin:0}#linkForm input[type="text"]{min-width:0}#linkForm button{justify-self:start;max-width:100%}
#linkForm .toggle{border-top:1px solid var(--line);padding-top:10px}#linkAvailability{margin:8px 0;overflow-wrap:anywhere}
#libraryCopiesPanel,#linkJobPanel{margin:12px 0 0;padding:10px;border:1px solid var(--line);border-radius:12px;box-shadow:none}
#libraryCopiesPanel h3,#linkJobPanel h4{margin:0 0 8px;font-size:.95rem}
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
#advancedPanel>h2,#localLivePanel>h2{margin:0 0 8px}
#advancedPanel>p{font-size:.88rem;margin:6px 0}
.advanced-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-top:14px}
.advanced-grid>section{margin:0;box-shadow:none;border:1px solid var(--line);min-width:0}
.advanced-grid h3{font-size:1rem;margin:0 0 8px}
#dashboard #errorDash:not(:empty){background:var(--input);padding:12px;border-radius:10px}
#queuePanel #uploadCard{min-width:0;margin-top:12px;padding:12px;border:1px solid var(--line);border-radius:14px;background:var(--input);box-shadow:none}
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
.tech-details{margin-top:12px;border-top:1px solid var(--line);padding-top:6px}
.tech-details>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-weight:650;color:var(--muted)}
.transfer-live{border-top:0;margin-top:6px;padding-top:0;min-width:0}
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
  #playback{grid-column:1}
  #findPanel{grid-column:2}
  #queuePanel{grid-column:1/-1}
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

/* Ticket 591 refresh: sticky app bar with a permanent Home control, rounded system
   type, a clear surface hierarchy and Now Playing as the room's focal "screen".
   Colours come only from the tested tokens above. */
:root{--font:ui-rounded,"SF Pro Rounded","Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --bar-h:64px;--r-lg:22px;--r-md:14px;--r-sm:10px;font-family:var(--font)}
body{font-family:var(--font);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  background:var(--bg);background-image:radial-gradient(120% 60% at 50% -10%,color-mix(in srgb,var(--accent) 14%,transparent),transparent 60%);background-attachment:fixed}
h1,h2,h3{color:var(--text);letter-spacing:-.018em;font-weight:720}
h2{font-size:1.18rem}
#elapsed,#duration,#volumeText,.transfer-stats,time{font-variant-numeric:tabular-nums}
header.app-bar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:12px;height:var(--bar-h);
  padding:0 max(14px,env(safe-area-inset-right)) 0 max(14px,env(safe-area-inset-left));border-bottom:1px solid var(--line);
  background:var(--bg);background:color-mix(in srgb,var(--bg) 84%,transparent);-webkit-backdrop-filter:saturate(1.5) blur(16px);backdrop-filter:saturate(1.5) blur(16px)}
.home-btn{display:inline-flex;align-items:center;gap:8px;flex:none;min-height:44px;padding:0 18px 0 13px;border-radius:999px;
  background:var(--accent);color:var(--on-accent);font-weight:750;font-size:.98rem;text-decoration:none;box-shadow:0 6px 18px var(--shadow)}
.home-btn svg{width:22px;height:22px;fill:currentColor}
.home-btn:hover{filter:brightness(1.08)}.home-btn:active{transform:scale(.97)}
.brand{display:flex;align-items:center;gap:10px;flex:none}
.brand h1{margin:0;font-size:1.12rem;letter-spacing:-.02em;white-space:nowrap}
.sc-version{flex:none;font-size:.74rem;font-weight:650;font-variant-numeric:tabular-nums;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 8px;white-space:normal;line-height:1.2;text-align:center}
.brand .site-mark{width:44px;height:44px;border-radius:13px;font-size:1.2rem;text-decoration:none;background:linear-gradient(135deg,var(--accent),var(--vote-on));transition:transform .12s ease,box-shadow .12s ease}
.brand .site-mark:hover{transform:translateY(-1px);box-shadow:0 6px 16px var(--shadow)}
.bar-now{margin-left:auto;flex:0 1 auto;display:flex;align-items:center;gap:9px;min-width:0;max-width:min(44vw,360px);min-height:44px;padding:0 15px;
  border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--text);text-decoration:none;font-size:.88rem}
.bar-now:hover{border-color:var(--accent)}
.bar-dot{flex:none;width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 25%,transparent)}
.bar-now.paused .bar-dot{background:var(--dim);box-shadow:none}
.bar-now-text{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-now-label{color:var(--muted)}
#barNowTitle{font-weight:680}
main{padding-top:6px}
.site-intro:focus{outline:none}
.site-intro{scroll-margin-top:var(--bar-h)}
.site-intro{margin:14px 2px 4px;font-size:.95rem}
#dashboard nav{top:calc(var(--bar-h) + 6px);z-index:20;margin-inline:-10px;padding:8px 10px;border-radius:20px;background:var(--bg);background:color-mix(in srgb,var(--bg) 90%,transparent);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
#dashboard nav a{min-height:40px;padding:0 15px;border-radius:999px;font-size:.9rem;font-weight:620;border:1px solid var(--line);background:var(--card);color:var(--on-nav)}
#dashboard nav a:hover{background:var(--nav-hover)}
#dashboard[data-room-blade="homePanel"]>:not(nav):not(#errorDash):not(#homePanel),
#dashboard[data-room-blade="peoplePanel"]>:not(nav):not(#errorDash):not(#peoplePanel),
#dashboard[data-room-blade="screensPanel"]>:not(nav):not(#errorDash):not(#screensPanel),
#dashboard[data-room-blade="meshPanel"]>:not(nav):not(#errorDash):not(#meshPanel),
#dashboard[data-room-blade="findPanel"]>:not(nav):not(#errorDash):not(#findPanel),
#dashboard[data-room-blade="advancedPanel"]>:not(nav):not(#errorDash):not(#advancedPanel){display:none}
#dashboard:not([data-room-blade])>:not(nav):not(#errorDash):not(#homePanel){display:none}
#dashboard[data-room-blade]>#findPanel,#dashboard[data-room-blade]>#advancedPanel{grid-column:1/-1}
#dashboard[data-room-blade]>#homePanel,#dashboard[data-room-blade]>#peoplePanel,#dashboard[data-room-blade]>#screensPanel,#dashboard[data-room-blade]>#meshPanel{grid-column:1/-1}
#dashboard nav a[aria-current="page"]{border-color:var(--accent);font-weight:750}
#dashboard section,#advancedPanel{scroll-margin-top:calc(var(--bar-h) + 70px)}
section,.welcome,#advancedPanel{border-radius:var(--r-lg);border:1px solid var(--line);box-shadow:0 1px 0 color-mix(in srgb,var(--text) 6%,transparent) inset,0 14px 34px var(--shadow)}
.advanced-grid>section,.transfer-journey,.help .help-body,#login .steps li{border-radius:var(--r-md)}
input,select{border-radius:var(--r-sm)}
input:focus-visible{border-color:var(--accent)}
button{border-radius:12px;transition:filter .15s ease,transform .1s ease}
button:hover:not(:disabled){filter:brightness(1.07)}button:active:not(:disabled){transform:scale(.98)}
.tiny{border-radius:999px}
.welcome h2{font-size:1.45rem}
.quick-links a{border-radius:999px;border-color:var(--line);background:var(--card)}
.quick-links a:hover{border-color:var(--accent);background:var(--nav-hover)}
#login{border-radius:var(--r-lg)}
#login h2{font-size:clamp(1.6rem,5vw,2.1rem)}
/* The focal screen: Now Playing glows like the TV it controls. */
#playback{position:relative;overflow:hidden;padding:22px;background:var(--card);
  background-image:radial-gradient(90% 70% at 50% -20%,color-mix(in srgb,var(--accent) 26%,transparent),transparent 70%)}
#playback::before{content:"";position:absolute;inset:0 18% auto;height:2px;border-radius:2px;background:var(--accent);opacity:.85;box-shadow:0 0 22px 4px color-mix(in srgb,var(--accent) 45%,transparent)}
#playback #title{font-size:clamp(1.45rem,4.5vw,2rem);line-height:1.15;letter-spacing:-.025em;color:var(--text);margin:.4rem 0 .2rem}
#playback #receiver{font-size:.9rem}
progress{-webkit-appearance:none;appearance:none;height:8px;border:0;border-radius:999px;background:var(--input);overflow:hidden;margin-top:14px}
progress::-webkit-progress-bar{background:var(--input);border-radius:999px}
progress::-webkit-progress-value{background:var(--accent);border-radius:999px}
progress::-moz-progress-bar{background:var(--accent);border-radius:999px}
input[type="range"]{accent-color:var(--accent);background:transparent;border:0;padding:0}
#playback .actions button[data-action="play_pause"]{flex-basis:100%;min-height:56px;font-size:1.05rem;border-radius:16px}
@media(min-width:520px){#playback .actions button[data-action="play_pause"]{flex-basis:auto;flex-grow:2}}
.invite{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:center;max-width:660px;margin:0 auto 14px;padding:18px 20px}
#login:not([hidden])~.invite{margin-top:4px}
body:has(#dashboard:not([hidden])) .invite{max-width:none}
.invite h2{margin:0 0 4px;font-size:1.15rem}
.invite-how{margin:0 0 4px;color:var(--text)}
.invite .room-link{border-top:0;margin-top:10px;padding-top:0}
.invite #roomLinkStatus:empty{display:none}
.invite #roomLinkHint{margin-bottom:0}
.invite .room-link label{font-weight:600;color:var(--muted);font-size:.88rem}
.invite-qr{margin:0;display:grid;justify-items:center}
.invite-qr img{display:block;width:144px;height:144px;padding:8px;border-radius:14px;background:white;box-shadow:0 0 0 1px var(--line);image-rendering:pixelated}
.invite-qr figcaption{max-width:12rem;font-size:.85rem;color:var(--muted);text-align:center}
@media(max-width:560px){.invite{gap:12px;padding:14px}.invite-qr img{width:112px;height:112px;padding:6px}.invite #roomLinkHint{display:none}.invite .room-link{grid-template-columns:minmax(0,1fr)}.invite .room-link button{width:100%}}
@media(max-width:360px){.invite{grid-template-columns:minmax(0,1fr)}.invite-qr{justify-items:start}}
@media(max-width:560px){:root{--bar-h:60px}header.app-bar{gap:8px}.home-btn{padding:0 15px 0 11px}.brand{gap:7px;flex:1 1 auto;min-width:0}.brand h1{display:none}.sc-version{flex:0 1 auto;min-width:0;overflow-wrap:anywhere;text-align:left}.bar-now{max-width:none;padding:0 12px}.bar-now-label{display:none}}
@media(max-width:340px){.brand .site-mark{display:none}}
@media(forced-colors:active){header.app-bar{background:Canvas;backdrop-filter:none}.home-btn{border:2px solid ButtonText}#playback::before{display:none}}
@media(prefers-reduced-transparency:reduce){header.app-bar,#dashboard nav{background:var(--bg);backdrop-filter:none;-webkit-backdrop-filter:none}}
/* Ticket 624: a concise Home landing pane. It is the default room view: pick a
   device, add media, and see the queue and who is here without the full wall of
   panels. Every action is a plain anchor or button so keyboard and screen
   readers work without custom widgets. */
#homePanel{grid-column:1/-1;background:var(--card);border:1px solid var(--line);border-radius:var(--r-lg);padding:22px}
#homePanel h2{font-size:clamp(1.45rem,4.5vw,1.95rem);margin:4px 0}
#homePanel .home-lead{color:var(--text);font-size:.98rem}
.home-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,215px),1fr));gap:10px;margin:16px 0 6px}
.home-action{display:flex;flex-direction:column;gap:4px;min-height:92px;padding:14px 15px;border:1px solid var(--border);border-radius:var(--r-md);background:var(--input);color:var(--text);text-decoration:none;transition:border-color .15s ease,background .15s ease,transform .1s ease}
.home-action:hover{border-color:var(--accent);background:var(--nav-hover);transform:translateY(-1px)}
.home-action:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.home-action:active{transform:scale(.99)}
.home-icon{font-size:1.3rem;line-height:1}
.home-action strong{font-size:.98rem}
.home-action span{font-size:.8rem;color:var(--muted);line-height:1.35}
.home-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-top:14px}
@media(min-width:720px){.home-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.home-card{border:1px solid var(--line);border-radius:var(--r-md);padding:14px;background:var(--bg);min-width:0}
.home-card h3{margin:0 0 8px;font-size:1rem}
.home-device{font-size:1.08rem;font-weight:700;margin:0;overflow-wrap:anywhere}
#homePanel #castEntry{border-radius:var(--r-md);margin-top:14px;box-shadow:none;background:var(--input)}
#homePanel #playback{border-radius:var(--r-md);margin:0 0 14px;box-shadow:none;background:var(--input)}
#homePanel #quickCastCard{border-radius:var(--r-md);margin:0 0 14px;box-shadow:none;background:var(--input)}
/* Flat, compact Home: one focal player, one quick cast action and a short queue. */
#dashboard nav{backdrop-filter:none;-webkit-backdrop-filter:none;background:var(--bg);border-radius:0;gap:4px}
#dashboard nav a{min-height:44px;border-color:transparent;background:transparent;padding:0 12px}
#dashboard nav a[aria-current="page"]{background:var(--input);border-color:var(--accent)}
#homePanel{background:transparent;border:0;box-shadow:none;padding:0;min-width:0}
#homePanel>.room-heading{margin:0 0 12px;flex-wrap:wrap;gap:6px}
#homePanel .home-lead{font-size:.84rem;color:var(--muted);margin:0}
#homePanel #quickCastCard{padding:14px 16px}
#homePanel #quickCastHeading{font-size:1rem;margin:0 0 8px}
#homePanel #playback{padding:16px;background:var(--card)}
#homePanel #playback::before{display:none}
#homePanel #playbackHeading{font-size:1rem}
#homePanel #playback .actions button[data-action="play_pause"]{min-height:44px;flex-basis:auto;flex-grow:2}
#homePanel .home-actions{grid-template-columns:repeat(auto-fit,minmax(min(100%,8rem),1fr));gap:6px;margin:10px 0}
#homePanel .home-action{min-height:44px;flex-direction:row;align-items:center;gap:8px;padding:9px 10px;border-color:var(--line);background:transparent;transition:none}
#homePanel .home-action:hover,#homePanel .home-action:active{transform:none}
#homePanel .home-action span:not(.home-icon){display:none}
#homePanel .home-action strong{font-size:.85rem}
#homePanel .home-icon{font-size:1rem}
#homePanel .home-grid{grid-template-columns:minmax(0,1fr);gap:8px;margin-top:10px}
#homePanel .home-card{padding:12px;background:var(--card)}
#homePanel .home-card summary{cursor:pointer;min-height:32px;font-weight:650}
#homePanel #castEntry{padding:0;margin-top:0;background:transparent;border:0}
body:has(#dashboard:not([hidden])[data-room-blade]:not([data-room-blade="homePanel"])) #roomInvite{display:none}
@media(min-width:720px){#homePanel .home-actions{grid-template-columns:repeat(4,minmax(0,1fr))}}
</style></head><body><noscript><p style="margin:0;padding:14px 16px;text-align:center;font:16px/1.4 system-ui,sans-serif">SmoothCast needs JavaScript to work. Turn it on in your browser settings, then reload this page.</p></noscript><header class="app-bar" id="appBar"><a class="home-btn" id="homeButton" href="#roomTop" title="Back to the top of the room"><svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 3.2 2.6 11a1 1 0 0 0 1.3 1.5l.8-.7V20a1 1 0 0 0 1 1h4.3v-5.5h4v5.5h4.3a1 1 0 0 0 1-1v-8.2l.8.7a1 1 0 1 0 1.3-1.5z"/></svg><span>Home</span></a><div class="brand"><a class="site-mark" id="homeLogo" href="#roomTop" aria-label="SmoothCast home" title="SmoothCast home">S</a><h1>SmoothCast</h1><span class="sc-version" id="scVersion" aria-label="Host version __SC_VERSION__">__SC_VERSION__</span><!--SC_DEMO--></div><a class="bar-now" id="barNow" href="#playback" hidden><span class="bar-dot" aria-hidden="true"></span><span class="bar-now-text"><span class="bar-now-label">Now playing</span> <span id="barNowTitle"></span></span></a></header><main><p class="site-intro" id="roomTop" tabindex="-1">Watch, listen and build the queue together, on your own Wi-Fi.</p>
<div id="updateNotice" role="alert" hidden><strong>SmoothCast was updated</strong><p>Reload to reconnect safely.</p><button id="reloadNow" type="button">Reload page</button></div>
<section id="login" aria-labelledby="joinTitle"><p class="eyebrow">Welcome to the shared room</p><h2 id="joinTitle">Join the house</h2>
<p>Use your phone or computer as a remote, add your own music or films, and help choose what's next. No app, account or cloud connection needed.</p>
<ol class="steps" aria-label="How SmoothCast works"><li><strong>1. Join</strong>Enter a name so everyone knows who's here.</li><li><strong>2. Add or find</strong>Choose something from the house or upload a file.</li><li><strong>3. Share the queue</strong>Vote, move items and control the room together.</li></ol>
<form id="loginForm"><label for="name">Your display name</label><p class="field-hint" id="nameHint">Shown to others in this room. You can change it later.</p>
<input id="name" name="name" maxlength="40" autocomplete="nickname" placeholder="e.g. Sam" aria-describedby="nameHint" required>
<div id="pinRow"><label for="pin">House PIN</label><p class="field-hint" id="pinHint">Ask whoever runs SmoothCast for the six-digit House PIN shown on their computer.</p>
<input id="pin" name="pin" minlength="6" maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" aria-describedby="pinHint" required></div>
<p id="loginHint" class="field-hint">Your device must be on the same Wi-Fi. You only need a House PIN if one has been set.</p>
<p id="error" role="alert" aria-live="polite"></p><button type="submit">Join</button></form>
<details class="help"><summary>Room privacy and what guests can do</summary><div class="help-body"><p>Everyone who joins can control playback and contribute to the same Up Next queue. Playback actions affect the selected TV or speaker, not just your phone.</p><p>The room runs on a computer in this home, not in the cloud. Only join rooms you trust, and ask the person who runs SmoothCast if you are unsure.</p></div></details>
</section>
<section id="roomInvite" class="invite" aria-labelledby="inviteHeading"><div class="invite-text"><h2 id="inviteHeading">Invite someone</h2><p class="invite-how" id="inviteHow">Point a phone camera at the code to join this room. The phone must be on the same Wi-Fi.</p><div class="room-link"><label for="roomLinkText">Or send this link</label><input id="roomLinkText" type="text" readonly aria-describedby="roomLinkHint" title="Local address guests can open in their browser"><button id="roomLinkCopy" type="button">Copy link</button><p id="roomLinkHint" class="field-hint">Send this address to someone on the same Wi-Fi. The link contains no PIN or account information.</p><p id="roomLinkStatus" role="status" aria-live="polite"></p></div></div><figure class="invite-qr"><img id="inviteQr" width="144" height="144" alt="QR code that opens this SmoothCast room" hidden><figcaption id="inviteQrFallback" hidden>The code isn't available right now. Send the link instead.</figcaption></figure></section>
<div id="dashboard" hidden>
<nav aria-label="Jump to room section"><a href="#homePanel">Home</a><a href="#findPanel">Find</a><a href="#screensPanel">Screens</a><a id="meshNavLink" href="#meshPanel">Mesh</a><a href="#peoplePanel">People</a><a href="#advancedPanel">Settings</a></nav>
<section id="homePanel" aria-labelledby="homeHeading">
<div class="room-heading"><h2 id="homeHeading" tabindex="-1">Your room</h2><span class="home-lead"><span id="joinedAs" aria-live="polite"></span> · <a href="#nameForm">Change name</a></span></div>
<section id="quickCastCard" aria-labelledby="quickCastHeading">
<h2 id="quickCastHeading">Cast from this device</h2>
<div class="actions"><button id="uploadCastNow" type="button" aria-describedby="quickCastStatus">Upload &amp; Cast Now</button><a href="#uploadCard" id="quickQueueUpload">Add to Up Next instead</a></div>
<p id="quickCastStatus" class="field-hint" role="status" aria-live="polite">No file is sent until you confirm the destination.</p>
</section>
<section id="playback" aria-labelledby="playbackHeading">
<div class="room-heading"><h2 id="playbackHeading" tabindex="-1">Now Playing</h2><span id="state" class="muted">—</span></div>
<p id="title" class="big">Nothing playing</p><p id="nowDetails" class="muted" hidden></p><p id="receiver">Playing on: —</p>
<progress id="progress" max="1" value="0" aria-label="Playback progress"></progress>
<div class="row"><span id="elapsed">0:00</span><span id="duration">—</span></div>
<label for="seek">Playback position</label><p id="seekHelp" class="field-hint">Seeking needs a connected TV or speaker and a known length.</p>
<input id="seek" type="range" min="0" max="1" value="0" aria-describedby="seekHelp" title="Seek within the current film or track" disabled>
<div class="actions"><button data-action="play_pause" title="Play or pause for everyone watching this TV or speaker">Play / pause</button><button class="secondary" data-action="stop" title="Stop playing on the TV or speaker">Stop</button><button class="secondary" data-action="previous" title="Go to the previous item for everyone">Previous</button><button class="secondary" data-action="next" title="Skip to the next item for everyone">Next</button></div>
<div class="actions" role="group" aria-label="Fine playback controls"><button id="seekBackTen" type="button" class="secondary" disabled aria-label="Seek back 10 seconds">−10 s</button><button id="seekForwardTen" type="button" class="secondary" disabled aria-label="Seek forward 10 seconds">+10 s</button><button id="toggleMute" type="button" class="secondary" disabled>Toggle mute</button></div>
<label for="volume">TV or speaker volume</label><span class="field-hint" id="volumeHelp" hidden>Changes the volume on the TV or speaker, not this device.</span>
<input id="volume" type="range" min="0" max="100" value="0" aria-describedby="volumeHelp" title="Change the TV or speaker volume" disabled><p id="volumeText" class="muted">—</p>
<details class="help"><summary>Explain playback controls</summary><div class="help-body"><p><strong>Play / pause</strong> resumes or pauses the TV or speaker. <strong>Stop</strong> ends its current playback. <strong>Previous</strong> and <strong>Next</strong> change what everybody hears or sees.</p><p><strong>Seek</strong> changes the current position without changing the shared queue. If a control is dimmed, the TV or speaker is not ready or cannot do that.</p></div></details>
</section>
<div class="home-actions" role="group" aria-label="Quick actions">
<a class="home-action" id="homeUpload" href="#uploadCard" title="Send a file from this phone or computer to the room"><span class="home-icon" aria-hidden="true">⬆</span><strong>Upload or transfer</strong><span>Send a file from this device</span></a>
<a class="home-action" id="homeYoutube" href="#queuePanel" data-home-link="youtube" title="Open the add-link box to paste a YouTube video URL"><span class="home-icon" aria-hidden="true">▶</span><strong>Cast a YouTube link</strong><span>Paste a YouTube video URL</span></a>
<a class="home-action" id="homeMagnet" href="#queuePanel" data-home-link="magnet" title="Open the add-link box to paste a magnet link"><span class="home-icon" aria-hidden="true">🧲</span><strong>Cast a magnet link</strong><span>Paste a torrent magnet link</span></a>
<a class="home-action" id="homeFind" href="#findPanel" title="Search the house libraries and YouTube"><span class="home-icon" aria-hidden="true">🔍</span><strong>Find something</strong><span>Search the house and YouTube</span></a>
</div>
<section id="queuePanel" aria-labelledby="queueHeading"><div class="room-heading"><h2 id="queueHeading" tabindex="-1">Shared Up Next</h2><span id="queueCount" class="muted"></span></div>
<div class="quick-links"><a href="#meshPanel" id="queueMeshLink" hidden>Mesh targets</a></div>
<div class="contribute" aria-labelledby="contributeHeading"><h3 id="contributeHeading">Add something to play</h3><p class="field-hint">Choose a file, paste a link or find media. Up Next keeps current playback uninterrupted.</p><div class="queue-add-links"><a href="#uploadCard" id="openUploadEntry"><strong>Choose files</strong><span>From your phone or computer</span></a><a href="#linkAcquisition" id="openLinkAcquisition"><strong>Paste a video link</strong><span>YouTube or magnet</span></a><a href="#findPanel" id="openFindEntry"><strong>Find media</strong><span>Shared libraries and YouTube</span></a></div></div>
<p class="section-desc">Choose <strong>Play now</strong> to request immediate room playback, or <strong>Next</strong> to put an item first in line without stopping the current film. Everyone here can reorder or remove waiting items.</p>
<p id="queueFeedback" class="field-hint" role="status" aria-live="polite">Queue changes appear here once the SmoothCast computer accepts them.</p>

<button id="clearQueue" class="secondary tiny" type="button" title="Remove waiting items without stopping what is playing" disabled>Clear Up Next</button>
<ul id="queue" aria-label="Shared Up Next queue" tabindex="-1"><li class="empty">Nothing in Up Next yet</li></ul>
<section id="queueIncomingPanel" aria-labelledby="queueIncomingHeading" hidden><h3 id="queueIncomingHeading">Incoming media</h3><ul id="queueIncomingRows" aria-label="Files arriving before queue acceptance"></ul><p class="field-hint">Files appear here immediately, then move into playback or Up Next when accepted.</p></section>
<section id="libraryCopiesPanel" aria-labelledby="libraryCopiesHeading" hidden><h3 id="libraryCopiesHeading">Shared-library transfers</h3><ul id="libraryCopyRows" aria-label="Shared library transfer activity"></ul></section>
<section id="uploadCard" aria-labelledby="uploadHeading" hidden><h3 id="uploadHeading" tabindex="-1">Add files from this device</h3>
<p class="section-desc">Choose music or video stored on your phone or computer; SmoothCast sends it to the SmoothCast computer over your Wi-Fi.</p>
<label for="videoFile">Audio or video files</label><input id="videoFile" type="file" accept=".mp4,.m4v,.mkv,.mov,.avi,.webm,.ts,.mpeg,.mpg,.wmv,.mp3,.aac,.m4a,.flac,.ogg,.opus,.wav,.aiff,.aif" multiple title="Choose media stored on this device">
<p id="uploadSelectionHint" class="field-hint">Choose files, or drop them anywhere in this panel. Submitted filenames and transfer progress are visible to everyone in this room. Audio always goes to Up Next. You can pause safely and resume while this browser still has the file.</p>
<p id="uploadSelectionSummary" class="field-hint" aria-live="polite">No files selected. Choose a video or audio file to begin.</p>
<label class="toggle" for="uploadQueue"><input id="uploadQueue" type="checkbox" checked><span><strong>Add to Up Next</strong><span class="field-hint" style="display:block">Default. Files transfer with smart buffering and join Up Next without interrupting what's playing. Untick to request Play now for video.</span></span></label>
<div id="transferJourney" class="transfer-journey" aria-label="File transfer stages">
<ol id="transferSteps" class="transfer-steps" aria-label="Transfer stages">
<li data-stage="choose" class="done"><span class="stage-dot">1</span><span>Choose file</span></li>
<li data-stage="prepare"><span class="stage-dot">2</span><span>Prepare</span></li>
<li data-stage="transfer"><span class="stage-dot">3</span><span>Transfer</span></li>
<li data-stage="verify"><span class="stage-dot">4</span><span>Check media</span></li>
<li data-stage="deliver"><span class="stage-dot">5</span><span>Queue / play</span></li>
</ol>
<div class="transfer-route" aria-label="Current file route"><span>Your device</span><span aria-hidden="true">→</span><strong id="transferHost">SmoothCast computer</strong><span aria-hidden="true">→</span><strong id="transferDestination">Up Next</strong></div>
<div class="transfer-meter"><strong id="transferStage" aria-live="polite">Ready to choose</strong><span id="transferPercent">0%</span></div>
<progress id="uploadProgress" max="1" value="0" aria-label="File transfer bytes received"></progress>
<div class="transfer-stats"><span id="transferBytes">0 B of 0 B</span><span id="transferRate">—</span><span id="transferEta">—</span></div>
<details class="tech-details" id="transferTech"><summary>Technical details</summary><div class="transfer-live" aria-labelledby="transferLiveHeading">
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
<p id="transferExplanation" class="field-hint">A percentage measures bytes received by this host. Bytes sent by the browser are not yet confirmed on disk. Media checks and queue or playback confirmation follow afterwards. Cross-node routing will appear only when a mesh transfer session confirms it.</p></details>
</div><p id="uploadStatus" role="status" aria-live="polite"></p>
<div class="actions"><button id="uploadButton" type="button" title="Transfer the selected files to the room" aria-describedby="uploadSelectionHint" disabled>Upload and add</button><button id="pauseUpload" class="secondary" type="button" hidden>Pause transfer</button><button id="cancelUpload" class="secondary" type="button" hidden>Cancel upload</button><a class="upload-view-queue" href="#queuePanel">View shared Up Next</a></div>
<details class="help"><summary>How uploads and Play now work</summary><div class="help-body"><p><strong>With Add to Up Next selected:</strong> media goes into the shared waiting queue when it is ready; current playback is not replaced.</p><p><strong>With it unticked:</strong> compatible video may start playing on the TV or speaker as it transfers. <strong>Audio always goes into Up Next</strong>, even when this option is unticked.</p><p>Transfers happen on the local network and may resume after a brief interruption. Keep this page open until the transfer has finished.</p></div></details>
</section>
<details id="linkAcquisition"><summary id="linkHeading">Add a YouTube or magnet link</summary>
<p id="linkAvailability" class="field-hint" role="status" aria-live="polite">Checking whether downloads are available…</p>
<form id="linkForm">
<label for="linkInput">YouTube video or magnet link</label>
<input id="linkInput" type="text" inputmode="url" maxlength="1500" autocomplete="off" spellcheck="false" placeholder="https://youtu.be/… or magnet:…" aria-describedby="linkAvailability" required>
<label class="toggle" for="linkAuthorised"><input id="linkAuthorised" type="checkbox" required><span>I have permission to download this media.</span></label>
<button id="linkSubmit" type="submit" disabled>Download and add to Up Next</button>
</form>
<p id="linkFeedback" class="field-hint" role="status" aria-live="polite"></p>
<section id="linkJobPanel" aria-labelledby="linkJobsHeading" hidden><h4 id="linkJobsHeading">Downloads</h4><ul id="linkJobs" aria-label="Room downloads"></ul></section>
</details>
<details class="help"><summary>What do the queue buttons mean?</summary><div class="help-body"><p><strong>Vote</strong> shows you want this item played; it does not automatically reorder the queue. <strong>Play now</strong> starts the item on the TV or speaker; <strong>Next</strong> moves it to be played after the current item.</p><p><strong>↑ / ↓</strong> move a waiting item earlier or later. <strong>×</strong> removes it from Up Next. <strong>Clear Up Next</strong> empties waiting items without stopping the currently playing item.</p><p>If someone else edits the queue at the same time, SmoothCast refreshes before letting you retry.</p></div></details>
</section>
<div class="home-grid">
<details class="home-card"><summary>In the room</summary><div id="homePeople" class="participants"></div><div class="quick-links"><a href="#peoplePanel">See everyone</a></div></details>
</div>
<details class="help"><summary>How the room works</summary><div class="help-body"><p><strong>1. Pick a device.</strong> SmoothCast plays on the TV or speaker selected above; use the playback controls to move it.</p><p><strong>2. Add media.</strong> Upload a file, paste a YouTube or magnet link, or find something already in the house. New items go to <strong>Up Next</strong> without interrupting what is playing.</p><p><strong>3. Share the room.</strong> Everyone here sees the same queue and can vote, reorder or remove waiting items. See who is here under <strong>In the room</strong>.</p></div></details>
<details id="castEntry" class="help"><summary id="castEntryHeading">Casting compatibility</summary><div class="help-body"><p>Use SmoothCast room controls to send media to the selected TV or speaker. Chrome’s own Cast button is not yet supported. If simultaneous Play now requests overlap, the first takes priority; other files go to Up Next.</p></div></details>
</section>

<p id="errorDash" role="status" aria-live="polite"></p>
<section id="findPanel" aria-labelledby="findHeading"><div class="find-intro"><h2 id="findHeading" tabindex="-1">Find something to play</h2><a href="#queuePanel">View Up Next</a></div>
<p class="section-desc">Search your house instantly, then discover YouTube or openly licensed torrent media.</p>
<div class="find-search">
<form id="findForm" role="search" aria-label="Search shared libraries">
<label for="findInput">Search films, shows, music and online sources</label><div class="find-field"><input id="findInput" type="search" placeholder="Title, artist, album or keyword" autocomplete="off" maxlength="200" enterkeyhint="search"><button id="findClear" type="button" class="secondary">Clear</button></div>
<div class="find-sources"><div class="find-source"><button type="submit" id="findSubmit">Search shared libraries</button><p class="field-hint">Searches your house as you type. Stays on your local network.</p></div><div class="find-source"><button id="youtubeSearch" type="button" class="secondary" aria-describedby="youtubeAvailability" disabled>Search YouTube</button><p id="youtubeAvailability" class="field-hint">Checking YouTube search availability…</p></div><div class="find-source"><button id="magnetSearch" type="button" class="secondary" disabled>Find open torrents</button><p id="magnetAvailability" class="field-hint">Checking Archive search availability…</p><label class="toggle"><input id="magnetAuto" type="checkbox"><span>Search open torrents as I type (sends terms to Internet Archive)</span></label></div></div>
</form>
<div id="findChips" role="group" aria-label="Filter search results"><button type="button" class="tiny secondary" data-kind="film" aria-pressed="false">Films</button><button type="button" class="tiny secondary" data-kind="show" aria-pressed="false">Shows</button><button type="button" class="tiny secondary" data-kind="music" aria-pressed="false">Music</button><button type="button" class="tiny secondary" data-kind="video" aria-pressed="false">Videos</button><button type="button" class="tiny secondary" data-available="1" aria-pressed="false">Available now</button></div>
</div>
<div class="find-results-head"><h3>Shared library results</h3><button id="findReset" class="tiny secondary" type="button" hidden>Reset filters</button></div>
<p id="findStatus" class="muted" role="status" aria-live="polite"></p><div id="findEmpty" class="empty"><strong>Find something you want to play</strong><p class="field-hint">Search by title or artist, select a media type, or browse the shared folders below.</p><div class="quick-links"><a href="#libraries" id="findBrowse">Browse shared libraries</a><a href="#uploadCard">Add your own files</a><a href="#linkAcquisition">Paste a video link</a></div></div><div id="findResults" aria-label="House search results"></div>
<section id="youtubeResultsPanel" aria-labelledby="youtubeResultsHeading" hidden><h3 id="youtubeResultsHeading">YouTube results</h3>
<p id="youtubeSearchStatus" role="status" aria-live="polite"></p><label class="toggle" for="youtubeAuthorised"><input id="youtubeAuthorised" type="checkbox"><span>I am authorised to download the selected media.</span></label>
<ul id="youtubeResults" class="find-list" aria-label="YouTube videos"></ul></section>
<section id="magnetResultsPanel" aria-labelledby="magnetResultsHeading" hidden><h3 id="magnetResultsHeading">Open torrents · Internet Archive</h3><p id="magnetSearchStatus" role="status" aria-live="polite"></p><label class="toggle"><input id="magnetAuthorised" type="checkbox"><span>I am authorised to download the selected media.</span></label><ul id="magnetResults" class="find-list" aria-label="Open torrent results"></ul></section>
<details id="libraries" class="help"><summary>Browse libraries on the network</summary><button id="libRefresh" type="button" class="tiny secondary">Refresh shared libraries</button><p id="libStatus" class="field-hint" role="status" aria-live="polite"></p><div id="libBody" class="muted">Loading libraries...</div></details>
<details class="help"><summary>How search and availability work</summary><div class="help-body"><p>Search finds films and music on the SmoothCast computers in your home. <strong>Available now</strong> limits results to items that can currently be reached; a computer that is switched off may come back later.</p><p>Use a house result to add it to Up Next, or select <strong>Search YouTube</strong> to send your query to YouTube. YouTube results are downloaded and checked before they enter Up Next. If you have a file on your own device, use <a href="#uploadCard">Add files in Queue</a> instead.</p></div></details>
</section>
<section id="peoplePanel" aria-labelledby="peopleHeading"><h2 id="peopleHeading">People in the room</h2>
<p class="section-desc">See who is connected. <a href="#advancedPanel">Change your name in Settings</a> or <a href="#localLivePanel">follow room activity</a>.</p>
<div id="people" class="participants"></div>
<details class="help"><summary>Who can see my name and actions?</summary><div class="help-body"><p>Your display name and activity such as joining, voting and queue changes can be seen by people in this shared room. Only you can change your display name.</p></div></details>
</section>
<section id="advancedPanel" aria-labelledby="roomSettingsHeading"><h2 id="roomSettingsHeading" tabindex="-1">Settings</h2><p>Personal browser preferences and shared room playback settings. Host policy and library folders are managed in desktop Preferences.</p>
<div class="advanced-grid">
<section aria-labelledby="profileHeading"><h3 id="profileHeading">Your profile</h3><form id="nameForm"><label for="displayName">Your display name</label><div class="actions"><input id="displayName" maxlength="40" autocomplete="nickname" required><button class="secondary" type="submit">Update name</button></div></form></section>
<section aria-labelledby="phoneHeading"><h3 id="phoneHeading">This browser only</h3>
<label class="toggle"><input id="lockControls" type="checkbox" checked><span><strong>Lock-screen controls</strong><span class="field-hint" style="display:block">Use play, pause and skip from your phone's lock screen or headphones while this page is open.</span></span></label>
<label class="toggle"><input id="keepScreenOn" type="checkbox"><span><strong>Keep screen on</strong><span class="field-hint" style="display:block">Ask your browser to keep the display awake while you use this remote. Your device may not support it.</span></span></label>
<p id="remoteDimHint" role="status" hidden>Your browser may still dim the screen. For an iPad on a stand, turn on Guided Access in its Settings to keep it awake.</p>
</section>
<section aria-labelledby="musicHeading"><h3 id="musicHeading">Shared room audio</h3>
<label class="toggle"><input id="musicAutogain" type="checkbox"><span><strong>Normalise audio-only tracks</strong><span class="field-hint" style="display:block">Reduce big volume differences between tracks. Existing programme or album normalisation takes precedence.</span></span></label>
<details class="help"><summary>Audio normalisation details</summary><div class="help-body"><p>Targets -16 LUFS with a -1.5 dBTP true-peak ceiling. This applies to music and other audio-only playback when the SmoothCast computer supports it.</p></div></details>
</section>
</div></section>
<section id="meshPanel" aria-labelledby="meshTitle"><h2 id="meshTitle" tabindex="-1">Mesh</h2><p class="section-desc">Live room and network activity, transfers, playback targets, connected computers and mesh health in one place.</p><p id="meshAvailability" class="field-hint" role="status">Checking mesh availability…</p><section id="localLivePanel" aria-labelledby="localLiveHeading"><h2 id="localLiveHeading" tabindex="-1">This room · live activity</h2><p class="section-desc">Local activity remains available even when the mesh service is offline.</p><div class="advanced-grid"><section aria-labelledby="livePlaybackHeading"><h3 id="livePlaybackHeading">Current playback</h3><p id="liveRoomTarget">TV or speaker status unavailable</p><p id="liveRoomPlayback">Playback state unavailable</p><div class="quick-links"><a href="#playback">Playback controls</a><a href="#queuePanel">Shared queue</a><a href="#uploadCard">Transfer monitor</a></div></section><section aria-label="Recent room activity"><h3 style="margin:18px 0 8px;font-size:1rem">Recent activity</h3><label for="activityFilter" class="muted">Show</label> <select id="activityFilter" aria-controls="activity"><option value="all">Everything</option><option value="playback">Playback</option><option value="queue">Up Next</option><option value="people">People</option><option value="problems">Problems</option></select><p id="activityEmpty" class="muted" hidden>Nothing here yet for this filter.</p><div id="activity" class="activity" role="log" aria-live="polite" aria-relevant="additions" aria-label="Room activity"></div></section><section aria-labelledby="peerHeading"><h3 id="peerHeading">Other SmoothCast computers</h3><p class="section-desc">Open another SmoothCast computer's room to switch to it. It has its own House PIN and settings; seeing it here does not give you access.</p><ul id="peers"><li class="empty">No other SmoothCast computers found</li></ul></section>
<section id="networkActivity" aria-labelledby="networkHeading"><h3 id="networkHeading">On your network</h3><p class="section-desc">Shows what is playing on other TVs and speakers in your home, updated every 15 seconds. Nothing here controls them.</p><p id="networkActivitySummary" class="muted" role="status" aria-live="polite">Looking for other TVs and speakers…</p><ul id="networkActivityRows"><li>Nothing is playing on other TVs or speakers</li></ul></section>
</div></section><!--SC_MESH_DETAILS--></section></div>
<dialog id="shortcutsHelp" aria-labelledby="shortcutsHeading"><h2 id="shortcutsHeading">Keyboard shortcuts</h2><p>Available when you are not typing in a field.</p><ul id="shortcutsList"></ul><button id="shortcutsClose" type="button">Close</button></dialog></main>
<script>
const PAGE_BUILD="__SC_BUILD__",CLIENT_SCHEMA=Number("__SC_SCHEMA__");
const SHORTCUTS=typeof __SC_SHORTCUTS__==="undefined"?[]:__SC_SHORTCUTS__,shortcutMap=new Map(SHORTCUTS.map(entry=>[entry.key,entry]));
let stalePage=false,shortcutState=null;
function showUpdateNotice(){
  stalePage=true;
  stopPlayhead();
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

async function post(path,body){
  if(stalePage)throw Error("Reload required");
  // A missing action response must not indefinitely block every room control.
  const controller=path==="/api/action"?new AbortController():null;
  const deadline=controller?setTimeout(()=>controller.abort(),10000):null;
  try{
    const r=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf,...clientHeaders},body:JSON.stringify(body),...(controller?{signal:controller.signal}:{})});
    const d=await r.json();
    if(d.code==="client_reload_required"){showUpdateNotice();throw Error(d.error||"Reload required")}
    if(r.status===429){const retryAfter=Math.max(1,Number(r.headers.get("Retry-After"))||1);rateDelayUntil=Date.now()+retryAfter*1000;throw Object.assign(Error("Too many controls at once. Try again shortly."),{status:429,retryAfter})}
    if(!r.ok)throw Error(d.error||"Request failed");
    return d;
  }catch(error){
    if(controller?.signal.aborted)throw Error("Command response timed out; playback may have changed. Check Now Playing before retrying.");
    throw error;
  }finally{if(deadline!==null)clearTimeout(deadline)}
}
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
  stopPlayhead();playhead=null;
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
let playhead=null,paintedAt=-1,playheadTimer=null;
function stopPlayhead(){if(playheadTimer!==null){clearTimeout(playheadTimer);playheadTimer=null}}
function schedulePlayhead(){
  if(playheadTimer!==null||!playhead||document.hidden||!csrf||stalePage||playhead.s.state!=="PLAYING")return;
  const duration=Number(playhead.s.duration)||0;
  if(duration>0&&paintedAt>=duration)return;
  playheadTimer=setTimeout(()=>{playheadTimer=null;if(document.hidden||!csrf||stalePage)return;paintPlayhead();schedulePlayhead()},200);
}
function trackPlayhead(s){stopPlayhead();playhead={s,age:Number(s.snapshot_age_ms)||0,at:performance.now()};paintedAt=-1;paintPlayhead();schedulePlayhead()}
function paintPlayhead(){if(!playhead)return;const pos=projectPosition(playhead.s,playhead.age,performance.now()-playhead.at);const dur=Number(playhead.s.duration)||0;if(Math.abs(pos-paintedAt)<0.2&&!(dur>0&&pos>=dur&&paintedAt<dur))return;paintedAt=pos;$("progress").value=Math.min(pos,dur||pos);if(!editingControls.has("seek")){$("elapsed").textContent=clock(pos);$("seek").value=Math.min(pos,dur||pos)}}
let queueRenderKey=null,queuePressed=false,deferredQueue=null,queueState=[],queueLimit=100;
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
  if(pending)renderQueue(pending.rows,pending.revision);
}
// Click follows pointerup, so retain the pressed button until its click runs.
document.addEventListener("pointerup",()=>setTimeout(releaseQueuePointer,0));
document.addEventListener("pointercancel",releaseQueuePointer);
function mediaKindLabel(kind){return kind==="audio"?"Audio":kind==="video"?"Video":""}
function renderQueue(items,revision=queueRevision){
  const queue=queueElement,rows=Array.isArray(items)?items:[];
  if(queuePressed){deferredQueue={rows,revision};return}
  queueRevision=revision;
  queueState=rows;
  const key=queueLimit+JSON.stringify(rows.map(item=>[
    item.id,item.title,item.duration,item.votes,item.voted,item.contributor,item.source_kind,item.media_kind,
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
  }else rows.slice(0,queueLimit).forEach((item,index)=>{
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
      +(mediaKindLabel(item.media_kind)?" · "+mediaKindLabel(item.media_kind):"")
      +(item.duration?" · "+clock(item.duration):"")
      +" · "+(item.contributor?"Added by "+item.contributor:"Contributor not recorded")
      +({upload:" · File upload",library:" · Shared library",link:" · Link download",local:" · Local media"}[item.source_kind]||"");
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
  if(rows.length>queueLimit){
    const more=document.createElement("li"),button=document.createElement("button");
    more.className="queue-more";
    button.type="button";
    button.className="secondary";
    button.dataset.queueMore="1";
    button.textContent="Show "+Math.min(100,rows.length-queueLimit)+" more of "+(rows.length-queueLimit)+" remaining";
    button.addEventListener("click",()=>{
      queueLimit+=100;
      queueRenderKey=null;
      renderQueue(queueState,queueRevision);
      queueElement.querySelectorAll("[data-queue-id]")[queueLimit-100]?.querySelector("button")?.focus();
      $("queueFeedback").textContent="Showing "+Math.min(queueLimit,queueState.length)+" of "+queueState.length+" Up Next items.";
    });
    more.append(button);
    nodes.push(more);
  }
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
  function stop(){
    env.clearTimeout(retry);retry=null;env.clearInterval(watch);watch=null;
    const previous=source;source=null;healthy=false;
    if(previous)previous.close();
  }
  function fail(es){
    // Late callbacks from a closed connection cannot tear down its replacement.
    if(source!==es)return;
    stop();if(!env.canRun())return;
    env.fallback();retry=env.setTimeout(start,delays[Math.min(failures++,4)]);
  }
  function start(){
    if(!env.EventSource||source||!env.canRun())return;
    env.clearTimeout(retry);retry=null;
    const es=new env.EventSource("/api/events");source=es;last=env.now();
    es.addEventListener("state",e=>{
      if(source!==es||!env.canRun())return;
      let d;try{d=JSON.parse(e.data)}catch(_){return}
      if(!d||typeof d.state!=="object"||!d.state)return;
      // Healthy means the frame was usable, not just that bytes arrived.
      try{if(env.apply(d)===false){stop();return}}catch(_){fail(es);return}
      if(source!==es)return;
      last=env.now();healthy=true;failures=0;
    });
    es.onerror=()=>fail(es);
    watch=env.setInterval(()=>{if(source===es&&env.now()-last>30000)fail(es)},5000);
  }
  return {start,stop,healthy:()=>healthy};
}
const roomEvents=makeRoomEvents({
  EventSource:typeof EventSource==="function"?EventSource:null,
  apply:d=>applyStatus(d),
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
  if(state==="PLAYING"||state==="BUFFERING")return ["Pause","Pause playback on the TV or speaker for everyone"];
  if(state==="PAUSED")return ["Resume","Resume playback on the TV or speaker for everyone"];
  return ["Play / pause","Toggle playback on the TV or speaker for everyone"];
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
  if(entering)$("dashboard").hidden=false;
  if($("uploadCard").hidden)$("uploadCard").hidden=false;
  if(entering)$("homeHeading").focus({preventScroll:true});
}
const linkForm=$("linkForm");
let linkCapabilities={},linkOwnerEnabled=null,linkLocalPrerequisites=null,linkStorageAvailable=null,linkPosting=false,linkAttempt=null,linkSignature="",youtubeSearchBusy=false;
const linkShortcut=$("openLinkAcquisition");
function openLinkAcquisition(){const panel=$("linkAcquisition");if(panel)panel.open=true}
if(linkShortcut)linkShortcut.addEventListener("click",()=>{openLinkAcquisition();$("linkInput").focus()});
function focusContributionControl(id){
  const control=$(id);
  if(control&&!control.disabled)control.focus({preventScroll:true});
}
$("openUploadEntry").addEventListener("click",()=>focusContributionControl("videoFile"));
$("openFindEntry").addEventListener("click",()=>focusContributionControl("findInput"));
document.querySelectorAll("[data-home-link]").forEach(link=>link.addEventListener("click",()=>{
  openLinkAcquisition();
  const input=$("linkInput");
  if(input)setTimeout(()=>input.focus({preventScroll:true}),0);
}));
if(location.hash==="#linkAcquisition")openLinkAcquisition();
window.addEventListener("hashchange",()=>{if(location.hash==="#linkAcquisition")openLinkAcquisition()});
function updateLinkControls(){
  function linkWorkerExplanation(kind){
    const owner=typeof linkOwnerEnabled==="undefined"?null:linkOwnerEnabled;
    const prerequisites=typeof linkLocalPrerequisites==="undefined"?null:linkLocalPrerequisites;
    if(owner?.[kind]===false)return "Ask the host to enable guest downloads in desktop Preferences → Queue.";
    const local=prerequisites?.[kind],missing=[];
    if(local?.engine===false)missing.push(kind==="youtube"?"yt-dlp":"aria2c");
    if(local?.probe===false)missing.push("FFprobe");
    if(local?.isolation===false)missing.push("isolated worker launcher");
    if(missing.length)return "No eligible worker is currently available. Host prerequisites missing at startup: "+missing.join(", ")+". Ask the host to check desktop Preferences → Queue and restart after repair.";
    return "Ask the host to check the acquisition worker in desktop Preferences → Queue. You can keep the link here.";
  }
  const search=$("youtubeSearch"),availability=$("youtubeAvailability");
  if(search&&availability){
    const ready=linkCapabilities.youtube_search??linkCapabilities.youtube;
    search.disabled=!ready||youtubeSearchBusy;
    availability.textContent=ready?"Search YouTube explicitly; your house search stays local.":"YouTube search is unavailable. "+linkWorkerExplanation("youtube");
  }
  const magnetSearch=$("magnetSearch"),magnetAvailability=$("magnetAvailability");
  if(magnetSearch&&magnetAvailability){
    magnetSearch.disabled=!linkCapabilities.magnet_search;
    magnetAvailability.textContent=linkCapabilities.magnet_search?"Openly licensed Archive media; ranked by title and downloads.":"Archive search needs a qualified local torrent worker and curl.";
  }
  const input=$("linkInput"),consent=$("linkAuthorised"),button=$("linkSubmit"),label=$("linkAvailability");
  if(!input||!consent||!button||!label)return false;
  const value=String(input.value||"").trim();
  // Advisory preflight only; the server remains the validation/policy authority.
  function classify(text){
    const fail=message=>({kind:null,message});
    if(!text)return {kind:null,message:""};
    if(text.length>1500)return fail("This link is too long. Copy the video's share link instead.");
    if(/[\s\x00-\x1f\x7f]/.test(text))return fail("Paste just one link, without surrounding text or spaces. For a title, use Find.");
    const queryValues=(query,key)=>{
      const fields=query.split("&");
      if(fields.length>80)throw Error("Too many link parameters");
      return fields.filter(Boolean).map(field=>{
        const i=field.indexOf("="),decode=x=>decodeURIComponent(x.replace(/\+/g," "));
        return i<0?[decode(field),""]:[decode(field.slice(0,i)),decode(field.slice(i+1))];
      }).filter(pair=>pair[0]===key&&pair[1]).map(pair=>pair[1]);
    };
    try{
      if(/^magnet:/i.test(text)){
        const match=/^magnet:\?([^#]+)$/.exec(text);
        if(match){
          const xt=queryValues(match[1],"xt");
          if(xt.length===1&&/^urn:btih:(?:[0-9a-f]{40}|[a-z2-7]{32})$/i.test(xt[0]))return {kind:"magnet"};
        }
        return fail("This magnet is incomplete or unsupported. Copy a single BitTorrent v1 magnet from its source.");
      }
      const match=/^https:\/\/([^/?#]+)([^?#]*)(?:\?([^#]*))?(?:#.*)?$/.exec(text);
      if(match){
        const host=match[1].toLowerCase().replace(/:443$/,""),path=match[2],query=match[3]||"";
        const youtube=["youtube.com","www.youtube.com","m.youtube.com","youtu.be"].includes(host);
        if(youtube){
          const ids=path==="/watch"&&host!=="youtu.be"?queryValues(query,"v"):[host==="youtu.be"?path.slice(1):path.startsWith("/shorts/")?path.slice(8):""];
          if(ids.length===1&&/^[A-Za-z0-9_-]{11}$/.test(ids[0]))return {kind:"youtube"};
          return fail("Choose one YouTube video or Short, then copy its Share link. Channel and playlist links are not supported.");
        }
        return fail("This website is not supported for downloads here. Use a YouTube video, magnet link, shared library or a file from your device.");
      }
      if(/^http:\/\//i.test(text))return fail("Use the secure HTTPS Share link from the video page.");
      if(/^(?:www\.)?(?:youtube\.com|youtu\.be)\//i.test(text))return fail("Copy the complete YouTube Share link, including https://.");
      return fail("Looking for a title? Use Find. To add a download, paste a YouTube video or magnet link.");
    }catch(_){return fail("The link contains invalid parameters. Copy a fresh Share link and try again.")}
  }
  const intent=classify(value),kind=intent.kind;
  const sourceName=kind==="youtube"?"YouTube":"BitTorrent magnets";
  const sources=[linkCapabilities.youtube?"YouTube":null,linkCapabilities.magnet?"BitTorrent magnets":null].filter(Boolean);
  const allowed=!!(kind&&linkCapabilities[kind]&&linkStorageAvailable!==false);
  input.disabled=linkPosting;consent.disabled=linkPosting;
  button.disabled=!allowed||linkPosting||!consent.checked;
  button.textContent=linkPosting?"Submitting…":kind==="youtube"?"Add YouTube video to Up Next":kind==="magnet"?"Add torrent media to Up Next":"Download and add to Up Next";
  if(linkStorageAvailable===false){
    label.textContent="Download storage is busy or unavailable. Ask whoever runs SmoothCast to check it and restart the room. Existing media is preserved.";
  }else if(value&&!kind){
    label.textContent=intent.message;
  }else if(kind&&!allowed){
    label.textContent=sourceName+" unavailable in this room. "+linkWorkerExplanation(kind);
  }else if(kind){
    label.textContent=sourceName+" recognised. "+(consent.checked?"Ready to request download; playback will not be interrupted.":"Confirm permission to download and add to Up Next.");
  }else{
    label.textContent=sources.length?"Available: "+sources.join(" and ")+".":"Downloads are not ready. Ask the host to enable or check the acquisition worker in desktop Preferences → Queue. You can still add files or use shared libraries.";
  }
  return !button.disabled;
}
function renderLinkJobs(state){
  linkCapabilities={...(state.link_capabilities||{}),youtube_search:state.link_search_available,magnet_search:state.magnet_search_available};
  linkOwnerEnabled=state.link_owner_enabled||null;
  linkLocalPrerequisites=state.link_local_prerequisites||null;
  linkStorageAvailable=state.link_storage_available;
  updateLinkControls();
  const list=$("linkJobs");if(!list||typeof list.replaceChildren!=="function")return;
  const jobs=Array.isArray(state.link_jobs)?state.link_jobs.slice(-24):[];
  const panel=$("linkJobPanel");if(panel)panel.hidden=!jobs.length;
  const signature=JSON.stringify(jobs);
  if(signature===linkSignature)return;linkSignature=signature;
  const stages={pending:"Waiting to start",resolving:"Resolving source / torrent metadata",downloading:"Downloading",verifying:"Checking completed media",queueing:"Submitting to Up Next",ready:"Added to Up Next",failed:"Failed",cancelled:"Cancelled",delivery_uncertain:"Queue acceptance uncertain — check Up Next"};
  // Progress-only snapshots must not destroy a focused or pending action.
  const previous=new Map(Array.from(list.children,row=>[row.dataset.linkJobId,row]));
  // Open for a newly active job, not every progress snapshot. Respect a
  // guest who closes the disclosure while a download continues.
  const active=stage=>["pending","resolving","downloading","verifying","queueing"].includes(stage);
  if(jobs.some(job=>active(job.stage)&&!active(previous.get(String(job.id))?.dataset.linkJobStage)))openLinkAcquisition();
  jobs.slice().reverse().forEach((job,index)=>{
    const id=String(job.id);
    let row=previous.get(id);
    if(!row){
      row=document.createElement("li");row.dataset.linkJobId=id;
      const heading=document.createElement("strong"),detail=document.createElement("p");
      detail.className="muted";
      const meter=document.createElement("progress"),stats=document.createElement("p"),error=document.createElement("p");
      meter.setAttribute("aria-label","Download progress");
      stats.className=error.className="field-hint";
      const action=(verb,success)=>{
        const button=document.createElement("button");
        button.type="button";button.className="secondary tiny";button.textContent=verb==="cancel"?"Cancel download":"Retry download";
        button.addEventListener("click",async()=>{
          if(button.disabled||button.hidden)return;
          button.disabled=true;
          try{const reply=await post("/api/link-jobs/"+verb,{id});showError("linkFeedback",reply.message||success);void refresh()}
          catch(error){showError("linkFeedback",error.message);button.disabled=false}
        });
        return button;
      };
      row.append(heading,detail,meter,stats,error,action("cancel","Cancellation requested"),action("retry","Retry accepted"));
    }
    previous.delete(id);
    row.dataset.linkJobStage=job.stage;
    const [heading,detail,meter,stats,error,cancel,retry]=row.children;
    const setText=(node,value)=>{if(node.textContent!==value)node.textContent=value};
    setText(heading,job.title||"Download");
    const sourceLabel=job.kind==="youtube"?"YouTube":job.kind==="magnet"?"BitTorrent magnet":"Link";
    setText(detail,sourceLabel+" · "+(stages[job.stage]||"State unavailable")+" · "+(job.executor||"Executor unknown"));
    const received=Number.isSafeInteger(job.received)&&job.received>=0?job.received:null;
    const total=Number.isSafeInteger(job.total)&&job.total>0?job.total:null;
    const progressing=job.stage==="downloading"||job.stage==="resolving";
    meter.hidden=stats.hidden=!progressing;
    if(progressing){
      if(received!==null&&total!==null&&received<=total){
        if(meter.max!==total)meter.max=total;
        if(!meter.hasAttribute("value")||meter.value!==received)meter.value=received;
      }else if(meter.hasAttribute("value"))meter.removeAttribute("value");
      const rate=Number.isFinite(job.rate)&&job.rate>0?job.rate:null;
      setText(stats,(received===null?"Waiting for progress":fileUnits(received)+(total===null?" reported":(" / "+fileUnits(total))))+(rate===null?"":" · "+fileUnits(rate)+"/s")+(rate!==null&&received!==null&&total!==null&&total>=received?" · approx. "+clock((total-received)/rate)+" remaining":""));
    }
    error.hidden=!job.error;setText(error,job.error||"");
    for(const [button,allowed,verb] of [[cancel,job.can_cancel,"Cancel"],[retry,job.can_retry,"Retry"]]){
      button.hidden=!allowed;
      if(!allowed)button.disabled=false;
      const label=verb+" "+(job.title||"acquisition");
      if(button.getAttribute("aria-label")!==label)button.setAttribute("aria-label",label);
    }
    const current=list.children[index]||null;
    if(current!==row)list.insertBefore(row,current);
  });
  for(const row of previous.values())row.remove();
}
if(linkForm&&typeof linkForm.addEventListener==="function"){
  $("linkInput").addEventListener("input",updateLinkControls);
  $("linkAuthorised").addEventListener("change",updateLinkControls);
  linkForm.addEventListener("submit",async event=>{
    event.preventDefault();if(!updateLinkControls())return;
    const url=$("linkInput").value.trim();if(!url)return;
    if(!linkAttempt||linkAttempt.url!==url)linkAttempt={url,id:"link-"+Date.now()+"-"+Math.random().toString(36).slice(2)};
    linkPosting=true;updateLinkControls();showError("linkFeedback","Sending to the SmoothCast computer…");
    try{
      const result=await post("/api/link-jobs",{url,request_id:linkAttempt.id,authorised:true});
      $("linkInput").value="";$("linkAuthorised").checked=false;linkAttempt=null;
      showError("linkFeedback",result.message||"Download accepted");void refresh();
    }catch(error){showError("linkFeedback",error.message)}
    finally{linkPosting=false;updateLinkControls()}
  });
}
let libraryCopySignature="";
function renderLibraryCopies(state){
  const list=$("libraryCopyRows");if(!list)return;
  const rows=Array.isArray(state.library_copies)?state.library_copies.slice(-24).reverse():null;
  const panel=$("libraryCopiesPanel");if(panel)panel.hidden=!rows?.length;
  const signature=JSON.stringify(rows);if(signature===libraryCopySignature)return;libraryCopySignature=signature;
  if(!rows||!rows.length){list.replaceChildren();return}
  const labels={copying:"Copying and verifying media",ready:"Queue accepted",failed:"Copy failed — try again from Find",cancelled:"Cancelled",uncertain:"Queue acceptance uncertain — check Up Next"};
  list.replaceChildren(...rows.map(row=>{
    const li=document.createElement("li"),title=document.createElement("strong"),detail=document.createElement("p");
    title.textContent=row.title||"Shared media";
    detail.className="field-hint";
    detail.textContent=[labels[row.stage]||"Unknown status",row.origin?"Requested from "+row.origin:"",row.contributor?"Added by "+row.contributor:""].filter(Boolean).join(" · ");
    li.append(title,detail);return li;
  }));
}
let roomTransferSignature=null;
function renderRoomTransfers(state){
  const rows=Array.isArray(state.room_transfers)?state.room_transfers.slice(0,24):[];
  const signature=JSON.stringify(rows);
  if(signature===roomTransferSignature)return;roomTransferSignature=signature;
  const labels={receiving:"Receiving",buffering:"Buffering / playback requested",verifying:"Checking media",submitting:"Submitting room action",awaiting_acceptance:"Awaiting room acceptance"};
  for(const [panelId,listId] of [["queueIncomingPanel","queueIncomingRows"]]){
    const panel=$(panelId),list=$(listId);if(!panel||!list)continue;
    if(panel.hidden!==!rows.length)panel.hidden=!rows.length;
    // Reuse stable rows so chunk ACKs do not rebuild the entire list,
    // interrupt assistive technology or disturb the user's scroll position.
    const previous=new Map(Array.from(list.children,li=>[li.dataset.transferId,li]));
    rows.forEach((row,index)=>{
      const id=String(row.id);
      let li=previous.get(id);
      if(!li){
        li=document.createElement("li");li.dataset.transferId=id;
        const detail=document.createElement("p");detail.className="field-hint";
        li.append(document.createElement("strong"),detail,document.createElement("progress"));
      }
      previous.delete(id);
      const [title,detail,meter]=li.children;
      const name=row.title||"Incoming media";
      const description=[row.batch_total>1?"File "+row.batch_index+" of "+row.batch_total:"",mediaKindLabel(row.media_kind),row.intent==="queue"?"Up Next":"Play now",labels[row.stage]||"Receiving",fileUnits(row.received)+" / "+fileUnits(row.size)].filter(Boolean).join(" · ");
      if(title.textContent!==name){title.textContent=name;meter.setAttribute("aria-label","Transfer progress for "+name);}
      if(detail.textContent!==description)detail.textContent=description;
      const total=Math.max(1,Number(row.size)||1),received=Math.max(0,Math.min(total,Number(row.received)||0));
      if(meter.max!==total)meter.max=total;
      if(meter.value!==received)meter.value=received;
      const current=list.children[index]||null;
      if(current!==li)list.insertBefore(li,current);
    });
    for(const li of previous.values())li.remove();
  }
}
function playbackFeedback(state){
  const feedback=state.cast_feedback;
  if(feedback&&feedback.receiver===state.receiver&&typeof feedback.message==="string"){
    if(feedback.state==="failed")return "Cast failed: "+feedback.message;
    if(feedback.state==="cancelled")return feedback.message;
    if(feedback.state==="preparing"&&state.busy)return feedback.message;
  }
  return "";
}
function quickCastDestinationCopy(receiver){
  return receiver?"Selected receiver: "+receiver+". SmoothCast checks availability before sending any file.":
    "No room receiver selected. You can still add media to Up Next.";
}
function renderQueueDestination(state){
  const quickStatus=$("quickCastStatus"),quickCopy=quickCastDestinationCopy(state.receiver);
  if(quickStatus&&quickStatus.textContent!==quickCopy)quickStatus.textContent=quickCopy;
  const mesh=$("queueMeshLink");
  const target=state.receiver||"No casting target selected";
  const playing=playbackFeedback(state)||(state.state_label||"Playback state unavailable")+(state.active&&state.title?" · "+state.title:"");
  const liveTarget=$("liveRoomTarget"),livePlayback=$("liveRoomPlayback");
  if(liveTarget)liveTarget.textContent=target;
  if(livePlayback)livePlayback.textContent=playing;
  // The mesh panel owns visibility. Never infer remote readiness from room selection.
  if(mesh){const details=$("meshDetails");mesh.hidden=!details||details.hidden;}
}
let networkActivityKey=null;
function renderNetworkActivity(entries){
  const streams=Array.isArray(entries)?entries:[],activityRows=$("networkActivityRows");
  const signature=JSON.stringify(streams.map(item=>[item.title,item.receiver,item.protocol,item.state,item.position,item.duration,item.is_local]));
  if(signature===networkActivityKey)return;networkActivityKey=signature;
  activityRows.replaceChildren();$("networkActivitySummary").textContent=streams.length?`${streams.length} active stream${streams.length===1?"":"s"} on reachable receivers`:"Nothing is playing on other TVs or speakers";if(!streams.length){const li=document.createElement("li");li.textContent="When someone starts casting on this network, it appears here. Unreachable receivers are omitted.";activityRows.append(li)}else for(const item of streams){const li=document.createElement("li"),title=document.createElement("strong"),detail=document.createElement("span");title.textContent=item.title||"Media title unavailable";detail.className="muted";const timing=item.position==null?"":` · ${clock(item.position)}${item.duration==null?"":` / ${clock(item.duration)}`}`;detail.textContent=`${item.receiver||"Unknown receiver"} · ${item.protocol||"Receiver"} · ${item.state||"ACTIVE"}${timing}${item.is_local?" · This SmoothCast":""}`;li.replaceChildren(title,document.createElement("br"),detail);activityRows.append(li)}
}
function renderSharedQueue(s){
  const revision=Number.isSafeInteger(s.queue_revision)?s.queue_revision:0;
  renderQueue(s.queue,revision);
  const qTotal=Number.isSafeInteger(s.queue_total)&&s.queue&&s.queue_total>s.queue.length?s.queue_total:0;
  $("queueCount").textContent=s.queue&&s.queue.length?(qTotal?`${s.queue.length} of ${qTotal} shown`:`${s.queue.length} waiting`):"";$("clearQueue").disabled=!s.queue||!s.queue.length;
}
function applyStatus(d){
  if(!matchingBuild(d))return false;
  if(!acceptRoomSnapshot(d))return true;
    const s=d.state||{};
    // Queue and contribution progress are independent of pending transport commands.
    // Do not discard their SSE snapshots while a control is awaiting acknowledgement.
    renderSharedQueue(s);renderRoomTransfers(s);renderLibraryCopies(s);renderLinkJobs(s);
    // Mesh and room observations are read-only and must remain live during a
    // pending local playback command, just like the shared contribution queue.
    renderRoom(s.room);renderPeers(s.peers,s.peer_discovery_available);
    window.scRenderMeshRoom&&window.scRenderMeshRoom(s);renderNetworkActivity(s.network_activity);
    if(busy)return true;
    applyAccentPreset(s.accent);shortcutState=s;renderExtraTransport(s);
    renderPlaybackToggle(s.state);
    document.querySelectorAll("[data-action]").forEach(b=>{
      const action=b.dataset.action;
      const allowed=action==="stop"?s.can_stop:action==="play_pause"?s.can_play_pause:undefined;
      b.disabled=typeof allowed==="boolean"?!allowed:!!s.busy||!s.active;
    });
    monitorText("state",playbackFeedback(s)||(!s.active&&s.preparing?"Preparing playback":s.state_label||"State unavailable"));
    monitorText("title",s.active?(s.title||"Media title unavailable"):s.preparing?"Preparing playback…":"Nothing playing");
    {const d=$("nowDetails"),t=s.active&&typeof s.media_details==="string"?s.media_details:"";if(d){d.textContent=t;d.hidden=!t}}
    monitorText("receiver","Playing on: "+(s.receiver||"—")+(s.active&&mediaKindLabel(s.media_kind)?" · "+mediaKindLabel(s.media_kind):""));
    // Optional lock-screen integration must not prevent core room controls.
    try{syncMediaSession(s)}catch(_){}monitorText("transferRoomState",(s.receiver||"No TV or speaker chosen")+" · "+(s.state_label||"State unavailable"));
const duration=Number(s.duration)||0,position=Number(s.position)||0;$("progress").max=duration||1;$("progress").value=Math.min(position,duration||position);if(!editingControls.has("seek")){$("seek").max=duration||1;$("seek").value=Math.min(position,duration||position);$("seek").disabled=!s.can_seek||!duration;$("elapsed").textContent=clock(position);}$("duration").textContent=clock(duration);trackPlayhead(s);if(!editingControls.has("volume")){$("volume").disabled=s.volume==null;$("volume").value=s.volume||0;$("volumeText").textContent=s.volume==null?"Volume unavailable":`${s.volume}%`;}
$("musicAutogain").checked=!!s.music_autogain;
renderQueueDestination(s);
window.scRenderScreens&&window.scRenderScreens(s);
if(statusFailures)showError("errorDash","");
statusFailures=0;showJoinedRoom();
  return true;
}
let homePeopleKey=null;
function renderHomePeople(room){
  const host=$("homePeople");if(!host)return;
  const participants=Array.isArray(room?.participants)?room.participants:[];
  const signature=JSON.stringify([room?.me?.id,participants.map(person=>[person.id,person.name,person.color,person.online])]);
  if(signature===homePeopleKey)return;homePeopleKey=signature;
  if(!participants.length){const empty=document.createElement("span");empty.className="muted";empty.textContent="Just you so far.";host.replaceChildren(empty);return}
  host.replaceChildren(...participants.map(person=>{
    const chip=document.createElement("span");chip.className="person"+(person.online?"":" offline");
    const avatar=document.createElement("span");avatar.className="avatar";avatar.style.background=person.color;avatar.textContent=initials(person.name);
    const name=document.createElement("span");name.textContent=person.name+(room.me&&room.me.id===person.id?" (you)":"");
    chip.append(avatar,name);return chip;
  }));
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
let lastRoom=null,participantRenderKey=null;
function renderRoom(room){lastRoom=room;renderHomePeople(room);const people=$("people");const participants=Array.isArray(room?.participants)?room.participants:[];
const signature=JSON.stringify([room?.me?.id,participants.map(person=>[person.id,person.name,person.color,person.online])]);
if(signature!==participantRenderKey){participantRenderKey=signature;people.replaceChildren();for(const person of participants){const chip=document.createElement("span");chip.className="person"+(person.online?"":" offline");const avatar=document.createElement("span");avatar.className="avatar";avatar.style.background=person.color;avatar.textContent=initials(person.name);const name=document.createElement("span");name.textContent=person.name+(room.me&&room.me.id===person.id?" (you)":"");chip.append(avatar,name);people.append(chip)}}const activity=$("activity");if(room&&room.activity){const filter=$("activityFilter").value,events=[...room.activity].filter(e=>activityMatches(e,filter)).slice(-12);$("activityEmpty").hidden=events.length>0||!room.activity.length;const keep=new Set(events.map(e=>e.seq));for(const [seq,line] of activityLines)if(!keep.has(seq)){line.remove();activityLines.delete(seq)}for(const event of events){let line=activityLines.get(event.seq);if(!line){line=document.createElement("div");line.className="ev";const time=document.createElement("time"),text=document.createElement("span");text.textContent=describe(event);line.append(time,text);activityLines.set(event.seq,line)}const time=line.firstChild;time.textContent=ago(event.at);time.title=new Date(event.at*1000).toLocaleString()}[...events].reverse().forEach((event,index)=>{const line=activityLines.get(event.seq);if(activity.children[index]!==line)activity.insertBefore(line,activity.children[index]||null)})}}
$("activityFilter").addEventListener("change",()=>{if(lastRoom)renderRoom(lastRoom)});
function renderPeers(peers,available){
  const list=$("peers");
  const entries=available&&Array.isArray(peers)?peers:[];
  const focused=document.activeElement;
  if(!entries.length){
    const message=available?"No other SmoothCast computers found":"Peer discovery is unavailable on this network";
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

const extraTransportClient="transport-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2);
let extraTransportSequence=0;
function extraTransportEnvelope(action,state,seek,volume){
  if(!["seek_back","seek_forward","mute"].includes(action)||!state||
    typeof state.session_id!=="string"||!/^[a-f0-9]{32}$/.test(state.session_id)||
    !Number.isSafeInteger(state.revision)||state.revision<0)return null;
  if(action!=="mute"&&!Number.isFinite(seek))return null;
  const command=shortcutCommand(action,state,seek,volume);
  if(!command)return null;
  return {action:command.action,client_id:extraTransportClient,command_id:"control-"+(++extraTransportSequence),
    expected_session_id:state.session_id,expected_revision:state.revision,
    payload:command.value===undefined?{}:{value:command.value}};
}
const extraTransportControls=[["seekBackTen","seek_back"],["seekForwardTen","seek_forward"],["toggleMute","mute"]];
function renderExtraTransport(state){
  const valid=state&&typeof state.session_id==="string"&&/^[a-f0-9]{32}$/.test(state.session_id)&&
    Number.isSafeInteger(state.revision)&&state.revision>=0;
  for(const [id,action] of extraTransportControls){
    const button=$(id);if(button)button.disabled=!valid||!shortcutCommand(action,state,0,0);
  }
}
for(const [id,action] of extraTransportControls){
  $(id)?.addEventListener("click",()=>{
    if(busy||stalePage||!csrf||editingControls.has("seek"))return;
    const command=extraTransportEnvelope(action,shortcutState,Number($("seek").value),Number($("volume").value));
    if(!command)return;
    const {action:transportAction,...envelope}=command;
    void act(transportAction,undefined,envelope);
  });
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
    showError($("dashboard").hidden?"error":"errorDash","This shortcut is unavailable until the room and the TV or speaker are ready.");
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
  // A delayed positional edit must retain the revision on which it was made.
  if(["queue_remove","queue_move","queue_next","queue_clear"].includes(action)&&extra.queue_revision===undefined){
    extra={...extra,queue_revision:queueRevision};
  }
  if(busy){
    // Stop supersedes waiting playback changes, not unrelated queue edits.
    if(action==="stop")for(const [key,pending] of pendingControls){
      if(["queue_play","play_pause","seek","next","previous"].includes(pending.action))pendingControls.delete(key);
    }
    const key=action+":"+(extra.id||"");
    if(action!=="stop"&&!pendingControls.has(key)&&pendingControls.size>=16){
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
  showError("errorDash",action==="stop"?"Requesting Stop…":action==="queue_play"?"Requesting playback…":"Sending command…");
  statusRequest?.abort("superseded");
  try{
    const body={action,...extra};
    if(["queue_remove","queue_move","queue_next","queue_clear"].includes(action)){
      body.queue_revision=extra.queue_revision;
      body.queue_command_id="q"+Date.now().toString(36)+"-"+(++queueCommandSeq).toString(36);
    }
    if(value!==undefined)body.value=value;
    const result=await post("/api/action",body);
    showError("errorDash",result.message||"Command accepted");
    if(action.startsWith("queue_"))$("queueFeedback").textContent=result.message||"Queue change accepted; updating the list…";
  }catch(err){showError("errorDash",err.message);if(action.startsWith("queue_"))$("queueFeedback").textContent="Queue action was not applied: "+err.message;}
  finally{
    busy=false;
    if(pendingControls.size&&csrf&&!stalePage){
      const first=pendingControls.has("stop:")?"stop:":pendingControls.keys().next().value;
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
function monitorText(id,value){const node=$(id),text=String(value);if(node&&node.textContent!==text)node.textContent=text;}
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
    let lastProgressPaint=-Infinity;
    xhr.upload.onprogress=event=>{
      const total=event.lengthComputable?event.total:options.body.size;
      const done=event.lengthComputable&&event.loaded===event.total;
      const now=performance.now();
      // Sender progress is diagnostic only; bound DOM writes to 10 Hz
      // without slowing network transfer or suppressing the last event.
      if(!done&&now-lastProgressPaint<100)return;
      lastProgressPaint=now;
      monitorText("transferInFlight",fileUnits(event.loaded)+" of "+fileUnits(total)+" (not yet confirmed)");
      if(done)monitorText("transferOperation","Chunk sent — waiting for host storage");
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
      throw Object.assign(Error("The SmoothCast computer sent an unreadable reply."),{status:response.status, retryAfter:1});
    }
    if(data?.code==="client_reload_required")showUpdateNotice();
    if(!response.ok||!data||data.ok===false)throw Object.assign(Error(response.status===429?"Upload requests are busy. Retrying shortly…":data?.error||"Upload request failed"),{status:response.status,code:data?.code,retryAfter:Math.max(1,Number(response.headers.get("Retry-After"))||1)});
    const validReceipt=validUploadProgress(data.received,data.size);
    if(method==="PUT"&&!validReceipt)
      throw Error("The SmoothCast computer sent an unexpected reply. Resume to check where the upload got to.");
    if(validReceipt)monitorText("transferAck",fileUnits(data.received));
    if(method==="PUT")monitorText("transferInFlight","Chunk acknowledged by host");
    else transferEvent(operation+" · HTTP "+response.status);
    monitorText("transferOperation","Host response received");
    return data;
  }catch(error){
    if(timedOut)error=Object.assign(Error("The SmoothCast computer did not respond within 60 seconds"),{status:408});
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
      if(pauseRequested)throw Error("Transfer paused");
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
// The final room action (queue or play) is idempotent server-side, so a
// transient busy or network error must be retried instead of stalling a
// multi-file batch after every byte has already arrived.
async function completeUpload(path,queueOnly,headers){
  for(let attempt=0;;attempt++){
    if(cancelUpload)throw Error("Upload cancelled");
    if(pauseRequested)throw Error("Transfer paused");
    try{return await uploadRequest("POST",path+"/complete",JSON.stringify({queue:queueOnly}),headers)}catch(error){
      if(pauseRequested)throw Error("Transfer paused");
      if(error.code==="client_reload_required")throw error;
      const transient=!error.status||error.status>=500||[408,409,429].includes(error.status);
      if(!transient||attempt===4||cancelUpload||!csrf)throw error;
      transferEvent("Retry "+(attempt+1)+" of 4 — confirming room acceptance");
      showError("uploadStatus","The room is busy. Retrying the queue request…");
      await new Promise(resolve=>setTimeout(resolve,Math.max(500*2**attempt,(error.status===429?error.retryAfter:0)*1000)));
      if(cancelUpload)throw Error("Upload cancelled");
      if(pauseRequested)throw Error("Transfer paused");
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
function transferView(phase,received=0,total=0,note="",queueOnly=$("uploadQueue").checked){
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
  $("transferDestination").textContent=queueOnly?"Up Next":"TV or speaker (pending)";
  const names={choose:"Choose media",prepare:"Preparing private transfer",transfer:"Sending to the SmoothCast computer",verify:"Checking received media",deliver:"Submitting to shared room"};
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
        pendingUpload={...record,received:state.received,queueOnly:state.queue_only??record.queueOnly};
        monitorText("transferFileName",record.name);
        monitorText("transferDelivery",pendingUpload.queueOnly?"Up Next requested":"Play now requested");
        transferEvent("Interrupted upload found; choose the original file to resume");
        $("uploadQueue").checked=pendingUpload.queueOnly;
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
  const files=batchFiles?batchFiles.slice(batchIndex):Array.from($("videoFile").files);
  const file=files[0],audio=files.length>0&&files.every(item=>/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(item.name));
  const invalid=files.find(item=>!Number.isSafeInteger(item.size)||item.size<=0||!/\.(mp4|m4v|mkv|mov|avi|webm|ts|mpeg|mpg|wmv|mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(item.name));
  const target=typeof shortcutState!=="undefined"?shortcutState?.receiver:null;
  // Audio is always queued per file, but a mixed selection may still request
  // playback of video. Never overwrite a locked batch's requested intent.
  if(audio&&!batchFiles&&!pendingUpload)$("uploadQueue").checked=true;
  const resumeLabel=pendingUpload&&(pendingUpload.received===pendingUpload.size
    ?"Retry queue / playback request":`Resume ${pendingUpload.name} (${Math.floor(pendingUpload.received*100/pendingUpload.size)}%)`);
  const summary=$("uploadSelectionSummary");
  if(summary){
    summary.textContent=invalid?("Cannot add "+invalid.name+": "+(invalid.size<=0?"the file is empty.":"choose a supported video or audio file.")+" Select files again; nothing has been sent."):files.length?files.length+" file"+(files.length===1?"":"s")+" selected · "+
      (typeof fileUnits==="function"?fileUnits(files.reduce((sum,item)=>sum+item.size,0)):"")+
      (audio||$("uploadQueue").checked?" · Add to Up Next":" · Play video on "+(target||"the selected room receiver (not yet confirmed)")+"; audio joins Up Next")+(files.length===1?" · "+file.name:""):
      pendingUpload?"Choose the original file to resume.":"No files selected. Choose a video or audio file to begin.";
  }
  $("uploadButton").disabled=uploading||!file||!!invalid;
  $("uploadButton").textContent=resumeLabel||(batchFiles?"Continue upload batch":($("uploadQueue").checked?"Upload and add":"Upload and cast"));
  $("videoFile").disabled=uploading||!!batchFiles;
  $("videoFile").multiple=!pendingUpload||!!batchFiles;
  $("uploadQueue").disabled=uploading||!!batchFiles||!!pendingUpload||!!audio;
  const destination=$("transferDestination");
  if(destination&&file&&!uploading&&!pendingUpload&&!batchFiles)destination.textContent=$("uploadQueue").checked||audio?"Up Next":target?target+" (requested)":"TV or speaker (pending)";
  const pause=$("pauseUpload");if(pause){pause.hidden=!uploading||!pendingUpload;pause.disabled=cancelUpload;}
  $("cancelUpload").hidden=!pendingUpload&&!batchFiles;
  $("cancelUpload").disabled=cancelUpload;
}
let batchCastTarget=null,quickCastIntent=false;
function chooseQueueUpload(){
  if(uploading||pendingUpload||batchFiles){
    showError("uploadStatus","Finish or cancel your existing transfer first.");
    return false;
  }
  quickCastIntent=false;
  $("uploadQueue").checked=true;
  updateUploadControls();
  $("videoFile").focus({preventScroll:true});
  return true;
}
$("quickQueueUpload").addEventListener("click",chooseQueueUpload);
$("openUploadEntry").addEventListener("click",chooseQueueUpload);
function recoverUnstartedCast(error){
  // A target fence can fail after confirmation but before the first upload
  // is created. Retain the file input, discard only the obsolete cast intent.
  if(error.status!==409||error.code==="client_reload_required"||pendingUpload||
      !batchFiles||batchIndex!==0||batchQueueOnly||!batchCastTarget)return false;
  batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;batchCastTarget=null;
  return true;
}
$("uploadCastNow").addEventListener("click",()=>{
  if(uploading||pendingUpload||batchFiles){location.hash="#uploadCard";showError("uploadStatus","Finish or cancel your existing transfer first.");return}
  quickCastIntent=true;
  location.hash="#uploadCard";
  $("videoFile").click();
});
$("videoFile").addEventListener("cancel",()=>{quickCastIntent=false;});
function resetUploadBatch(){
  batchCastTarget=null;quickCastIntent=false;
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
  batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;
  $("videoFile").value="";
  transferView("choose");
  monitorText("transferOperation","Cancelled");
  monitorText("transferDelivery","Not submitted");
  transferEvent("Upload cancelled");
  showError("uploadStatus","Upload cancelled");
}
$("uploadButton").addEventListener("click",async()=>{
  if(uploading)return;
  updateUploadControls();if($("uploadButton").disabled)return;
  const selected=Array.from($("videoFile").files);
  if(!batchFiles&&!selected.length)return;
  const session=csrf,json={"Content-Type":"application/json"};
  if(!pendingUpload&&!batchFiles)resetTransferMonitor();
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
      const queueIntent=pendingUpload?.queueOnly??$("uploadQueue").checked;
      if(!pendingUpload&&!queueIntent){
        showError("uploadStatus","Checking the pnode's selected receiver…");
        const target=await uploadRequest("POST","/api/uploads/target",JSON.stringify({}),json);
        if(!session||csrf!==session||cancelUpload)return;
        if(typeof target.receiver!=="string"||!target.receiver||!(/^[0-9a-f]{64}$/.test(target.target_id||"")))
          throw Error("No reachable casting target. Choose Add to Up Next instead.");
        if(!window.confirm("Stream this upload via SmoothCast to "+target.receiver+"?"+(target.active?" This replaces current playback.":""))){
          $("uploadQueue").checked=true;
          showError("uploadStatus","Not sent. Choose Upload and add to keep it in Up Next.");
          return;
        }
        batchCastTarget=target.target_id;
      }
      batchFiles=selected;
      batchIndex=0;
      batchAdded=0;
      batchTotal=selected.length;
      batchQueueOnly=queueIntent;
    }
    while(batchIndex<batchFiles.length&&!cancelUpload){
      const file=batchFiles[batchIndex],audio=/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name);
      let queueOnly=pendingUpload?.queueOnly??(audio||batchQueueOnly||batchIndex>0);
      monitorText("transferFileName",(batchIndex+1)+"/"+batchFiles.length+" · "+file.name);
      monitorText("transferDelivery",queueOnly?"Up Next requested":"Play now requested");
      monitorText("transferAck",pendingUpload?fileUnits(pendingUpload.received):"0 B");
      transferEvent((pendingUpload?"Resuming file ":"Preparing file ")+(batchIndex+1)+" of "+batchFiles.length+" · "+fileUnits(file.size));
      let state;
      if(pendingUpload){
        transferView("prepare",pendingUpload.received,file.size,"Resuming",queueOnly);
        showError("uploadStatus",`Checking ${file.name}…`);
        state=await uploadRequest("GET","/api/uploads/"+pendingUpload.id);
      }else{
        transferView("prepare",0,file.size,"File "+(batchIndex+1)+" of "+batchFiles.length,queueOnly);
        showError("uploadStatus",`Preparing ${batchIndex+1}/${batchFiles.length}: ${file.name}…`);
        state=await uploadRequest("POST","/api/uploads",JSON.stringify({name:file.name,size:file.size,queue:queueOnly,cast_target:queueOnly?null:batchCastTarget,batch_index:batchIndex+1,batch_total:batchFiles.length}),json);
        const {id,chunk_size:chunkSize}=state;
        if(typeof id!=="string"||!/^[A-Za-z0-9_-]{32}$/.test(id)||!validUploadChunkSize(chunkSize))
          throw Error("Upload setup returned invalid transfer parameters. Reload and retry.");
        if(state.queue_only===true&&!queueOnly){
          queueOnly=true;
          transferEvent("Another upload has the Play now lane; this file will join Up Next");
          monitorText("transferDelivery","Up Next — another upload has priority");
        }
        pendingUpload={id,chunkSize,name:file.name,size:file.size,lastModified:file.lastModified,queueOnly,started:Date.now(),received:0};
        monitorText("transferOperation","Reading local file fingerprint");
        const record={...pendingUpload,hashVersion:3,hash:await firstChunkHash(file,chunkSize)};
        await uploadStorage("readwrite",store=>store.put(record));
        transferEvent("Host reserved storage; chunk size "+fileUnits(chunkSize));
      }
      if(state.queue_only===true){queueOnly=true;pendingUpload.queueOnly=true;}
      const {id,chunkSize}=pendingUpload,path="/api/uploads/"+id;
      if(!validUploadChunkSize(chunkSize)||!validUploadProgress(state.received,file.size))
        throw Error("Upload progress is invalid. Reload and choose the file again.");
      casting=!!state.ready_to_cast;
      if(casting)monitorText("transferDelivery","Early playback requested — not confirmed");
      transferView("transfer",state.received,file.size,"",queueOnly);
      pendingUpload.received=state.received;
      let milestone=Math.floor(state.received*4/file.size);
      while(state.received<file.size&&!cancelUpload){
        const end=Math.min(state.received+chunkSize,file.size);
        state=await sendChunk(path,file,state.received,end);
        if(!validUploadProgress(state.received,file.size)||state.received!==end)
          throw Error("The SmoothCast computer reported an unexpected position. Resume to check where the upload got to.");
        pendingUpload.received=state.received;
        transferView("transfer",state.received,file.size,"",queueOnly);
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
      transferView("verify",file.size,file.size,"",queueOnly);
      $("pauseUpload").hidden=true;
      const receipt=await completeUpload(path,queueOnly,json);
      if(receipt.queue_only===true)queueOnly=true;
      monitorText("transferOperation","Transfer complete");
      monitorText("transferDelivery",queueOnly?"Added to Up Next":"Play requested — waiting for the TV or speaker");
      monitorText("transferAck",fileUnits(file.size));
      transferEvent(queueOnly?"Host accepted queue addition":"Host accepted playback request; receiver confirmation is separate");
      transferView("deliver",file.size,file.size,queueOnly?"Queue request accepted":"Playback request submitted",queueOnly);
      for(const step of $("transferSteps").children){step.classList.add("done");step.classList.remove("active");step.removeAttribute("aria-current");}
      $("transferStage").textContent=queueOnly?"Added to shared Up Next":"Play requested — waiting for the TV or speaker";
      $("transferEta").textContent="Complete";
      await clearPendingUpload();
      batchIndex++;
      batchAdded++;
      showError("uploadStatus",queueOnly?"Added to shared Up Next.":"Play requested; waiting for the TV or speaker to start.");
    }
    if(batchFiles&&batchIndex>=batchFiles.length){
      const count=batchAdded,total=batchTotal;
      batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;
      $("videoFile").value="";
      if(total>1)showError("uploadStatus",`${count} of ${total} file requests accepted by the host. See transfer activity for details.`);
      refresh();
    }
  }catch(error){
    if(!pauseRequested&&!cancelUpload){
      monitorText("transferOperation","Upload needs attention");
      transferEvent("Transfer paused by error: "+(error?.message||"Unknown upload failure"));
    }
    if(error.status===404){
      await clearPendingUpload();
      showError("uploadStatus",error.message+" Select the upload button to start this file again.");
    }else if(error.status===422||(error.status===413&&!pendingUpload)){
      await clearPendingUpload();
      batchIndex++;
      if(batchFiles&&batchIndex>=batchFiles.length){
        batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;
        $("videoFile").value="";
        showError("uploadStatus",`${error.message} Choose another file to continue.`);
      }else showError("uploadStatus",`${error.message} Skipped this file; select Continue upload batch to add the rest.`);
    }else if(pauseRequested){
      monitorText("transferOperation","Paused");
      transferEvent("Paused; Resume carries on from the last saved point");
      if(pendingUpload)transferView("transfer",pendingUpload.received,pendingUpload.size,"Paused — Resume available",pendingUpload.queueOnly);
      showError("uploadStatus","Paused safely. Select Resume to carry on from where it stopped.");
    }else if(cancelUpload){
      try{await discardUpload()}catch(cancelError){showError("uploadStatus",cancelError.message)}
    }else if(recoverUnstartedCast(error)){
      monitorText("transferDelivery","Destination needs confirmation");
      transferView("choose");
      showError("uploadStatus",error.message+" Your files are still selected. Select Upload and cast to confirm again, or Add to Up Next.");
    }else if(error.status===409&&error.code!=="client_reload_required"&&!pendingUpload&&!batchFiles){
      showError("uploadStatus",error.message+" Retry when a receiver is available, or select Add to Up Next.");
    }else {
      if(pendingUpload){
        const received=pendingUpload.received,total=pendingUpload.size,complete=received===total;
        transferView(complete?"verify":"transfer",received,total,complete?"Action not confirmed — retry available":"Paused — resume available",pendingUpload.queueOnly);
        showError("uploadStatus",error.message+(complete?" Select Retry queue / playback request.":" Select Resume to retry."));
      }else showError("uploadStatus",error.message+" Select Continue upload batch to retry.");
    }
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
  try{$("videoFile").files=event.dataTransfer.files;$("videoFile").dispatchEvent(new Event("change"));}
  catch(_){showError("uploadStatus","This browser cannot accept dropped files. Use Choose files instead.");}
});
$("uploadQueue").addEventListener("change",updateUploadControls);
$("videoFile").addEventListener("change",()=>{
  const file=$("videoFile").files[0],quick=quickCastIntent;quickCastIntent=false;
  if(quick&&file){
    if($("videoFile").files.length!==1||/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name)){
      $("uploadQueue").checked=true;updateUploadControls();
      showError("uploadStatus","Choose one video for Cast Now. Audio and batches can be added to Up Next.");return;
    }
    $("uploadQueue").checked=false;
  }
  updateUploadControls();
  if(file)transferView("choose",0,file.size,($("videoFile").files.length>1?$("videoFile").files.length+" files":"Ready"));
  if(quick&&file&&!$("uploadButton").disabled)$("uploadButton").click();
});
$("cancelUpload").addEventListener("click",async()=>{
  cancelUpload=true;if(activeUploadController)activeUploadController.abort();$("cancelUpload").disabled=true;showError("uploadStatus","Cancelling upload…");if(uploading)return;
  uploading=true;updateUploadControls();try{await discardUpload()}catch(error){showError("uploadStatus",error.message)}
  finally{finishUpload()}
});
document.addEventListener("visibilitychange",()=>{
  void syncRemoteWakeLock();
  if(document.hidden){stopPlayhead();clearTimeout(statusTimer);statusRequest?.abort("superseded");roomEvents.stop();return}
  statusFailures=0;
  if(csrf&&!stalePage){paintPlayhead();schedulePlayhead()}
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
  const empty=$("findEmpty"),reset=$("findReset");
  if(!input||!out||!status)return;
  let timer=null,source=null,controller=null,searchGeneration=0;
  const clock=s=>{s=Math.round(Number(s)||0);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return(h?h+":"+String(m).padStart(2,"0"):m)+":"+String(s%60).padStart(2,"0")};
  const LABELS={films:"Films",shows:"Shows",artists:"Artists",albums:"Albums",songs:"Songs",other:"Other"};
  function where(copies){
    const list=copies||[];if(!list.length)return"Availability unknown";
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
      go.addEventListener("click",()=>{input.value=(type==="artists"?"artist:":"album:")+JSON.stringify(it.name);input.dispatchEvent(new Event("input"));run()});
      const a=document.createElement("div");a.className="queue-actions";a.append(go);li.append(a);return li;
    }
    if(type==="shows"){
      meta.textContent=it.count+" episode"+(it.count===1?"":"s");text.append(title,meta);li.append(text);return li;
    }
    const bits=[it.year,it.artist,it.album,it.duration?clock(it.duration):""].filter(Boolean);
    meta.textContent=bits.join(" - ");
    const where_=document.createElement("div");where_.className="muted find-availability";where_.textContent=where(it.copies);
    text.append(title,meta,where_);li.append(text);
    const feedback=document.createElement("p");feedback.className="field-hint";feedback.setAttribute("role","status");text.append(feedback);
    const add=document.createElement("button");add.className="tiny";add.type="button";add.textContent="Add to Up Next";add.setAttribute("aria-label","Add "+(it.title||it.name||"media")+" to Up Next");
    if(!(it.copies||[]).some(c=>c.online)){add.disabled=true;add.title="Its computer is offline"}
    add.addEventListener("click",async()=>{
      if(add.disabled)return;
      add.disabled=true;feedback.textContent="Submitting request…";
      const session=csrf;
      try{
        const d=await post("/api/action",{action:"queue_add_key",key:it.id});
        if(csrf!==session)return;
        // A remote copy may still be transferring. Acknowledgement is not queue confirmation.
        feedback.textContent=d.message||"Request accepted; check Up Next for confirmation.";
        add.textContent=d.message==="Added to the queue."?"Added":"Requested";
        void refresh();
      }catch(err){if(csrf===session){feedback.textContent=err.message||"Could not add media. Retry.";add.disabled=false}}
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
      if(ul.children.length)out.append(h,ul);
    }
    const pending=(d.pending_origins||[]).length;
    status.textContent=n?n+(n===1?" result":" results")+(pending?" - still checking "+pending+(pending===1?" computer":" computers"):""):
      (pending?"Still checking "+pending+(pending===1?" computer":" computers")+"…":availableOnly?"No currently available matches. Turn off Available now to see offline media.":input.value.trim()?"No shared library matches "+JSON.stringify(input.value.trim())+". Try another title or search YouTube.":"No shared media matches this filter.");
  }
  function stop(){searchGeneration++;if(source){source.close();source=null}if(controller){controller.abort();controller=null}}
  async function run(){
    clearTimeout(timer);stop();const typed=input.value.trim();
    const generation=searchGeneration,session=csrf;
    const current=()=>generation===searchGeneration&&csrf===session;
    if(!session)return;
    if(reset)reset.hidden=!kind&&!availableOnly;
    if(empty)empty.hidden=Boolean(typed||kind);
    if(!typed&&!kind){out.replaceChildren();status.textContent=availableOnly?"Choose a media type or enter a search term to filter available media.":"";return}
    const q=(typed+(kind?" kind:"+kind:"")).trim();
    const url="/api/search"+(typeof EventSource==="function"?"/stream":"")+"?q="+encodeURIComponent(q);
    out.replaceChildren();status.textContent="Searching shared libraries…";
    if(typeof EventSource==="function"){
      const stream=new EventSource(url);source=stream;
      const accept=e=>{if(!current()||source!==stream)return;try{render(JSON.parse(e.data))}catch(_){status.textContent="Search update could not be read.";stop()}};
      stream.addEventListener("results",accept);
      stream.addEventListener("more",accept);
      stream.addEventListener("done",()=>{if(current()&&source===stream)stop()});
      stream.onerror=()=>{if(current()&&source===stream){status.textContent="Search connection interrupted. Change the query or filter to retry.";stop()}};
      return;
    }
    const request=new AbortController();controller=request;
    try{const r=await fetch(url,{credentials:"same-origin",signal:request.signal});const d=await r.json();if(!current()||request.signal.aborted)return;if(!r.ok)throw Error(d.error||"Search failed");render(d)}
    catch(err){if(current()&&err.name!=="AbortError")status.textContent=err.message}
    finally{if(controller===request)controller=null}
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
  const form=$("findForm"),clear=$("findClear"),browseLink=$("findBrowse");
  if(form)form.addEventListener("submit",event=>{event.preventDefault();run()});
  function resetFilters(){kind="";availableOnly=false;for(const chip of document.querySelectorAll("#findChips button"))chip.setAttribute("aria-pressed","false");}
  if(reset)reset.addEventListener("click",()=>{resetFilters();run()});
  if(clear)clear.addEventListener("click",()=>{resetFilters();input.value="";input.dispatchEvent(new Event("input"));run();input.focus()});
  if(browseLink)browseLink.addEventListener("click",()=>{lib.open=true});
  let libLoaded=false,libraryGeneration=0,libraryBusy=false;
  const libStatus=$("libStatus"),libRefresh=$("libRefresh");
  const libraryStatus=message=>{if(libStatus)libStatus.textContent=message};
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
    if(cursor&&libraryBusy)return;
    const generation=++libraryGeneration,session=csrf;
    if(!session)return;
    const current=()=>generation===libraryGeneration&&csrf===session;
    libraryBusy=true;libraryStatus(cursor?"Loading more media…":"Opening shared folder…");
    try{
      const url="/api/libraries/"+encodeURIComponent(origin)+"/"+encodeURIComponent(folder)+"?path="+encodeURIComponent(path)+(cursor?"&cursor="+encodeURIComponent(cursor):"");
      const d=await getJSON(url);
      if(!current())return;
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
      libraryStatus(!(d.dirs||[]).length&&!(d.items||[]).length&&!cursor?"No media in this folder.":"");
    }catch(err){if(current())libraryStatus(err.message||"Could not open this folder.")}
    finally{if(generation===libraryGeneration)libraryBusy=false}
  }
  async function showAll(){
    const generation=++libraryGeneration,session=csrf;
    if(!session)return;
    const current=()=>generation===libraryGeneration&&csrf===session;
    libraryBusy=true;libraryStatus("Refreshing shared libraries…");
    try{const d=await getJSON("/api/libraries");if(current()){showOrigins(d);libLoaded=true;libraryStatus("")}}
    catch(err){if(current()){libLoaded=false;libraryStatus(err.message||"Could not load libraries.")}}
    finally{if(generation===libraryGeneration)libraryBusy=false}
  }
  if(libRefresh)libRefresh.addEventListener("click",showAll);
  lib.addEventListener("toggle",()=>{if(lib.open&&!libLoaded)showAll()});
  input.addEventListener("input",()=>{clearTimeout(timer);stop();out.replaceChildren();if(empty)empty.hidden=Boolean(input.value.trim()||kind);status.textContent="";timer=setTimeout(run,120)});
})();
(()=>{
  const input=$("findInput"),search=$("youtubeSearch"),panel=$("youtubeResultsPanel"),
    status=$("youtubeSearchStatus"),out=$("youtubeResults"),consent=$("youtubeAuthorised");
  if(!input||!search||!panel||!status||!out||!consent)return;
  let generation=0;
  input.addEventListener("input",()=>{
    generation++;panel.hidden=true;out.replaceChildren();consent.checked=false;
  });
  search.addEventListener("click",async()=>{
    const q=input.value.trim();
    if(youtubeSearchBusy||!(linkCapabilities.youtube_search??linkCapabilities.youtube))return;
    panel.hidden=false;out.replaceChildren();consent.checked=false;
    if(!q){status.textContent="Type something to search on YouTube.";input.focus();return}
    const current=++generation,session=csrf;
    youtubeSearchBusy=true;updateLinkControls();status.textContent="Searching YouTube…";
    try{
      const response=await post("/api/search/youtube",{q});
      if(current!==generation||csrf!==session)return;
      const results=Array.isArray(response.results)?response.results.slice(0,10):[];
      for(const result of results){
        if(!result||typeof result.id!=="string"||!/^[A-Za-z0-9_-]{11}$/.test(result.id))continue;
        const row=document.createElement("li");row.className="queue-item";
        const info=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("div");
        title.textContent=result.title||"YouTube video";meta.className="muted";
        meta.textContent=[result.channel,Number.isFinite(result.duration)&&result.duration>0?clock(result.duration):""].filter(Boolean).join(" · ");
        info.append(title,meta);
        const actions=document.createElement("div");actions.className="queue-actions";
        const add=document.createElement("button");add.className="tiny";add.type="button";add.textContent="Add to Up Next";
        add.setAttribute("aria-label","Add "+title.textContent+" to Up Next");
        const request_id="yt-"+Date.now()+"-"+Math.random().toString(36).slice(2);
        add.addEventListener("click",async()=>{
          if(add.disabled||current!==generation||csrf!==session)return;
          if(!linkCapabilities.youtube){status.textContent="No eligible YouTube download worker is currently available.";return}
          if(linkStorageAvailable===false){status.textContent="Download storage is unavailable. Ask the host to check it and restart the room. Your search results are preserved.";return}
          if(!consent.checked){status.textContent="Confirm that you are authorised to download this media.";consent.focus();return}
          add.disabled=true;add.textContent="Submitting…";
          try{
            const receipt=await post("/api/link-jobs",{url:"https://www.youtube.com/watch?v="+result.id,request_id,authorised:true});
            add.textContent="Download requested";
            if(current===generation&&csrf===session)status.textContent=receipt.message||"Download accepted; follow its progress in Queue.";
            void refresh();
          }catch(err){
            if(current===generation&&csrf===session)status.textContent=err.message;
            add.disabled=false;add.textContent="Retry add to Up Next";
          }
        });
        actions.append(add);row.append(info,actions);out.append(row);
      }
      status.textContent=out.children.length?out.children.length+" YouTube results. Choose a video to download.":"No YouTube videos found.";
    }catch(err){if(current===generation&&csrf===session)status.textContent=err.message}
    finally{youtubeSearchBusy=false;updateLinkControls()}
  });
})();
(()=>{
  const input=$("findInput"),button=$("magnetSearch"),auto=$("magnetAuto"),panel=$("magnetResultsPanel"),
    status=$("magnetSearchStatus"),out=$("magnetResults"),consent=$("magnetAuthorised");
  if(!input||!button||!auto||!panel||!status||!out||!consent)return;
  let generation=0,timer=null,busy=false,pending=null;
  function invalidate(){
    generation++;clearTimeout(timer);pending=null;panel.hidden=true;out.replaceChildren();consent.checked=false;
  }
  function schedule(){
    invalidate();
    if(auto.checked&&input.value.trim().length>=3)timer=setTimeout(()=>request(),850);
  }
  function request(){
    clearTimeout(timer);
    const q=input.value.trim(),session=csrf;
    if(!session||!linkCapabilities.magnet_search)return;
    if(q.length<3){panel.hidden=false;status.textContent="Enter at least three characters.";input.focus();return}
    pending={q,session,generation:++generation};
    out.replaceChildren();consent.checked=false;panel.hidden=false;
    status.textContent=busy?"Waiting for the previous search…":"Searching open torrents…";
    void drain();
  }
  async function drain(){
    if(busy||!pending)return;
    const job=pending;pending=null;busy=true;
    const current=()=>job.generation===generation&&csrf===job.session;
    try{
      if(!current())return;
      status.textContent="Searching Internet Archive…";
      const response=await post("/api/search/magnets",{q:job.q});
      if(!current())return;
      const results=Array.isArray(response.results)?response.results.slice(0,4):[];
      for(const result of results){
        if(!result||typeof result.id!=="string"||!/^[a-f0-9]{40}$/.test(result.id))continue;
        const row=document.createElement("li");row.className="queue-item";
        const info=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("div");
        title.textContent=result.title||"Archive media";meta.className="muted";
        const downloads=Number.isSafeInteger(result.downloads)?result.downloads.toLocaleString()+" Archive downloads":"";
        meta.textContent=[result.source||"Internet Archive",downloads,Number.isFinite(result.size)?(result.size/1048576).toFixed(0)+" MiB":""].filter(Boolean).join(" · ");
        info.append(title,meta);
        const source=document.createElement("a");
        if(typeof result.archive_id==="string"&&/^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/.test(result.archive_id)){
          source.href="https://archive.org/details/"+encodeURIComponent(result.archive_id);source.target="_blank";source.rel="noopener noreferrer";source.textContent="Check source and licence";info.append(source);
        }
        const add=document.createElement("button");add.type="button";add.className="tiny";add.textContent="Download & add";
        const actions=document.createElement("div");actions.className="queue-actions";actions.append(add);
        const request_id="archive-"+Date.now()+"-"+Math.random().toString(36).slice(2);
        add.addEventListener("click",async()=>{
          if(add.disabled||!current())return;
          if(!linkCapabilities.magnet||linkStorageAvailable===false){status.textContent="No eligible download worker or storage.";return}
          if(!consent.checked){status.textContent="Confirm you have permission to download this media.";consent.focus();return}
          add.disabled=true;add.textContent="Submitting…";
          try{
            const receipt=await post("/api/link-jobs",{url:"magnet:?xt=urn:btih:"+result.id,request_id,authorised:true});
            if(current()){add.textContent="Download requested";status.textContent=receipt.message||"Download requested; follow Queue."}
            void refresh();
          }catch(err){if(current()){status.textContent=err.message;add.disabled=false;add.textContent="Retry download"}}
        });
        row.append(info,actions);out.append(row);
      }
      status.textContent=out.children.length?out.children.length+" compatible open torrents. Check the licence and choose a download.":"No compatible openly licensed torrents found.";
    }catch(err){if(current())status.textContent=err.message||"Archive search unavailable."}
    finally{busy=false;if(pending)void drain()}
  }
  input.addEventListener("input",schedule);
  auto.addEventListener("change",schedule);
  button.addEventListener("click",request);
})();
// #591: the Home control is always in the sticky app bar. It returns to the top
// of the room and moves keyboard/screen-reader focus there; the now-playing pill
// mirrors the playback card so the current item is visible from any section.
(()=>{
  const home=$("homeButton"),top=$("roomTop"),pill=$("barNow"),pillTitle=$("barNowTitle");
  const title=$("title"),state=$("state"),dash=$("dashboard");
  if(!home||!top||!pill||!pillTitle||!title||!state||!dash||!home.addEventListener)return;
  const still=()=>typeof matchMedia==="function"&&matchMedia("(prefers-reduced-motion: reduce)").matches;
  function syncRoomBlade(navigate=false){
    const target=$(location.hash.slice(1));
    const blade=target&&dash.contains(target)&&target.closest("#homePanel,#findPanel,#peoplePanel,#screensPanel,#meshPanel,#advancedPanel");
    const selected=blade?blade.id:"";
    const previous=dash.getAttribute("data-room-blade")||"";
    if(selected)dash.setAttribute("data-room-blade",selected);
    else dash.removeAttribute("data-room-blade");
    for(const link of dash.querySelectorAll("nav a")){
      if(link.getAttribute("href")==="#"+(selected||"homePanel"))link.setAttribute("aria-current","page");
      else link.removeAttribute("aria-current");
    }
    if(navigate&&!dash.hidden&&target&&dash.contains(target)&&(selected||previous)){
      target.scrollIntoView({block:"start",behavior:"auto"});
      if((blade===target||["uploadCard","queuePanel","playback"].includes(target.id))&&!target.contains(document.activeElement)){
        const heading=$(target.id==="queuePanel"?"queueHeading":target.id==="uploadCard"?"uploadHeading":target.id==="playback"?"playbackHeading":selected==="homePanel"?"homeHeading":selected==="findPanel"?"findHeading":selected==="peoplePanel"?"peopleHeading":selected==="screensPanel"?"screensPanelHeading":selected==="meshPanel"?"meshTitle":selected==="advancedPanel"?"roomSettingsHeading":"localLiveHeading");
        if(heading&&heading.focus)heading.focus({preventScroll:true});
      }
    }
  }
  window.addEventListener("hashchange",()=>syncRoomBlade(true));
  syncRoomBlade();
  const goHome=event=>{
    event.preventDefault();
    if(location.hash)history.replaceState(null,"",location.pathname+location.search);
    syncRoomBlade();
    window.scrollTo({top:0,behavior:still()?"auto":"smooth"});
    top.focus({preventScroll:true});
  };
  home.addEventListener("click",goHome);
  const logo=$("homeLogo");if(logo&&logo.addEventListener)logo.addEventListener("click",goHome);
  const idle=new Set(["","Nothing playing","—"]);
  function syncPill(){
    const text=(title.textContent||"").trim(),mode=(state.textContent||"").trim();
    const show=!dash.hidden&&!idle.has(text);
    if(pill.hidden===show)pill.hidden=!show;
    if(!show)return;
    if(pillTitle.textContent!==text)pillTitle.textContent=text;
    const paused=!/play|buffer/i.test(mode);
    pill.classList.toggle("paused",paused);
    const label="Now playing: "+text+(mode&&mode!=="—"?" ("+mode+")":"")+". Go to playback controls";
    if(pill.getAttribute("aria-label")!==label)pill.setAttribute("aria-label",label);
  }
  if(typeof MutationObserver!=="function"){syncPill();return}
  const watch=new MutationObserver(syncPill);
  for(const node of [title,state])watch.observe(node,{childList:true,characterData:true,subtree:true});
  watch.observe(dash,{attributes:true,attributeFilter:["hidden"]});
  const routeWatch=new MutationObserver(()=>{if(!dash.hidden&&location.hash)syncRoomBlade(true)});
  routeWatch.observe(dash,{attributes:true,attributeFilter:["hidden"]});
  syncPill();
})();
// Ticket 592: invite QR from the same origin. Handlers are attached before src so
// a fast or cached load is never missed; on failure the link remains the way in.
(()=>{
  const img=$("inviteQr"),fallback=$("inviteQrFallback");
  if(!img||!fallback||!img.addEventListener)return;
  img.addEventListener("load",()=>{img.hidden=false;fallback.hidden=true});
  img.addEventListener("error",()=>{img.hidden=true;img.removeAttribute("src");fallback.hidden=false});
  img.src="/join-qr.png";
})();
</script></body></html>"""
_HTML = _HTML.replace("/*TOKENS*/", design_tokens.css())
