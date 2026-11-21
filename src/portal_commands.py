"""Validated, fenced and idempotent LAN control commands.

The LAN portal accepts a bounded mutation envelope from each client.  Commands
are serialized through one dispatcher, de-duplicated per client request id and
fenced to the media generation they were created against.  This module is
deliberately GTK-free so the state machine and HTTP integration can be tested
without a display.

Bounds: command ids are 1-128 characters, client ids 1-64 characters, sessions
are 32 lowercase hex characters, revisions are non-negative 64-bit integers and
payloads are at most 16 JSON values.  Completed receipts live for 120 seconds
and at most 512 are retained per dispatcher.  At most 64 commands are admitted
at once and only one is applied at a time.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import secrets
import threading
import time
from typing import Callable

ACTIONS = frozenset({"play_pause", "stop", "seek", "volume", "mute", "music_autogain"})
CLIENT_ID_MAX = 64
COMMAND_ID_MAX = 128
SESSION_HEX_LENGTH = 32
REVISION_MAX = 2**63 - 1
MAX_PAYLOAD_VALUES = 16
COMMAND_TTL_SECONDS = 120.0
COMMAND_CACHE_CAPACITY = 512
COMMAND_QUEUE_CAPACITY = 64
COMMAND_WAIT_SECONDS = 5.0

_TOKEN = re.compile(r"[A-Za-z0-9:_.-]{1,128}\Z")
_SESSION = re.compile(r"[0-9a-f]{32}\Z")


class CommandError(Exception):
    """A safe command rejection carrying the current fence position."""

    def __init__(self, status: int, message: str, *, revision: int | None = None,
                 session_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.revision = revision
        self.session_id = session_id


@dataclass(frozen=True)
class MutationEnvelope:
    """One bounded, replay-safe remote mutation."""

    client_id: str
    command_id: str
    expected_session_id: str
    expected_revision: int
    action: str
    payload: dict

    def fingerprint(self) -> str:
        """Return a stable digest of every field that changes the effect."""
        canonical = json.dumps({
            "client_id": self.client_id,
            "command_id": self.command_id,
            "expected_session_id": self.expected_session_id,
            "expected_revision": self.expected_revision,
            "action": self.action,
            "payload": self.payload,
        }, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommandReceipt:
    """The durable result returned for a command id."""

    command_id: str
    session_id: str
    revision: int
    message: str


@dataclass
class _Entry:
    fingerprint: str
    created: float
    completed: bool = False
    receipt: CommandReceipt | None = None
    error: CommandError | None = None
    event: threading.Event = field(default_factory=threading.Event)


def _token(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise CommandError(400, f"{name} is invalid")
    if _TOKEN.fullmatch(value) is None:
        raise CommandError(400, f"{name} is invalid")
    return value


def _payload(action: str, value: object) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CommandError(400, "payload must be a JSON object")
    if len(value) > MAX_PAYLOAD_VALUES:
        raise CommandError(400, "payload is too large")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise CommandError(400, "payload must contain JSON values") from None
    if action == "seek":
        position = value.get("value")
        if isinstance(position, bool) or not isinstance(position, (int, float)):
            raise CommandError(400, "Seek position must be a number")
        if not math.isfinite(float(position)) or not 0 <= float(position) <= 24 * 60 * 60:
            raise CommandError(400, "Seek position is out of range")
        return {"value": float(position)}
    if action == "volume":
        level = value.get("value")
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100:
            raise CommandError(400, "Volume must be from 0 to 100")
        return {"value": level}
    if action == "music_autogain":
        if type(value.get("value")) is not bool:
            raise CommandError(400, "Music autogain must be on or off")
        return {"value": value["value"]}
    if value:
        raise CommandError(400, "This action does not accept a payload")
    return {}


def parse_envelope(body: object) -> MutationEnvelope | None:
    """Validate an envelope, or return ``None`` for the legacy solo request."""
    if not isinstance(body, dict):
        raise CommandError(400, "Request must be a JSON object")
    keys = set(body)
    envelope_keys = {"client_id", "command_id", "expected_session_id", "expected_revision"}
    present = envelope_keys & keys
    if not present:
        return None
    if present != envelope_keys:
        raise CommandError(400, "Incomplete command envelope")
    if keys - envelope_keys - {"action", "payload"}:
        raise CommandError(400, "Unsupported command field")
    action = body.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise CommandError(400, "Unsupported action")
    session_id = body.get("expected_session_id")
    if not isinstance(session_id, str) or _SESSION.fullmatch(session_id) is None:
        raise CommandError(400, "expected_session_id is invalid")
    revision = body.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or not 0 <= revision <= REVISION_MAX:
        raise CommandError(400, "expected_revision is invalid")
    return MutationEnvelope(
        client_id=_token(body.get("client_id"), "client_id", CLIENT_ID_MAX),
        command_id=_token(body.get("command_id"), "command_id", COMMAND_ID_MAX),
        expected_session_id=session_id,
        expected_revision=revision,
        action=action,
        payload=_payload(action, body.get("payload")),
    )


def legacy_envelope(body: object, fence: "CommandFence", *, client_id: str) -> MutationEnvelope:
    """Build an envelope for the existing solo PIN request shape."""
    if not isinstance(body, dict):
        raise CommandError(400, "Request must be a JSON object")
    action = body.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise CommandError(400, "Unsupported action")
    payload = _payload(action, {key: value for key, value in body.items() if key != "action"})
    session_id, revision, _owner = fence.snapshot()
    return MutationEnvelope(
        client_id=_token(client_id, "client_id", CLIENT_ID_MAX),
        command_id=secrets.token_hex(16),
        expected_session_id=session_id,
        expected_revision=revision,
        action=action,
        payload=payload,
    )


class CommandFence:
    """Opaque media-generation fence shared by the portal and the GUI."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 session_id: str | None = None,
                 generation: Callable[[], object] | None = None,
                 owner: Callable[[], str] | None = None) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._session_id = session_id or secrets.token_hex(16)
        self._revision = 0
        self._owner = ""
        self._generation = generation
        self._generation_value = generation() if generation is not None else None
        self._owner_provider = owner

    def _refresh_locked(self) -> None:
        changed = False
        if self._generation is not None:
            current = self._generation()
            if current != self._generation_value:
                self._generation_value = current
                changed = True
        if self._owner_provider is not None:
            current_owner = self._owner_provider()
            if current_owner != self._owner:
                self._owner = current_owner
                changed = True
        if changed:
            self._session_id = secrets.token_hex(16)
            self._revision += 1

    def snapshot(self) -> tuple[str, int, str]:
        with self._lock:
            self._refresh_locked()
            return self._session_id, self._revision, self._owner

    def rotate(self, *, owner: str = "") -> tuple[str, int, str]:
        """Start a new generation after a handoff, stop or device change."""
        with self._lock:
            self._session_id = secrets.token_hex(16)
            self._revision += 1
            self._owner = owner
            if self._generation is not None:
                self._generation_value = self._generation()
            return self._session_id, self._revision, self._owner

    def check(self, expected_session_id: str, expected_revision: int,
              *, owner: str | None = None) -> None:
        """Reject stale or foreign commands immediately before effects."""
        with self._lock:
            self._refresh_locked()
            stale = (expected_session_id != self._session_id
                     or expected_revision != self._revision)
            foreign = bool(owner is not None and self._owner and owner != self._owner)
            if stale or foreign:
                raise CommandError(
                    409, "This control session has expired; refresh the dashboard",
                    revision=self._revision, session_id=self._session_id)


class ParticipantRateLimiter:
    """Bounded, thread-safe token buckets per authenticated room identity.

    Route classes: read (16 burst, 4/s), mutation (12, 6/s) and upload
    (40, 20/s). Uploads have a higher ceiling so 2 MiB chunks do not
    needlessly stall ordinary phones. Buckets are LRU-bounded to 512.
    """

    DEFAULT_LIMITS = {
        "read": (16.0, 4.0),
        "mutation": (12.0, 6.0),
        "upload": (40.0, 20.0),
    }

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 limits: dict[str, tuple[float, float]] | None = None,
                 max_buckets: int = 512) -> None:
        self._clock = clock
        self._limits = dict(limits or self.DEFAULT_LIMITS)
        if max_buckets < 1 or any(cap < 1 or rate <= 0
                                   for cap, rate in self._limits.values()):
            raise ValueError("rate limit parameters must be positive")
        self._max_buckets = max_buckets
        self._lock = threading.Lock()
        self._buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()

    def retry_after(self, participant_id: str, route_class: str) -> float:
        """Consume one token, or return required delay in seconds (0 = allowed)."""
        capacity, rate = self._limits[route_class]
        now = self._clock()
        key = (participant_id, route_class)
        with self._lock:
            tokens, last = self._buckets.get(key, (capacity, now))
            tokens = min(capacity, tokens + max(0.0, now - last) * rate)
            if tokens >= 1:
                tokens -= 1
                retry = 0.0
            else:
                retry = (1 - tokens) / rate
            self._buckets[key] = (tokens, now)
            self._buckets.move_to_end(key)
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
            return retry


class CommandDispatcher:
    """One bounded serial dispatcher with per-client request-id replay."""

    def __init__(self, apply: Callable[[MutationEnvelope], CommandReceipt], *,
                 fence: CommandFence, clock: Callable[[], float] = time.monotonic,
                 ttl: float = COMMAND_TTL_SECONDS,
                 capacity: int = COMMAND_CACHE_CAPACITY,
                 queue_capacity: int = COMMAND_QUEUE_CAPACITY,
                 wait_seconds: float = COMMAND_WAIT_SECONDS,
                 per_client_cap: int = 2) -> None:
        self._apply = apply
        self.fence = fence
        self._clock = clock
        self._ttl = ttl
        self._capacity = capacity
        self._wait_seconds = wait_seconds
        self._lock = threading.Lock()
        self._execute_lock = threading.Lock()
        if per_client_cap < 1:
            raise ValueError("per-client command cap must be positive")
        self._per_client_cap = per_client_cap
        self._client_pending: dict[str, int] = {}
        self._slots = threading.BoundedSemaphore(queue_capacity)
        self._cache: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._closed = False

    def execute(self, envelope: MutationEnvelope, *,
                participant_key: str | None = None) -> CommandReceipt:
        """Apply once; bound competing requests per authenticated participant."""
        key = (envelope.client_id, envelope.command_id)
        owner = participant_key or envelope.client_id
        fingerprint = envelope.fingerprint()
        with self._lock:
            if self._closed:
                raise CommandError(503, "SmoothCast is shutting down")
            self._prune_locked()
            entry = self._cache.get(key)
            if entry is not None:
                if entry.fingerprint != fingerprint:
                    raise CommandError(
                        409, "Command ID was already used with different data",
                        revision=self.fence.snapshot()[1])
                self._cache.move_to_end(key)
                if entry.completed:
                    return self._replay(entry)
                waiter = entry
            else:
                if self._client_pending.get(owner, 0) >= self._per_client_cap:
                    raise CommandError(429, "Too many commands; try again shortly")
                waiter = None
                entry = _Entry(fingerprint=fingerprint, created=self._clock())
                self._client_pending[owner] = self._client_pending.get(owner, 0) + 1
                self._cache[key] = entry
                self._cache.move_to_end(key)
                self._evict_locked()
        if waiter is not None:
            if not waiter.event.wait(self._wait_seconds):
                raise CommandError(503, "SmoothCast did not respond in time",
                                   revision=self.fence.snapshot()[1])
            return self._replay(waiter)
        if not self._slots.acquire(blocking=False):
            error = CommandError(503, "Too many commands are waiting; try again",
                                 revision=self.fence.snapshot()[1])
            with self._lock:
                self._cache.pop(key, None)
                self._client_pending[owner] -= 1
                if not self._client_pending[owner]:
                    self._client_pending.pop(owner, None)
                entry.error = error
                entry.completed = True
                entry.event.set()
            raise error
        try:
            with self._execute_lock:
                receipt = self._apply(envelope)
            if not isinstance(receipt, CommandReceipt):
                raise CommandError(500, "Command did not return a receipt")
        except CommandError as exc:
            with self._lock:
                entry.error = exc
                entry.completed = True
                entry.event.set()
            raise
        except Exception as exc:
            error = CommandError(503, "SmoothCast could not accept that command",
                                 revision=self.fence.snapshot()[1])
            with self._lock:
                entry.error = error
                entry.completed = True
                entry.event.set()
            raise error from exc
        else:
            with self._lock:
                entry.receipt = receipt
                entry.completed = True
                entry.event.set()
            return receipt
        finally:
            self._slots.release()
            with self._lock:
                self._client_pending[owner] -= 1
                if not self._client_pending[owner]:
                    self._client_pending.pop(owner, None)

    def close(self) -> None:
        """Stop accepting work and release any waiting duplicate."""
        with self._lock:
            self._closed = True
            for entry in self._cache.values():
                if not entry.completed:
                    entry.error = CommandError(503, "SmoothCast is shutting down")
                    entry.completed = True
                    entry.event.set()
            self._cache.clear()

    @staticmethod
    def _replay(entry: _Entry) -> CommandReceipt:
        if entry.error is not None:
            error = entry.error
            raise CommandError(error.status, error.message,
                               revision=error.revision, session_id=error.session_id)
        if entry.receipt is None:
            raise CommandError(503, "Command result is unavailable")
        return entry.receipt

    def _prune_locked(self) -> None:
        now = self._clock()
        for key, entry in list(self._cache.items()):
            if entry.completed and now - entry.created >= self._ttl:
                self._cache.pop(key, None)

    def _evict_locked(self) -> None:
        while len(self._cache) > self._capacity:
            for key, entry in self._cache.items():
                if entry.completed:
                    self._cache.pop(key, None)
                    break
            else:
                break


def precheck(controller: object, fence: CommandFence | None,
             envelope: MutationEnvelope) -> None:
    """Reject stale or foreign commands before marshalling to the GUI thread."""
    if getattr(controller, "_closing", False):
        raise CommandError(503, "SmoothCast is shutting down")
    if fence is None:
        raise CommandError(503, "The LAN portal is not ready")
    fence.check(envelope.expected_session_id, envelope.expected_revision,
                owner=controller._device())


def run_mutation(controller: object, fence: CommandFence,
                 envelope: MutationEnvelope) -> CommandReceipt:
    """Check the fence and apply one action on the controller's own thread."""
    if getattr(controller, "_closing", False):
        raise CommandError(503, "SmoothCast is shutting down")
    fence.check(envelope.expected_session_id, envelope.expected_revision,
                owner=controller._device())
    revision = fence.snapshot()[1]
    if getattr(controller, "busy", False):
        raise CommandError(409, "SmoothCast is finishing another command", revision=revision)
    action = envelope.action
    if action == "play_pause":
        if not controller.play_button.get_sensitive():
            raise CommandError(409, "Playback is not available right now", revision=revision)
        controller.toggle_play()
        message = "Playback command sent; the dashboard will refresh with receiver state."
    elif action == "stop":
        if not controller.stop_button.get_sensitive():
            raise CommandError(409, "Nothing SmoothCast can stop right now", revision=revision)
        controller.stop_stream()
        message = "Stop requested; the dashboard will refresh with receiver state."
    elif action == "seek":
        if (controller.session is None or controller.external or not controller.tracker.known
                or controller.busy or not controller.tracker.duration):
            raise CommandError(409, "Seeking is not available for this stream", revision=revision)
        controller.seek_to(envelope.payload["value"])
        message = "Seek requested; the dashboard will refresh with receiver state."
    elif action == "volume":
        if controller.device_state == "OFFLINE" or not controller.volume_scale.get_sensitive():
            raise CommandError(409, "Receiver volume is unavailable", revision=revision)
        controller.volume_scale.set_value(envelope.payload["value"])
        message = "Volume change requested; the dashboard will refresh with receiver state."
    elif action == "mute":
        if (controller.device_state == "OFFLINE"
                or not controller.mute_button.get_sensitive()):
            raise CommandError(409, "Receiver mute is unavailable", revision=revision)
        controller.toggle_mute()
        message = "Mute change requested; the dashboard will refresh with receiver state."
    elif action == "music_autogain":
        message = controller._portal_apply_music_autogain(envelope.payload["value"])
    else:
        raise CommandError(400, "Unsupported action")
    session_id, revision, _owner = fence.snapshot()
    return CommandReceipt(envelope.command_id, session_id, revision, message)
