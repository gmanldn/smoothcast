"""Small, PIN-protected shared-room dashboard hosted by the GTK application.

The portal uses Python's standard-library HTTP server so SmoothCast adds no
web framework or runtime dependency. GTK callbacks are supplied by the caller
and are dispatched onto the GTK main context by the application layer.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache
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
from urllib.parse import parse_qs, urlsplit

import lan_guard
import library_replication
import portal_commands
import peer_discovery
import portal_room
import portal_screen_page
import portal_mesh_http
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


@lru_cache(maxsize=1)
def page_build() -> str:
    """Version plus the served page's hash, never a duplicated release constant."""
    return version.__version__ + "-" + hashlib.sha256(
        (_HTML + portal_screen_page.panel_html() + shortcut_map.browser_json()).encode("utf-8")
    ).hexdigest()[:12]


def _page() -> bytes:
    # Replace just the main closing tag; the Screens panel is part of the build.
    markup = _HTML.replace("</main>", portal_screen_page.panel_html() + "</main>", 1)
    return (markup.replace("__SC_BUILD__", page_build())
            .replace("__SC_SCHEMA__", str(CLIENT_SCHEMA))
            .replace("__SC_SHORTCUTS__", shortcut_map.browser_json())).encode("utf-8")


class _PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, pin: str, dispatch: Callable, *, clock=time.monotonic,
                 pin_required: bool = True,
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
        self.library_search: Callable | None = None
        self.library_search_stream: Callable | None = None
        self.library_replication = None
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

    def server_close(self) -> None:
        try:
            self.screens.close()
            self.commands.close()
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
            for participant_id in participants:
                self.room.leave(participant_id)
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
                self._queue_command_cache.move_to_end(key)
                if cached[1] != fingerprint:
                    return 409, "Queue command ID was already used with different data"
                return cached[2], cached[3]
            action = body.get("action")
            try:
                payload = ({**body, "_portal_auth_key": session_key}
                           if session_key is not None else body)
                message = self.dispatch(action, payload)
                self.room.record(participant_id, "action", {
                    "action": action, "id": body.get("id"),
                })
                status, result = 202, str(message or "Queue updated")
            except PortalRequestError as exc:
                status, result = exc.status, exc.message
            except Exception:
                status, result = 503, "SmoothCast could not accept that queue edit"
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


class _Handler(BaseHTTPRequestHandler):
    server: _PortalHTTPServer
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT
    server_version = "SmoothCastPortal"
    sys_version = ""

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
            429, {"ok": False, "error": "Too many room requests. Try again shortly."},
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
        if path in {"/", "/index.html"}:
            page = _page().replace(
                b"__PIN_REQUIRED__", b"1" if self.server.pin_required else b"0")
            return self._send(200, page, content_type="text/html; charset=utf-8")
        if portal_screens_http.route(self, "GET", path):
            return
        if portal_mesh_http.route(self, "GET", path):
            return
        if path == "/api/search/stream":
            return self._search_stream()
        if path == "/api/search":
            return self._search()
        if path.startswith("/mesh/library/"):
            return self._mesh_library(path)
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
        if path == "/api/status":
            if not self._authenticated():
                return self._error(401, "Enter the PIN shown in SmoothCast")
            if self._throttle("read"):
                return
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
            directory = self.server.peer_directory
            state["screens"] = self.server.screens.snapshot()
            state["peers"] = directory.snapshot() if directory is not None else []
            state["peer_discovery_available"] = directory is not None
            return self._send(200, {"ok": True, "state": state,
                                    "build": page_build(), "client_schema": CLIENT_SCHEMA})
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
                return self._error(exc.status, exc.message)
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
                return self._error(exc.status, exc.message)
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
                return self._error(exc.status, exc.message)
            return self._send(200, {"ok": True,
                                    "participant": participant.public(self.server.clock())})
        if path == "/api/action":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            action = body.get("action")
            try:
                envelope = portal_commands.parse_envelope(body)
                participant_id = self.server.session_participant(self._cookie_token())
                if participant_id is None:
                    return self._error(401, "Session expired")
                if envelope is None:
                    if not isinstance(action, str) or action not in {
                            "play_pause", "stop", "seek", "volume", "mute", "music_autogain",
                            "next", "previous", "queue_play", "queue_remove",
                            "queue_move", "queue_next", "queue_clear", "queue_vote",
                            "queue_add_key"}:
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
                            result = self.server.dispatch(action, {
                                **body, "_portal_auth_key": self.server._session_key(
                                    self._cookie_token() or ""),
                            })
                        except PortalRequestError as exc:
                            return self._error(exc.status, exc.message)
                        except Exception:
                            return self._error(503, "SmoothCast could not accept that command")
                        self.server.room.record(participant_id, "action",
                                                {"action": action, "id": body.get("id")})
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
                "_portal_auth_key": self.server._session_key(self._cookie_token() or ""),
            })
            accepted = True
        except Exception:
            accepted = False
        self.server.uploads.mark_early_cast(upload_id, accepted=accepted)

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
            return self._error(exc.status, exc.message)

    def _not_allowed(self) -> None:
        self._error(405, "Method not allowed")

    def do_HEAD(self) -> None:  # noqa: N802
        # Only authenticated media may answer HEAD; every other path stays 405.
        if not self._safe_origin(required=False):
            return self._error(400, "Invalid host")
        if not portal_screens_http.route(self, "HEAD", self._path()):
            self._not_allowed()

    do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815


class Portal:
    """One-interface LAN portal with a per-run PIN and clean thread shutdown."""

    def __init__(self, bind_ip: str, dispatch: Callable, *, pin: str | None = None,
                 uploads: portal_uploads.UploadManager | None = None,
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
            commands=commands, fence=fence,
            room=self.room, pin_required=pin_required,
        )
        self.port = int(self.server.server_address[1])
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
:root{font:16px system-ui,sans-serif;color-scheme:light dark;--bg:#101722;--card:#1c2735;--accent:#4d9de0;--muted:#b7c3d0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f4f7fb}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.05rem;margin:0 0 12px}p{color:var(--muted);margin:.35rem 0}
section{background:var(--card);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 26px #0002}
label{display:block;margin:12px 0 6px}input,button{font:inherit;min-height:44px;border-radius:10px;border:1px solid #718096;padding:8px 12px}
input{width:100%;color:inherit;background:#121b27}button{background:var(--accent);color:white;border:0;font-weight:650;cursor:pointer}
#musicAutogain{width:auto;min-height:0;margin-right:8px}
dialog#shortcutsHelp{background:var(--card);color:#f4f7fb;border:1px solid #718096;border-radius:14px;max-width:min(92vw,480px);width:100%;padding:20px}
dialog#shortcutsHelp::backdrop{background:#000b}
#shortcutsList{display:grid;gap:8px}
#shortcutsList li{display:flex;justify-content:space-between;gap:12px;align-items:center}
#shortcutsList kbd{border:1px solid #718096;border-radius:6px;padding:4px 7px;white-space:nowrap}
button.secondary{background:#36475d}button:disabled,input:disabled{opacity:.55;cursor:not-allowed}.actions{display:flex;gap:8px;flex-wrap:wrap}
.actions button{flex:1 1 120px}.actions input{flex:1 1 160px;min-width:0}.muted{color:var(--muted)}.big{font-size:1.35rem;font-weight:700}.row{display:flex;justify-content:space-between;gap:12px}
progress{width:100%;height:10px}ul{padding-left:0;list-style:none}li{padding:4px 0;overflow-wrap:anywhere}#error{color:#ffb4a9;min-height:1.4em}
.participants{display:flex;flex-wrap:wrap;gap:7px;margin:4px 0 0}.person{display:flex;align-items:center;gap:6px;background:#121b27;border:1px solid #ffffff12;border-radius:999px;padding:4px 9px 4px 4px;font-size:.82rem}.person.offline{opacity:.45}.avatar{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:.68rem;font-weight:750;color:#08101a}
.queue-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border-top:1px solid #ffffff10;padding:8px 0}.queue-item:first-child{border-top:0}.queue-item strong{display:block;font-size:.88rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue-item .muted{font-size:.74rem}.queue-actions{display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.tiny{min-height:32px;padding:4px 8px;font-size:.76rem;border-radius:8px}.vote{background:#1c3555;border:1px solid #4d9de066;color:#cfe6ff}.vote.on{background:#2e6fae;color:white}.activity{display:grid;gap:4px;font-size:.78rem;color:var(--muted);max-height:160px;overflow:auto}.activity .ev{display:flex;gap:7px}.activity time{color:#8394aa;white-space:nowrap}.empty{color:var(--muted);border:1px dashed #718096;border-radius:10px;padding:12px;text-align:center}
header{padding:16px 0;border-bottom:1px solid #425264}header h1{font-size:clamp(1.6rem,5vw,2.2rem);letter-spacing:-.04em}
nav{display:flex;flex-wrap:wrap;gap:4px;margin:12px 0}nav a{display:inline-flex;align-items:center;min-height:44px;padding:0 12px;border-radius:10px;background:#26364a;color:#e2edff;text-decoration:none}nav a:hover{background:#364b65}
#login{max-width:30rem;margin:24px auto}#login button{width:100%}#pin{letter-spacing:.25em}button:not(.secondary):not(.vote){color:#081522}
@media(max-width:480px){.queue-item{grid-template-columns:minmax(0,1fr)}.queue-actions{justify-content:flex-start}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
:focus-visible{outline:3px solid #ffd166;outline-offset:2px}@media(max-width:480px){main{padding:12px}section{padding:15px}}
</style></head><body><main><header><h1>SmoothCast</h1><p>Local playback dashboard</p></header>
<div id="updateNotice" role="alert" hidden><strong>SmoothCast was updated</strong><p>Reload to reconnect safely.</p><button id="reloadNow" type="button">Reload page</button></div>
<section id="login"><h2>Connect to SmoothCast</h2><p id="loginHint">Enter your name and the six-digit PIN shown on the SmoothCast home screen.</p>
<form id="loginForm"><label for="name">Your name</label><input id="name" name="name" maxlength="40" autocomplete="nickname" placeholder="e.g. Sam" required>
<div id="pinRow"><label for="pin">Access PIN</label><input id="pin" name="pin" minlength="6" maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" required></div>
<p id="error" role="alert" aria-live="polite"></p><button type="submit">Connect</button></form></section>
<div id="dashboard" hidden><nav aria-label="Room sections"><a href="#playback">Playback</a><a href="#findPanel">Find</a><a href="#queuePanel">Queue</a><a href="#peoplePanel">People</a><a href="#networkActivity">Network</a></nav><section id="playback"><div class="row"><h2>Now Playing</h2><span id="state" class="muted">—</span></div>
<p id="title" class="big">Nothing playing</p><p id="receiver">Receiver: —</p><progress id="progress" max="1" value="0" aria-label="Playback progress"></progress>
<div class="row"><span id="elapsed">0:00</span><span id="duration">—</span></div>
<label for="seek">Seek</label><input id="seek" type="range" min="0" max="1" value="0" disabled>
<div class="actions"><button data-action="play_pause">Play / pause</button><button class="secondary" data-action="stop">Stop</button><button class="secondary" data-action="previous">Previous</button><button class="secondary" data-action="next">Next</button></div></section>
<section><h2>Volume</h2><label for="volume">Receiver volume</label><input id="volume" type="range" min="0" max="100" value="0" disabled><p id="volumeText">—</p></section>
<section><h2>Music</h2><label><input id="musicAutogain" type="checkbox"> Normalise audio-only tracks</label><p>Targets -16 LUFS with a -1.5 dBTP ceiling. Existing programme/album normalisation takes precedence.</p></section>
<section id="peoplePanel"><h2>In the room</h2><div id="people" class="participants"></div><form id="nameForm"><label for="displayName">Your display name</label><div class="actions"><input id="displayName" maxlength="40" autocomplete="nickname" required><button class="secondary" type="submit">Update name</button></div></form><h2 style="margin-top:18px">Activity</h2><div id="activity" class="activity"></div></section>
<section><h2>Nearby SmoothCast hosts</h2><p>Opening another host requires that host's own room PIN. Discovery does not grant access.</p><ul id="peers"><li class="empty">No other SmoothCast hosts found</li></ul></section>
<section id="findPanel"><h2>Find</h2><label for="findInput" class="muted">Search films, shows and music in every computer</label><input id="findInput" type="search" placeholder="Search the house" autocomplete="off" maxlength="200"><p id="findStatus" class="muted" role="status" aria-live="polite"></p><div id="findResults" aria-label="Search results"></div></section>
<section id="queuePanel"><div class="row"><h2>Up Next</h2><span id="queueCount" class="muted"></span></div><button id="clearQueue" class="secondary tiny" type="button" disabled>Clear Up Next</button><ul id="queue" aria-label="Up Next" tabindex="-1"><li class="empty">No videos queued</li></ul></section>
<section id="networkActivity"><h2>On your network</h2><p>Read-only status from reachable Cast and DLNA receivers; refreshes every 15 seconds. Unreachable receivers are omitted.</p><p id="networkActivitySummary" class="muted" role="status" aria-live="polite">Checking discovered receivers…</p><ul id="networkActivityRows"><li>No active streams reported by reachable receivers</li></ul></section></div><p id="errorDash" role="status" aria-live="polite"></p>
<section id="uploadCard" hidden><h2>Add media from this device</h2><p>Files transfer in resumable chunks. Audio is validated and added to the shared queue; video can be queued or streamed to this host’s receiver.</p>
<label for="videoFile">Audio or video files</label><input id="videoFile" type="file" accept="audio/*,video/*,.mkv,.ts,.wmv" multiple>
<label style="display:flex;align-items:center;gap:9px;min-height:44px"><input id="uploadQueue" type="checkbox" style="width:auto;min-height:auto" checked> Add to the shared queue</label>
<progress id="uploadProgress" max="1" value="0" aria-label="Upload progress"></progress><p id="uploadStatus" role="status" aria-live="polite"></p>
<div class="actions"><button id="uploadButton" type="button">Upload and add</button><button id="cancelUpload" class="secondary" type="button" hidden>Cancel upload</button></div></section>
<dialog id="shortcutsHelp" aria-labelledby="shortcutsHeading"><h2 id="shortcutsHeading">Keyboard shortcuts</h2><p>Available when you are not typing in a field.</p><ul id="shortcutsList"></ul><button id="shortcutsClose" type="button">Close</button></dialog></main>
<script>
const PAGE_BUILD="__SC_BUILD__",CLIENT_SCHEMA=Number("__SC_SCHEMA__");
const SHORTCUTS=typeof __SC_SHORTCUTS__==="undefined"?[]:__SC_SHORTCUTS__,shortcutMap=new Map(SHORTCUTS.map(entry=>[entry.key,entry]));
let stalePage=false,shortcutState=null;
function showUpdateNotice(){
  stalePage=true;
  document.getElementById("updateNotice").hidden=false;
  document.getElementById("dashboard").hidden=true;
  document.getElementById("uploadCard").hidden=true;
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
async function post(path,body){if(stalePage)throw Error("Reload required");const r=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf,...clientHeaders},body:JSON.stringify(body)});const d=await r.json();if(d.code==="client_reload_required"){showUpdateNotice();throw Error(d.error||"Reload required")}if(r.status===429){const retryAfter=Math.max(1,Number(r.headers.get("Retry-After"))||1);rateDelayUntil=Date.now()+retryAfter*1000;throw Object.assign(Error("Too many controls at once. Try again shortly."),{status:429,retryAfter})}if(!r.ok)throw Error(d.error||"Request failed");return d}
const PIN_REQUIRED="__PIN_REQUIRED__"!=="0";
const loginButton=$("loginForm").querySelector("button");
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
    $("login").hidden=true;
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
      $("login").hidden=true;
      refresh();
      return true;
    }catch(_){return false}
  }
  restoreSession().then(restored=>{
    if(restored||PIN_REQUIRED)return;
    $("pinRow").hidden=true;$("pin").required=false;$("pin").value="";
    $("loginHint").textContent="Enter your name to join the house.";
    loginButton.textContent="Join";
    let saved="";try{saved=localStorage.getItem("sc_name")||""}catch(_){}
    if(saved){$("name").value=saved;loginButton.click()}
  });
})();
function expireSession(){
  csrf="";
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
  showError("error","Room access expired. Enter the current PIN to reconnect.");
  $("pin").focus();
}
function clock(s){if(s==null||!Number.isFinite(s))return "--:--";s=Math.floor(Math.max(0,s));const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;return h?`${h}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`:`${m}:${String(sec).padStart(2,"0")}`}
let queueRenderKey=null,queuePressed=false,deferredQueue=null,queueState=[];
const queueElement=$("queue");
function queueAction(button){
  const row=button.closest("[data-queue-id]");
  if(!row)return;
  const id=row.dataset.queueId;
  const index=queueState.findIndex(item=>String(item.id)===id);
  if(index<0){showError("errorDash","That queue item is no longer here");return}
  const item=queueState[index];
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
    empty.textContent="No videos queued";
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
    li.children[0].children[1].textContent=(item.votes?"▲ "+item.votes+" vote"+(item.votes===1?"":"s"):"No votes")
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
    const captions=[item.voted?"Voted":"Vote","Play now","↑","↓","Next","×"];
    Array.from(buttons).forEach((button,i)=>{
      button.textContent=captions[i];
      button.setAttribute("aria-label",labels[i]);
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
  if(!csrf||stalePage||document.hidden)return;
  const delay=statusFailures?Math.min(30000,2000*2**statusFailures+Math.random()*500):2000;
  statusTimer=setTimeout(refresh,Math.max(delay,rateDelayUntil-Date.now()));
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
    if(!matchingBuild(d))return;
    const s=d.state||{};shortcutState=s;$("state").textContent=s.state_label||"State unavailable";$("title").textContent=s.title||"Nothing playing";$("receiver").textContent="Receiver: "+(s.receiver||"—");
queueRevision=Number.isSafeInteger(s.queue_revision)?s.queue_revision:0;const duration=Number(s.duration)||0,position=Number(s.position)||0;$("progress").max=duration||1;$("progress").value=Math.min(position,duration||position);if(!editingControls.has("seek")){$("seek").max=duration||1;$("seek").value=Math.min(position,duration||position);$("seek").disabled=!s.can_seek||!duration;}$("elapsed").textContent=clock(position);$("duration").textContent=clock(duration);if(!editingControls.has("volume")){$("volume").disabled=s.volume==null;$("volume").value=s.volume||0;$("volumeText").textContent=s.volume==null?"Volume unavailable":`${s.volume}%`;}
$("musicAutogain").checked=!!s.music_autogain;
renderQueue(s.queue);
$("queueCount").textContent=s.queue&&s.queue.length?`${s.queue.length} waiting`:"";$("clearQueue").disabled=!s.queue||!s.queue.length;
renderRoom(s.room);renderPeers(s.peers,s.peer_discovery_available);window.scRenderScreens&&window.scRenderScreens(s);
const streams=Array.isArray(s.network_activity)?s.network_activity:[],activityRows=$("networkActivityRows");activityRows.replaceChildren();$("networkActivitySummary").textContent=streams.length?`${streams.length} active stream${streams.length===1?"":"s"} on reachable receivers`:"No active streams reported by reachable receivers";if(!streams.length){const li=document.createElement("li");li.textContent="When someone starts casting on this network, it appears here. Unreachable receivers are omitted.";activityRows.append(li)}else for(const item of streams){const li=document.createElement("li"),title=document.createElement("strong"),detail=document.createElement("span");title.textContent=item.title||"Media title unavailable";detail.className="muted";const timing=item.position==null?"":` · ${clock(item.position)}${item.duration==null?"":` / ${clock(item.duration)}`}`;detail.textContent=`${item.receiver||"Unknown receiver"} · ${item.protocol||"Receiver"} · ${item.state||"ACTIVE"}${timing}${item.is_local?" · This SmoothCast":""}`;li.replaceChildren(title,document.createElement("br"),detail);activityRows.append(li)}
document.querySelectorAll("[data-action]").forEach(b=>b.disabled=!!s.busy||!s.active);statusFailures=0;$("dashboard").hidden=false;$("uploadCard").hidden=false;showError("errorDash","");
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
function renderRoom(room){const people=$("people");people.replaceChildren();if(room&&room.participants)for(const person of room.participants){const chip=document.createElement("span");chip.className="person"+(person.online?"":" offline");const avatar=document.createElement("span");avatar.className="avatar";avatar.style.background=person.color;avatar.textContent=initials(person.name);const name=document.createElement("span");name.textContent=person.name+(room.me&&room.me.id===person.id?" (you)":"");chip.append(avatar,name);people.append(chip)}const activity=$("activity");activity.replaceChildren();if(room&&room.activity)for(const event of [...room.activity].slice(-12).reverse()){const line=document.createElement("div");line.className="ev";const time=document.createElement("time");time.textContent=new Date(event.at*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});const text=document.createElement("span");text.textContent=describe(event);line.append(time,text);activity.append(line)}}
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
function describe(event){const name=(event.data&&event.data.name)||"Someone";switch(event.type){case "joined":return name+(event.data.reconnected?" reconnected":" joined");case "left":return name+" left";case "renamed":return "You are now "+name;case "voted":return name+" voted on a film";case "action":return name+" used "+(event.data.action||"a control").replaceAll("_"," ");default:return name+" updated the room"}}
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
  }catch(err){showError("errorDash",err.message)}
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
$("clearQueue").addEventListener("click",()=>act("queue_clear"));
document.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",()=>act(b.dataset.action)));
for(const id of ["seek","volume"]){
  const control=$(id);
  control.addEventListener("pointerdown",()=>editingControls.add(id));
  control.addEventListener("input",()=>editingControls.add(id));
  control.addEventListener("pointercancel",()=>editingControls.delete(id));
  control.addEventListener("blur",()=>editingControls.delete(id));
}
$("seek").addEventListener("change",()=>{
  const value=Number($("seek").value);
  editingControls.delete("seek");
  act("seek",value);
});
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
$("nameForm").addEventListener("submit",async e=>{e.preventDefault();try{const d=await post("/api/profile",{name:$("displayName").value});$("displayName").value=d.participant.name;showError("errorDash","Display name updated");refresh()}catch(err){showError("errorDash",err.message)}});
$("musicAutogain").addEventListener("change",()=>act("music_autogain",$("musicAutogain").checked));
async function uploadRequest(method,path,body,headers={}){
  if(stalePage)throw Error("Reload required");
  if(!csrf)throw Object.assign(Error("Room access expired"),{status:401});
  const controller=new AbortController();activeUploadController=controller;
  const deadline=setTimeout(()=>controller.abort(),60000);
  try{
    const response=await fetch(path,{method,credentials:"same-origin",cache:"no-store",headers:{"X-CSRF-Token":csrf,...clientHeaders,...headers},body,signal:controller.signal});
    const data=await response.json();
    if(data.code==="client_reload_required")showUpdateNotice();
    if(!response.ok)throw Object.assign(Error(response.status===429?"Upload requests are busy. Retrying shortly…":data.error||"Upload request failed"),{status:response.status,retryAfter:Math.max(1,Number(response.headers.get("Retry-After"))||1)});
    return data;
  }finally{clearTimeout(deadline);if(activeUploadController===controller)activeUploadController=null}
}
async function sendChunk(path,file,offset,end){
  const body=file.slice(offset,end),headers={"Content-Type":"application/octet-stream","Content-Range":`bytes ${offset}-${end-1}/${file.size}`};
  for(let attempt=0;;attempt++){
    if(cancelUpload)throw Error("Upload cancelled");
    try{return await uploadRequest("PUT",path,body,headers)}catch(error){
      if(error.status&&error.status<500&&error.status!==409&&error.status!==429)throw error;
      if(attempt===4||cancelUpload||!csrf)throw error;
      showError("uploadStatus","Connection interrupted. Retrying…");
      await new Promise(resolve=>setTimeout(resolve,Math.max(250*2**attempt,(error.status===429?error.retryAfter:0)*1000)));
      if(cancelUpload)throw Error("Upload cancelled");
      try{const state=await uploadRequest("GET",path);if(state.received===end)return state}
      catch(statusError){if(statusError.status===404||statusError.status===401)throw statusError}
    }
  }
}
function updateUploadControls(){
  const file=batchFiles&&batchFiles[batchIndex]||$("videoFile").files[0],audio=file&&/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name);
  if(audio)$("uploadQueue").checked=true;
  $("uploadButton").disabled=uploading;$("uploadButton").textContent=pendingUpload?"Resume upload":(batchFiles?"Continue upload batch":($("uploadQueue").checked?"Upload and add":"Upload and cast"));
  $("videoFile").disabled=uploading||!!batchFiles;$("uploadQueue").disabled=uploading||!!batchFiles||!!audio;$("cancelUpload").hidden=!uploading&&!batchFiles;$("cancelUpload").disabled=cancelUpload;
}
function resetUploadBatch(){
  pendingUpload=null;
  batchFiles=null;
  batchIndex=0;
  $("videoFile").value="";
  $("uploadProgress").value=0;
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
  if(pendingUpload){try{await uploadRequest("DELETE",pendingUpload.path)}catch(error){if(error.status!==404)throw error}pendingUpload=null}
  batchFiles=null;batchIndex=0;
  showError("uploadStatus","Upload cancelled");
}
$("uploadButton").addEventListener("click",async()=>{
  if(uploading)return;
  if(!batchFiles){const selected=Array.from($("videoFile").files);if(!selected.length)return;batchFiles=selected;batchIndex=0;batchAdded=0;batchTotal=selected.length;batchQueueOnly=$("uploadQueue").checked}
  uploading=true;cancelUpload=false;updateUploadControls();const json={"Content-Type":"application/json"};
  try{
    while(batchIndex<batchFiles.length&&!cancelUpload){
      const file=batchFiles[batchIndex],audio=/\.(mp3|aac|m4a|flac|ogg|opus|wav|aiff|aif)$/i.test(file.name),queueOnly=audio||batchQueueOnly;let state;casting=false;
      if(pendingUpload){showError("uploadStatus",`Checking ${batchIndex+1}/${batchFiles.length}: ${file.name}…`);state=await uploadRequest("GET",pendingUpload.path)}
      else{showError("uploadStatus",`Preparing ${batchIndex+1}/${batchFiles.length}: ${file.name}…`);state=await uploadRequest("POST","/api/uploads",JSON.stringify({name:file.name,size:file.size,queue:queueOnly}),json);pendingUpload={path:"/api/uploads/"+state.id,chunkSize:state.chunk_size}}
      const {path,chunkSize}=pendingUpload;$("uploadProgress").max=file.size;$("uploadProgress").value=state.received;
      while(state.received<file.size&&!cancelUpload){const end=Math.min(state.received+chunkSize,file.size);state=await sendChunk(path,file,state.received,end);$("uploadProgress").value=state.received;if(state.ready_to_cast)casting=true;const percent=Math.floor(state.received*100/file.size);showError("uploadStatus",casting?`Casting ${file.name} — ${percent}% received`:`${batchIndex+1}/${batchFiles.length} · ${queueOnly?"Adding":"Uploading"} ${file.name}: ${percent}%`)}
      if(cancelUpload){await discardUpload();break}
      $("cancelUpload").disabled=true;const result=await uploadRequest("POST",path+"/complete",JSON.stringify({queue:queueOnly}),json);pendingUpload=null;batchIndex++;batchAdded++;showError("uploadStatus",result.message||`${file.name} added`);
    }
    if(batchFiles&&batchIndex>=batchFiles.length){const count=batchAdded,total=batchTotal;batchFiles=null;batchIndex=0;batchAdded=0;batchTotal=0;showError("uploadStatus",`${count} of ${total} files added`)}
  }catch(error){if(error.status===404)pendingUpload=null;if(error.status===413||error.status===422){pendingUpload=null;batchIndex++;if(batchIndex>=batchFiles.length){batchFiles=null;batchIndex=0;showError("uploadStatus",`${error.message} No files remain in this batch.`)}else showError("uploadStatus",`${error.message} Skipped this file; select Continue upload batch to add the rest.`)}else if(cancelUpload){try{await discardUpload()}catch(cancelError){showError("uploadStatus",cancelError.message)}}else showError("uploadStatus",pendingUpload?error.message+" Select Resume upload to retry.":error.message)}
  finally{finishUpload()}
});
$("uploadQueue").addEventListener("change",updateUploadControls);
$("videoFile").addEventListener("change",updateUploadControls);
$("cancelUpload").addEventListener("click",async()=>{
  cancelUpload=true;if(activeUploadController)activeUploadController.abort();$("cancelUpload").disabled=true;showError("uploadStatus","Cancelling upload…");if(uploading)return;
  uploading=true;updateUploadControls();try{await discardUpload()}catch(error){showError("uploadStatus",error.message)}
  finally{finishUpload()}
});
document.addEventListener("visibilitychange",()=>{
  if(document.hidden){clearTimeout(statusTimer);statusRequest?.abort("superseded");return}
  statusFailures=0;
  refresh();
});
window.addEventListener("online",()=>{statusFailures=0;refresh()});

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
    const local=(it.copies||[]).some(c=>c.origin==="local");
    if(!local){add.disabled=true;add.title="Playing from other computers is coming soon"}
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
      for(const it of g.items||[]){ul.append(item(it,g.type));n++}
      out.append(h,ul);
    }
    const pending=(d.pending_origins||[]).length;
    status.textContent=n?n+(n===1?" result":" results")+(pending?" - still checking "+pending+(pending===1?" computer":" computers"):""):
      (pending?"Still checking "+pending+(pending===1?" computer":" computers")+"...":"Nothing in the house matches "+JSON.stringify(input.value.trim())+".");
  }
  function stop(){if(source){source.close();source=null}if(controller){controller.abort();controller=null}}
  async function run(){
    stop();const q=input.value.trim();
    if(!q){out.replaceChildren();status.textContent="";return}
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
  input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(run,120)});
})();
</script></body></html>"""
