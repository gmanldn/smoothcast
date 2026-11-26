"""Always-on house coordinator ("sc-core").

Started on every launch — including a bare ZIP download run with no install —
this keeps the mesh alive on a private LAN so other nodes and web clients join
the house automatically (VISION: trusted home LAN, "discovery is membership").
One daemon thread samples a bounded, read-only snapshot of what the house is
doing: mesh state, nodes, receivers, web clients and what is being cast.

It is deliberately tiny and defensive. It owns no sockets, casts or receivers,
never imports GTK, never raises and self-heals a stopped mesh instead of acting
on playback (design principle: observation never acts). It only ever calls the
existing ``cast_mesh`` hook, which itself is failure-proof.
"""
from __future__ import annotations

from collections.abc import Callable
import secrets
import threading
import time
from typing import Any

import lan_interfaces

INTERVAL_S = 3.0
JOIN_TIMEOUT_S = 2.0
MAX_ACTIVITIES = 4
_MAX_TEXT = 64


class ScCore:
    """Coordinate the mesh from one small, robust daemon thread.

    *resolve* returns a private LAN address or None (no sockets are opened while
    it is None). *mesh_start* is the existing ``cast_mesh.start`` hook, injectable
    for tests. Reads only detached values, so it can never block or disturb GTK.
    """

    def __init__(self, window: object, *, interval_s: float = INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 resolve: Callable[[], str | None] | None = None,
                 mesh_start: Callable[[object, str], None] | None = None) -> None:
        self._window = window
        self._interval = max(0.5, float(interval_s))
        self._clock = clock
        self._wall = wall
        self._resolve = resolve or lan_interfaces.select_private_lan_ip
        self._mesh_start = mesh_start
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.epoch = secrets.token_hex(4)
        self.seq = 0
        self.errors = 0
        self.last_error = ""
        self._started_mono = 0.0
        self._snapshot: dict[str, Any] = _starting_snapshot(self.epoch)

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> "ScCore":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._started_mono = self._clock()
        try:
            self.tick()                   # first snapshot is available immediately
        except Exception as exc:          # a bad first tick must not stop startup
            self._record_error(exc)
        self._thread = threading.Thread(target=self._loop, name="smoothcast-sc-core",
                                        daemon=True)
        self._thread.start()
        return self

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
        """Detached house snapshot with a monotonic age since the last tick."""
        with self._lock:
            beat = dict(self._snapshot)
        at = beat.pop("_at", None)
        beat["age_ms"] = (max(0, int((self._clock() - at) * 1000))
                          if isinstance(at, (int, float)) else 0)
        return beat

    # -- internals ------------------------------------------------------------
    def tick(self) -> None:
        """Resolve the LAN, keep the mesh alive and publish one snapshot. Never raises."""
        now = self._clock()
        address: str | None = None
        try:
            resolved = self._resolve()
            address = resolved if isinstance(resolved, str) and resolved else None
        except Exception as exc:
            self._record_error(exc)
        if address is not None and not getattr(self._window, "_closing", False):
            try:
                self._ensure_mesh(address)
            except Exception as exc:
                self._record_error(exc)
        beat = self._sample(address, now)
        with self._lock:
            self._snapshot = beat

    def _ensure_mesh(self, address: str) -> None:
        """Start (or restart) the mesh only when it is not already running."""
        service = getattr(self._window, "_mesh", None)
        if service is not None and getattr(service, "state", "") == "running":
            return
        start = self._mesh_start
        if start is None:
            import cast_mesh
            start = cast_mesh.start
        start(self._window, address)

    def _sample(self, address: str | None, now: float) -> dict[str, Any]:
        self.seq += 1
        return {
            "_at": now,
            "epoch": self.epoch,
            "seq": self.seq,
            "at": self._wall(),
            "uptime_s": max(0, int(now - self._started_mono)),
            "errors": self.errors,
            "address": address,
            "mesh": _mesh_summary(getattr(self._window, "_mesh", None)),
            "cast": _cast_summary(self._window),
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self._interval):
                return
            try:
                self.tick()
            except Exception as exc:      # a bad tick must never end the thread
                self._record_error(exc)

    def _record_error(self, exc: BaseException) -> None:
        self.errors += 1
        self.last_error = f"{type(exc).__name__}: {exc}"[:200]


def start(window: object) -> ScCore:
    """Start the always-on coordinator for *window* (restarting any previous one)."""
    stop(window)
    core = ScCore(window)
    window._sc_core = core                  # type: ignore[attr-defined]
    return core.start()


def stop(window: object) -> None:
    """Stop the coordinator for *window*; never raises."""
    core = getattr(window, "_sc_core", None)
    window._sc_core = None                  # type: ignore[attr-defined]
    if core is not None:
        try:
            core.stop()
        except Exception:
            pass


def snapshot(window: object) -> dict[str, Any] | None:
    """Latest house snapshot for *window*, or None when the core is not running."""
    core = getattr(window, "_sc_core", None)
    if core is None:
        return None
    try:
        return core.snapshot()
    except Exception:
        return None


def _starting_snapshot(epoch: str) -> dict[str, Any]:
    return {"_at": None, "epoch": epoch, "seq": 0, "at": 0.0, "uptime_s": 0,
            "errors": 0, "address": None, "mesh": _mesh_summary(None),
            "cast": {"active": False, "state": "", "mode": "", "target": ""}}


def _mesh_summary(service: object) -> dict[str, Any]:
    """Bounded view of the mesh: nodes, receivers and attached web clients."""
    if service is None:
        return {"state": "off", "nodes": 0, "receivers": 0,
                "receivers_ready": 0, "clients": 0, "activities": []}
    try:
        state = str((service.status() or {}).get("state") or "unknown")
    except Exception:
        state = "unknown"
    beat: Any = None
    try:
        beat = service.heartbeat_snapshot()
    except Exception:
        beat = None
    beat = beat if isinstance(beat, dict) else {}
    return {
        "state": state[:24],
        "nodes": _count(beat.get("nodes")),
        "receivers": _count(beat.get("targets")),
        "receivers_ready": _count(beat.get("targets_ready")),
        "clients": _count(beat.get("clients")),
        "activities": _activities(beat.get("activities")),
    }


def _cast_summary(window: object) -> dict[str, Any]:
    """What the house is casting, read from the GTK-published status (thread-safe)."""
    snapshot = getattr(window, "_core_status", None)
    read = getattr(snapshot, "read", None)
    state: Any = None
    try:
        state = read() if callable(read) else None
    except Exception:
        state = None
    state = state if isinstance(state, dict) else {}
    return {
        "active": bool(state.get("active")),
        "state": str(state.get("state") or "")[:_MAX_TEXT],
        "mode": str(state.get("mode") or "")[:_MAX_TEXT],
        "target": str(state.get("target") or "")[:_MAX_TEXT],
    }


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


__all__ = ["ScCore", "start", "stop", "snapshot"]
