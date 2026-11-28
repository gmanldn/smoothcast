"""Screens: browsers that act as playback targets for the shared room.

Any phone, tablet, laptop or TV browser that has paired with the room can open
``/screen`` and become a *screen* (video) or *speaker* (audio). The host never
needs an app on that device. A screen is a target that is independent of the
Cast/DLNA receiver: controlling it never stops, replaces or re-owns the host's
own playback session.

This module is GTK-free and I/O-free. It owns:

* the bounded, expiring registry of screens;
* a per-screen ordered command mailbox (sequence numbers fence stale orders);
* direct-play versus host-transcode route selection from browser capability.

Trust boundaries: a screen is owned by the paired session that registered it.
Only that session may poll or report for it; any paired participant may send it
commands, exactly like the shared queue. Media is addressed only by the room's
opaque queue IDs; filesystem paths never appear here.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import math
import re
import threading
import time
from typing import Callable

MAX_SCREENS = 8
SCREEN_TTL = 30.0          # seconds without any poll/report before removal
STALE_AFTER = 12.0         # seconds without contact before "not ready"
MAX_NAME = 32
MAX_PENDING_ORDERS = 16
COMMAND_CACHE = 64
MAX_POSITION = 24 * 60 * 60
POLL_WAIT_MAX = 8.0

ACTIONS = frozenset({"play", "pause", "resume", "seek", "stop", "volume"})
STATES = frozenset({"idle", "loading", "playing", "paused", "buffering", "ended", "error"})
_ID = re.compile(r"^[a-f0-9]{8}$")
_ITEM = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_COMMAND_ID = re.compile(r"^[A-Za-z0-9:_.-]{1,128}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Container suffix -> (media kind, MIME type a browser reports it can play).
# A suffix is only a hint about the container; codec failures are reported by
# the browser at playback time and shown to the room honestly.
_SUFFIX_MIME: dict[str, tuple[str, str]] = {
    ".mp4": ("video", "video/mp4"), ".m4v": ("video", "video/mp4"),
    ".mov": ("video", "video/mp4"), ".webm": ("video", "video/webm"),
    ".mkv": ("video", "video/x-matroska"), ".ogv": ("video", "video/ogg"),
    ".avi": ("video", ""), ".wmv": ("video", ""), ".ts": ("video", ""),
    ".mpg": ("video", ""), ".mpeg": ("video", ""), ".flv": ("video", ""),
    ".m2ts": ("video", ""),
    ".mp3": ("audio", "audio/mpeg"), ".m4a": ("audio", "audio/mp4"),
    ".aac": ("audio", "audio/aac"), ".flac": ("audio", "audio/flac"),
    ".ogg": ("audio", "audio/ogg"), ".oga": ("audio", "audio/ogg"),
    ".opus": ("audio", "audio/ogg"), ".wav": ("audio", "audio/wav"),
    ".aiff": ("audio", ""), ".aif": ("audio", ""), ".wma": ("audio", ""),
}
# MIME types a screen may claim support for. Anything else is ignored.
KNOWN_MIMES = frozenset(mime for _kind, mime in _SUFFIX_MIME.values() if mime)


class ScreenError(Exception):
    """A safe rejection with an HTTP status and a user-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def media_kind(suffix: str) -> str | None:
    """Return ``video``/``audio`` for a known media suffix, else ``None``."""
    entry = _SUFFIX_MIME.get(str(suffix).lower())
    return entry[0] if entry else None


def direct_mime(suffix: str) -> str:
    """MIME type to serve for direct play, or ``""`` when never direct-played."""
    entry = _SUFFIX_MIME.get(str(suffix).lower())
    return entry[1] if entry else ""


@dataclass(frozen=True)
class Route:
    """How the host will deliver one item to one screen."""

    kind: str              # "video" or "audio"
    mode: str              # "direct" or "transcode"
    mime: str              # Content-Type the screen will receive
    reason: str = ""       # human sentence when transcoding is needed

    def public(self) -> dict:
        return {"kind": self.kind, "mode": self.mode, "mime": self.mime,
                "reason": self.reason}


def choose_route(suffix: str, capabilities: frozenset[str] | set[str],
                 *, can_transcode: bool) -> Route:
    """Pick direct play when the browser reports support; otherwise transcode.

    Raises ``ScreenError(415)`` with an actionable reason when neither works.
    """
    kind = media_kind(suffix)
    if kind is None:
        raise ScreenError(415, "That file type cannot be played on a screen")
    mime = direct_mime(suffix)
    if mime and mime in capabilities:
        return Route(kind, "direct", mime)
    if not can_transcode:
        raise ScreenError(
            415, "This screen cannot play that format and the host has no "
                 "FFmpeg to convert it")
    out_mime = "video/mp4" if kind == "video" else "audio/mp4"
    why = ("This screen's browser cannot play the original format, so the host "
           "converts it on the fly.")
    return Route(kind, "transcode", out_mime, why)


def clean_name(value: object, fallback: str = "Screen") -> str:
    """Printable, bounded display name."""
    if not isinstance(value, str):
        return fallback
    text = _CONTROL.sub("", value).strip()
    text = re.sub(r"\s+", " ", text)[:MAX_NAME].strip()
    return text or fallback


def clean_text(value: object, limit: int) -> str:
    """Printable single-line text bounded to *limit* characters."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", _CONTROL.sub("", value)).strip()[:limit]


def clean_capabilities(value: object) -> frozenset[str]:
    """Keep only well-known MIME types from an untrusted capability list."""
    if not isinstance(value, (list, tuple)):
        return frozenset()
    return frozenset(item for item in value[:64]
                     if isinstance(item, str) and item in KNOWN_MIMES)


def _number(value: object, upper: float = MAX_POSITION) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return min(number, upper)


@dataclass
class Screen:
    id: str
    name: str
    owner_key: str                  # hashed session key of the registering page
    owner_id: str                   # room participant id (for display only)
    capabilities: frozenset[str]
    registered: float
    last_seen: float
    state: str = "idle"
    position: float = 0.0
    duration: float = 0.0
    item: str = ""                  # queue ID currently loaded
    title: str = ""
    kind: str = ""                  # video/audio of the loaded item
    mode: str = ""                  # direct/transcode of the loaded item
    error: str = ""
    volume: int = 100
    follow: bool = False            # advance through the shared queue
    seq: int = 0                    # last order issued
    play_seq: int = 0               # seq of the last "play" order
    ack: int = 0                    # last order the screen says it applied
    orders: deque = field(default_factory=lambda: deque(maxlen=MAX_PENDING_ORDERS))
    commands: OrderedDict = field(default_factory=OrderedDict)

    def public(self, now: float) -> dict:
        age = max(0.0, now - self.last_seen)
        return {
            "id": self.id, "name": self.name, "ready": age <= STALE_AFTER,
            "state": self.state, "position": round(self.position, 1),
            "duration": round(self.duration, 1), "item": self.item,
            "title": self.title, "kind": self.kind, "mode": self.mode,
            "error": self.error, "volume": self.volume, "follow": self.follow,
            "video": "video/mp4" in self.capabilities
                     or "video/webm" in self.capabilities,
        }


class ScreenRegistry:
    """Thread-safe, bounded registry of browser screens for one room."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 can_transcode: Callable[[], bool] = lambda: True) -> None:
        self._clock = clock
        self._can_transcode = can_transcode
        self._cond = threading.Condition(threading.RLock())
        self._screens: dict[str, Screen] = {}
        self._ids = 0
        self._generation = 0   # bumps on any change; wakes long pollers

    # -- lifecycle -----------------------------------------------------------
    def _expire(self, now: float) -> None:
        for screen_id, screen in list(self._screens.items()):
            if now - screen.last_seen > SCREEN_TTL:
                self._screens.pop(screen_id, None)
                self._generation += 1

    def _new_id(self) -> str:
        import secrets
        while True:
            screen_id = secrets.token_hex(4)
            if screen_id not in self._screens:
                return screen_id

    def register(self, owner_key: str, owner_id: str, name: object,
                 capabilities: object, *, claim: object = None) -> Screen:
        """Create or re-claim this session's screen. One screen per session."""
        now = self._clock()
        caps = clean_capabilities(capabilities)
        clean = clean_name(name)
        with self._cond:
            self._expire(now)
            existing = None
            if isinstance(claim, str) and _ID.fullmatch(claim):
                candidate = self._screens.get(claim)
                if candidate is not None and candidate.owner_key == owner_key:
                    existing = candidate
            if existing is None:
                for candidate in self._screens.values():
                    if candidate.owner_key == owner_key:
                        existing = candidate
                        break
            if existing is not None:
                existing.name = self._unique_name(clean, except_id=existing.id)
                existing.capabilities = caps
                existing.last_seen = now
                self._generation += 1
                self._cond.notify_all()
                return existing
            if len(self._screens) >= MAX_SCREENS:
                raise ScreenError(409, "This room already has the maximum number "
                                       "of screens")
            screen = Screen(self._new_id(), self._unique_name(clean), owner_key,
                            owner_id, caps, now, now)
            self._screens[screen.id] = screen
            self._generation += 1
            self._cond.notify_all()
            return screen

    def _unique_name(self, name: str, *, except_id: str = "") -> str:
        taken = {s.name for s in self._screens.values() if s.id != except_id}
        if name not in taken:
            return name
        for number in range(2, 100):
            suffix = f" {number}"
            candidate = f"{name[:MAX_NAME - len(suffix)]}{suffix}"
            if candidate not in taken:
                return candidate
        return name

    def remove(self, screen_id: str, owner_key: str) -> bool:
        with self._cond:
            screen = self._screens.get(screen_id)
            if screen is None or screen.owner_key != owner_key:
                return False
            self._screens.pop(screen_id, None)
            self._generation += 1
            self._cond.notify_all()
            return True

    def drop_owner_keys(self, keys: set[str] | frozenset[str]) -> int:
        """Remove screens whose paired session was revoked or expired."""
        with self._cond:
            doomed = [sid for sid, s in self._screens.items()
                      if s.owner_key in keys]
            for sid in doomed:
                self._screens.pop(sid, None)
            if doomed:
                self._generation += 1
                self._cond.notify_all()
            return len(doomed)

    def retain_owner_keys(self, is_active: Callable[[str], bool]) -> int:
        """Drop screens whose session is no longer valid."""
        with self._cond:
            doomed = [sid for sid, s in self._screens.items()
                      if not is_active(s.owner_key)]
            for sid in doomed:
                self._screens.pop(sid, None)
            if doomed:
                self._generation += 1
                self._cond.notify_all()
            return len(doomed)

    def close(self) -> None:
        with self._cond:
            self._screens.clear()
            self._generation += 1
            self._cond.notify_all()

    # -- reads ---------------------------------------------------------------
    def snapshot(self) -> list[dict]:
        now = self._clock()
        with self._cond:
            self._expire(now)
            return [s.public(now) for s in sorted(
                self._screens.values(), key=lambda s: (s.registered, s.id))]

    def get(self, screen_id: str) -> Screen | None:
        with self._cond:
            self._expire(self._clock())
            return self._screens.get(screen_id)

    def capabilities(self, screen_id: str) -> frozenset[str]:
        screen = self.get(screen_id)
        return screen.capabilities if screen is not None else frozenset()

    # -- screen side: poll and report ---------------------------------------
    def poll(self, screen_id: str, owner_key: str, since: int,
             wait: float = 0.0) -> dict:
        """Return orders newer than *since*; optionally long-poll up to *wait*.

        Polling counts as contact, so an idle screen stays registered.
        """
        deadline = self._clock() + max(0.0, min(wait, POLL_WAIT_MAX))
        with self._cond:
            while True:
                now = self._clock()
                self._expire(now)
                screen = self._screens.get(screen_id)
                if screen is None or screen.owner_key != owner_key:
                    raise ScreenError(404, "This screen is no longer registered")
                screen.last_seen = now
                pending = [dict(o) for o in screen.orders if o["seq"] > since]
                if pending or now >= deadline:
                    return {"seq": screen.seq, "orders": pending}
                self._cond.wait(timeout=min(0.5, max(0.0, deadline - now)))

    def report(self, screen_id: str, owner_key: str, report: dict) -> dict:
        """Record the screen's playback state. Returns follow-on information.

        ``advance`` is the finished item's ID when the screen is following the
        shared queue and an order newer than the finished play has not already
        replaced it; the caller decides what comes next.
        """
        if not isinstance(report, dict):
            raise ScreenError(400, "Report must be a JSON object")
        state = report.get("state")
        if state not in STATES:
            raise ScreenError(400, "Unknown playback state")
        now = self._clock()
        with self._cond:
            self._expire(now)
            screen = self._screens.get(screen_id)
            if screen is None or screen.owner_key != owner_key:
                raise ScreenError(404, "This screen is no longer registered")
            screen.last_seen = now
            ack = report.get("ack")
            if (isinstance(ack, int) and not isinstance(ack, bool)
                    and 0 <= ack <= screen.seq):
                screen.ack = max(screen.ack, ack)
            screen.position = _number(report.get("position")) or 0.0
            duration = _number(report.get("duration"))
            if duration is not None and duration > 0:
                screen.duration = duration
            volume = report.get("volume")
            if (isinstance(volume, int) and not isinstance(volume, bool)
                    and 0 <= volume <= 100):
                screen.volume = volume
            error = report.get("error")
            screen.error = clean_text(error, 120) if state == "error" else ""
            previous = screen.state
            # Only trust a report about the order currently in force; a late
            # report from an older play must not overwrite newer state.
            about = report.get("play_seq")
            current = (not isinstance(about, int) or isinstance(about, bool)
                       or about == screen.play_seq)
            advance = ""
            if current:
                screen.state = state
                if state == "ended" and previous != "ended" and screen.follow \
                        and screen.item:
                    advance = screen.item
            self._generation += 1
            self._cond.notify_all()
            return {"advance": advance, "play_seq": screen.play_seq}

    # -- controller side -----------------------------------------------------
    def command(self, screen_id: str, action: str, *, command_id: object = None,
                item: str = "", title: str = "", duration: float = 0.0,
                suffix: str = "", value: object = None,
                follow: bool = False, start: float = 0.0,
                expected_play_seq: int | None = None) -> dict:
        """Issue one fenced order to a screen; identical retries are idempotent."""
        if action not in ACTIONS:
            raise ScreenError(400, "Unsupported screen action")
        if command_id is not None and (
                not isinstance(command_id, str)
                or not _COMMAND_ID.fullmatch(command_id)):
            raise ScreenError(400, "Command ID is invalid")
        now = self._clock()
        with self._cond:
            self._expire(now)
            screen = self._screens.get(screen_id)
            if screen is None:
                raise ScreenError(404, "That screen is no longer here")
            if (expected_play_seq is not None
                    and screen.play_seq != expected_play_seq):
                raise ScreenError(409, "Playback changed before the next item could start")
            if command_id is not None and command_id in screen.commands:
                screen.commands.move_to_end(command_id)
                return dict(screen.commands[command_id])
            if now - screen.last_seen > STALE_AFTER:
                raise ScreenError(409, "That screen is not responding right now")
            order: dict = {"kind": action}
            if action == "play":
                if not _ITEM.fullmatch(item or ""):
                    raise ScreenError(400, "Choose something from the queue")
                route = choose_route(suffix, screen.capabilities,
                                     can_transcode=self._can_transcode())
                begin = _number(start) or 0.0
                base = f"/api/media/{item}"
                convert = f"{base}?mode=transcode" if self._can_transcode() else ""
                order.update(item=item, title=clean_name(title, "Untitled"),
                             duration=round(float(duration or 0.0), 1),
                             start=begin, route=route.public(),
                             url=convert if route.mode == "transcode" else base,
                             # Used by the screen if the browser accepts the
                             # container but cannot decode its codecs.
                             fallback=convert if route.mode == "direct" else "",
                             follow=bool(follow))
            elif action == "seek":
                position = _number(value)
                if position is None:
                    raise ScreenError(400, "Seek position must be a number")
                order["value"] = position
            elif action == "volume":
                if (isinstance(value, bool) or not isinstance(value, int)
                        or not 0 <= value <= 100):
                    raise ScreenError(400, "Volume must be from 0 to 100")
                order["value"] = value
            elif action in {"pause", "resume"} and not screen.item:
                raise ScreenError(409, "Nothing is playing on that screen")
            screen.seq += 1
            order["seq"] = screen.seq
            if action == "play":
                screen.play_seq = screen.seq
                screen.item = order["item"]
                screen.title = order["title"]
                screen.kind = order["route"]["kind"]
                screen.mode = order["route"]["mode"]
                screen.duration = order["duration"]
                screen.position = order["start"]
                screen.state = "loading"
                screen.error = ""
                screen.follow = order["follow"]
            elif action == "stop":
                screen.play_seq = screen.seq
                screen.follow = False
                screen.state = "idle"
                screen.item = screen.title = screen.kind = screen.mode = ""
                screen.position = screen.duration = 0.0
            screen.orders.append(order)
            receipt = {"ok": True, "seq": screen.seq, "screen": screen.id}
            if command_id is not None:
                screen.commands[command_id] = receipt
                while len(screen.commands) > COMMAND_CACHE:
                    screen.commands.popitem(last=False)
            self._generation += 1
            self._cond.notify_all()
            return dict(receipt)
