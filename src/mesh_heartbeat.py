"""Dedicated mesh heartbeat thread.

One small coordinator thread per running mesh watches the read-only mesh view and
publishes a single heartbeat describing the *first node up* — the mesh primary, the
"real master" — and what the mesh is doing. It owns no sockets, casts or receivers:
it only reads a detached sample of the mesh, so a failure can never stop the mesh,
block playback or touch a receiver.

The heartbeat is process-local and therefore resets whenever the application
(``sc.py``) starts: a restart cleanly re-initialises the sequence and epoch, and a
mesh restart (interface change) starts a fresh coordinator. The thread is a daemon
and every read is wrapped, so a raising sample is counted and skipped instead of
ending the thread. GTK-free and clock-injectable.
"""
from __future__ import annotations

from collections.abc import Callable
import secrets
import threading
import time
from typing import Any

INTERVAL_S = 1.0
JOIN_TIMEOUT_S = 1.5
MAX_ACTIVITIES = 6

_STATE_TEXT = {"up": "Up", "no_primary": "Waiting for the first node",
               "mesh_off": "Mesh off", "unavailable": "Unavailable",
               "stopped": "Stopped", "starting": "Starting"}
_SERVICE_STATE = {"stopped": "stopped", "disabled": "mesh_off",
                  "unavailable": "unavailable"}


class HeartbeatCoordinator:
    """Emit a sequenced heartbeat from the mesh primary on its own thread.

    *sample* returns the raw observation dict (see ``MeshService._heartbeat_sample``);
    the coordinator adds the sequence, epoch, timing and robustness.
    """

    def __init__(self, *, sample: Callable[[], dict[str, Any]],
                 interval_s: float = INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 on_error: Callable[[BaseException], None] | None = None) -> None:
        self._sample = sample
        self._interval = max(0.05, float(interval_s))
        self._clock = clock
        self._wall = wall
        self._on_error = on_error
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.epoch = secrets.token_hex(4)
        self.seq = 0
        self.errors = 0
        self.last_error = ""
        self._started_mono = 0.0
        self._primary_id: str | None = None
        self._primary_since = 0.0
        self._snapshot: dict[str, Any] = _starting_snapshot(self.epoch)

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_mono = self._clock()
        self._primary_id = None
        self._primary_since = self._started_mono
        try:
            self.beat()                   # first heartbeat is available immediately
        except Exception as exc:          # a bad first sample must not stop startup
            self._record_error(exc)
        self._thread = threading.Thread(target=self._loop, name="smoothcast-mesh-heartbeat",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            try:
                thread.join(JOIN_TIMEOUT_S)
            except (RuntimeError, ValueError):
                pass

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # -- read -----------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Detached heartbeat with a monotonic age since the last beat."""
        with self._lock:
            beat = dict(self._snapshot)
        at = beat.pop("_at", None)
        beat["age_ms"] = (max(0, int((self._clock() - at) * 1000))
                          if isinstance(at, (int, float)) else 0)
        return beat

    # -- internals ------------------------------------------------------------
    def beat(self) -> None:
        """Sample the mesh once and publish a new heartbeat. Never raises into callers."""
        now = self._clock()
        raw = self._sample()
        raw = raw if isinstance(raw, dict) else {}
        primary_id = raw.get("primary_id") or None
        if primary_id != self._primary_id:
            self._primary_id = primary_id
            self._primary_since = now
        mesh_state = str(raw.get("mesh_state", "running"))
        if mesh_state != "running":
            state = _SERVICE_STATE.get(mesh_state, mesh_state)
        elif primary_id is None:
            state = "no_primary"
        else:
            state = "up"
        self.seq += 1
        beat = {
            "_at": now,
            "epoch": self.epoch,
            "seq": self.seq,
            "state": state,
            "at": self._wall(),
            "uptime_s": max(0, int(now - self._started_mono)),
            "errors": self.errors,
            "primary": None if primary_id is None else {
                "id": primary_id,
                "name": str(raw.get("primary_name") or ""),
                "self": bool(raw.get("primary_self")),
                "for_s": max(0, int(now - self._primary_since)),
            },
            "nodes": _count(raw.get("nodes")),
            "targets": _count(raw.get("targets")),
            "targets_ready": _count(raw.get("targets_ready")),
            "clients": _count(raw.get("clients")),
            "generation": _count(raw.get("generation")),
            "activities": _activities(raw.get("activities")),
        }
        with self._lock:
            self._snapshot = beat

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self._interval):
                return
            try:
                self.beat()
            except Exception as exc:          # a bad sample must never end the thread
                self._record_error(exc)

    def _record_error(self, exc: BaseException) -> None:
        self.errors += 1
        self.last_error = f"{type(exc).__name__}: {exc}"[:200]
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                pass


def _starting_snapshot(epoch: str) -> dict[str, Any]:
    return {"_at": None, "epoch": epoch, "seq": 0, "state": "starting", "at": 0.0,
            "uptime_s": 0, "errors": 0, "primary": None, "nodes": 0, "targets": 0,
            "targets_ready": 0, "clients": 0, "generation": 0, "activities": []}


def _count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(number, 1_000_000))


def _activities(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item[:80] for item in value if isinstance(item, str) and item][:MAX_ACTIVITIES]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _uptime(seconds: Any) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {(seconds % 3600) // 60} min"


def describe(beat: dict[str, Any] | None) -> dict[str, str]:
    """Turn a heartbeat into display text shared by the GTK Info card and tests."""
    if not isinstance(beat, dict):
        return {"primary": "—", "state": "Mesh off", "beat": "—", "uptime": "—",
                "mesh": "—", "activity": "No mesh is running on this device."}
    primary = beat.get("primary")
    if not isinstance(primary, dict):
        who = "None yet"
    elif primary.get("self"):
        who = "This device"
    else:
        who = str(primary.get("name") or "A node")
    age_ms = beat.get("age_ms")
    seq = beat.get("seq")
    age = ("just now" if not isinstance(age_ms, int) or age_ms < 1500
           else f"{age_ms // 1000} s ago")
    beat_text = f"#{seq} · {age}" if isinstance(seq, int) else age
    nodes, targets, ready, clients = (_count(beat.get("nodes")), _count(beat.get("targets")),
                                      _count(beat.get("targets_ready")), _count(beat.get("clients")))
    mesh_text = (f"{_plural(nodes, 'node')} · {ready} of {_plural(targets, 'receiver')} ready"
                 f" · {_plural(clients, 'client')}")
    activities = beat.get("activities")
    activity = str(activities[0]) if isinstance(activities, list) and activities else ""
    return {"primary": who, "state": _STATE_TEXT.get(str(beat.get("state")),
                                                     str(beat.get("state") or "Unknown")),
            "beat": beat_text, "uptime": _uptime(beat.get("uptime_s")),
            "mesh": mesh_text, "activity": activity}


__all__ = ["HeartbeatCoordinator", "describe"]
