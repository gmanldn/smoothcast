"""Web clients as first-class members of the mesh (ticket #402, "M9").

* ``client_summaries`` / ``screen_targets`` turn the portal's room roster and
  screen registry into the ``clients`` and ``targets`` sections a node publishes,
  so every full node sees who is connected where and which browser screens can
  be driven (routed through the node they registered with).
* ``MeshFeed`` is the bounded, versioned live channel browsers read: a snapshot
  on connect, then coalesced deltas with monotonic event ids scoped to this feed's
  generation, ``Last-Event-ID`` resume from a bounded ring, and a full snapshot on
  any gap. Each change is encoded **once** and shared by every stream, so work per
  change is O(1) in the number of browsers and a slow browser costs nothing: it is
  simply told to take a snapshot. Guests only ever receive the guest tier of each
  record (identity, usable targets, a client *count*), never other nodes' client
  names, edges, sources or addresses.

GTK-free. Design: docs/MESH_DESIGN.md ("Web clients").
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
import hashlib
import json
import secrets
import threading
from typing import Any

import mesh_model as mm
from mesh_state import Delta, MeshView, ViewPublisher

MAX_STREAMS = 64
MAX_STREAMS_PER_KEY = 3
RING = 128
KEEPALIVE = b": keepalive\n\n"


def _opaque(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:20]


def client_summaries(participants: Iterable[dict[str, Any]],
                     screens: Iterable[dict[str, Any]]) -> tuple[mm.ClientSummary, ...]:
    """Roster + screen registry -> bounded client summaries with opaque ids."""
    out: dict[str, mm.ClientSummary] = {}
    for person in participants:
        if not isinstance(person, dict) or not person.get("online", True):
            continue
        ident = _opaque("p", str(person.get("id", "")))
        out[ident] = mm.ClientSummary(
            ident, "controller", (), 0,
            mm.clean_text(person.get("name"), mm.MAX_NAME, fallback="Guest"))
    for screen in screens:
        if not isinstance(screen, dict) or not screen.get("ready"):
            continue
        ident = _opaque("s", str(screen.get("id", "")))
        role = "screen" if screen.get("video") else "speaker"
        flags = ("playing",) if screen.get("state") == "playing" else ()
        out[ident] = mm.ClientSummary(
            ident, role, flags, 0,
            mm.clean_text(screen.get("name"), mm.MAX_NAME, fallback="Screen"))
    return tuple(sorted(out.values(), key=lambda c: c.id))[:mm.MAX_CLIENTS]


def screen_targets(screens: Iterable[dict[str, Any]]) -> tuple[mm.TargetObservation, ...]:
    """Ready browser screens as targets, id ``screen-<id>``; routed via this node."""
    targets = []
    for screen in screens:
        if not isinstance(screen, dict):
            continue
        sid = str(screen.get("id", ""))
        if not sid.isalnum():
            continue
        state = ("busy" if screen.get("state") in {"playing", "loading", "buffering"}
                 else "ready") if screen.get("ready") else "stale"
        formats = ("video/mp4", "audio/mpeg") if screen.get("video") else ("audio/mpeg",)
        targets.append(mm.TargetObservation(
            f"screen-{sid}", "screen",
            mm.clean_text(screen.get("name"), mm.MAX_NAME, fallback="Screen"),
            state=state, model="Browser", formats=formats))
    return tuple(sorted(targets, key=lambda t: t.id))[:mm.MAX_TARGETS]


def guest_snapshot(view: MeshView, primary: str | None = None) -> dict[str, Any]:
    return {"generation": view.generation, "local": view.local_id,
            "primary": primary or "",
            "nodes": [mm.guest_tier(record) for record in view.nodes]}


def _delta_wire(delta: Delta, view: MeshView) -> dict[str, Any]:
    changes = []
    for change in delta.changes:
        item: dict[str, Any] = {"kind": change.kind, "node_id": change.node_id,
                                "sections": list(change.sections)}
        record = view.node(change.node_id)
        if change.kind != "removed" and record is not None:
            item["node"] = mm.guest_tier(record)
        changes.append(item)
    return {"generation": delta.generation, "changes": changes}


class FeedFull(Exception):
    """Too many open mesh streams (globally or for one session)."""


class Stream:
    """One browser's cursor into the feed. Not thread-bound; poll from its handler."""

    def __init__(self, feed: MeshFeed, key: str, cursor: int, needs_snapshot: bool) -> None:
        self._feed = feed
        self.key = key
        self._cursor = cursor
        self._snapshot = needs_snapshot
        self.closed = False

    def poll(self) -> list[bytes]:
        """Frames not yet delivered: a snapshot, or in-order deltas."""
        if self.closed:
            return []
        frames, self._cursor, self._snapshot = self._feed._collect(
            self._cursor, self._snapshot)
        return frames

    def wait(self, timeout: float) -> bool:
        """Block until new frames exist (or timeout/close). Returns True if any."""
        return self._feed._wait(self, timeout)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._feed._release(self)


class MeshFeed:
    def __init__(self, publisher: ViewPublisher, *, generation: str | None = None,
                 history: int = RING, max_streams: int = MAX_STREAMS,
                 primary: Callable[[], str | None] = lambda: None) -> None:
        self._publisher = publisher
        self._primary = primary
        self.generation = generation or secrets.token_hex(4)
        self._cond = threading.Condition(threading.RLock())
        self._ring: deque[tuple[int, bytes]] = deque(maxlen=max(2, history))
        self._n = 0
        self._streams: list[Stream] = []
        self._max = max_streams
        self._sub = publisher.subscribe(limit=256, on_ready=self.pump)
        self.pump()
        self._closed = False

    # -- producer side (mesh loop thread) -----------------------------------------
    def pump(self) -> None:
        """Drain the publisher subscription into the shared ring and wake streams."""
        with self._cond:
            for item in self._sub.poll():
                if isinstance(item, Delta):
                    body = _delta_wire(item, self._publisher.view)
                    body["primary"] = self._primary() or ""
                    self._append("delta", body)
                else:
                    self._n += 0            # a snapshot request is served on demand
            self._cond.notify_all()

    def _append(self, kind: str, body: dict[str, Any]) -> None:
        self._n += 1
        data = json.dumps({"type": kind, **body}, separators=(",", ":"))
        frame = (f"id: {self.generation}:{self._n}\nevent: mesh\ndata: {data}\n\n").encode()
        self._ring.append((self._n, frame))

    def _snapshot_frame(self) -> bytes:
        data = json.dumps({"type": "snapshot",
                           **guest_snapshot(self._publisher.view, self._primary())},
                          separators=(",", ":"))
        return (f"id: {self.generation}:{self._n}\nevent: mesh\ndata: {data}\n\n").encode()

    # -- consumer side -------------------------------------------------------------------
    def open(self, key: str, last_event_id: str | None = None) -> Stream:
        with self._cond:
            if len(self._streams) >= self._max or sum(
                    1 for s in self._streams if s.key == key) >= MAX_STREAMS_PER_KEY:
                raise FeedFull("too many mesh streams")
            cursor, snapshot = self._n, True
            gen, _, num = (last_event_id or "").partition(":")
            if gen == self.generation and num.isdigit():
                n = int(num)
                oldest = self._ring[0][0] if self._ring else self._n + 1
                if n <= self._n and n >= oldest - 1:
                    cursor, snapshot = n, False
            stream = Stream(self, key, cursor, snapshot)
            self._streams.append(stream)
            return stream

    def _collect(self, cursor: int, snapshot: bool) -> tuple[list[bytes], int, bool]:
        with self._cond:
            oldest = self._ring[0][0] if self._ring else self._n + 1
            if snapshot or (cursor < self._n and cursor < oldest - 1):
                return [self._snapshot_frame()], self._n, False
            return [frame for n, frame in self._ring if n > cursor], self._n, False

    def _wait(self, stream: Stream, timeout: float) -> bool:
        with self._cond:
            if stream.closed:
                return False
            if stream._snapshot or stream._cursor < self._n:
                return True
            self._cond.wait(timeout)
            return not stream.closed and (stream._cursor < self._n)

    def _release(self, stream: Stream) -> None:
        with self._cond:
            if stream in self._streams:
                self._streams.remove(stream)
            self._cond.notify_all()

    def close_keys(self, keys: Iterable[str]) -> int:
        """Revocation: drop every stream owned by these session keys at once."""
        doomed = set(keys)
        with self._cond:
            victims = [s for s in self._streams if s.key in doomed]
        for stream in victims:
            stream.close()
        return len(victims)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            for stream in list(self._streams):
                stream.close()
            self._sub.close()

    @property
    def stream_count(self) -> int:
        with self._cond:
            return len(self._streams)

    @property
    def last_event(self) -> int:
        return self._n


__all__ = ["FeedFull", "MeshFeed", "Stream", "client_summaries", "guest_snapshot",
           "screen_targets"]
