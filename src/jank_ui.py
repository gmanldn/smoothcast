"""GLib scheduling around the GTK-free jank detector (#442).

:class:`JankMonitor` posts the heartbeat from the GTK main loop and polls it from
a monitor thread, so the detector sees real main-loop gaps. The scheduling hooks
are injectable, which keeps the class unit-testable without GTK.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable

import jank_watchdog

BEAT_MS = 50
POLL_MS = 200
SMOKE_STALL_MS = 250.0


class JankMonitor:
    """Post the main-loop heartbeat and poll it from a monitor thread."""

    def __init__(self, *, threshold_ms: float = jank_watchdog.DEFAULT_THRESHOLD_MS,
                 beat_ms: int = BEAT_MS, poll_ms: int = POLL_MS,
                 timeout_add: Callable[[int, Callable[[], bool]], int] | None = None,
                 source_remove: Callable[[int], None] | None = None,
                 watchdog: object | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if timeout_add is None or source_remove is None:
            from gi.repository import GLib
            timeout_add = timeout_add or GLib.timeout_add
            source_remove = source_remove or GLib.source_remove
        self._timeout_add = timeout_add
        self._source_remove = source_remove
        self._beat_ms = int(beat_ms)
        self._poll_s = max(int(poll_ms), 1) / 1000.0
        self._clock = clock
        self.watchdog = (watchdog if watchdog is not None
                         else jank_watchdog.JankWatchdog(threshold_ms=threshold_ms,
                                                         clock=clock))
        self.max_lag_ms = 0.0
        self._beat_source: int | None = None
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin monitoring; safe to call once."""
        if self._stopped.is_set():
            return
        jank_watchdog.install(self.watchdog)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="jank-monitor",
                                            daemon=True)
            self._thread.start()
        if self._beat_source is None:
            self._beat_source = self._timeout_add(self._beat_ms, self._beat)

    def stop(self) -> None:
        """Stop the monitor and release the registry; never raises."""
        self._stopped.set()
        if self._beat_source is not None:
            try:
                self._source_remove(self._beat_source)
            except Exception:  # noqa: BLE001 - best-effort source removal
                pass
            self._beat_source = None
        if jank_watchdog.current() is self.watchdog:
            jank_watchdog.install(None)

    def smoke_stall(self) -> bool:
        """True when the isolated smoke saw a stall past its hard limit."""
        return self.max_lag_ms >= SMOKE_STALL_MS

    def _beat(self) -> bool:
        self.watchdog.beat()
        return not self._stopped.is_set()

    def _run(self) -> None:
        while not self._stopped.wait(self._poll_s):
            stall = self.watchdog.poll()
            if stall is not None:
                self.max_lag_ms = max(self.max_lag_ms, float(stall.lag_ms))


class JankMonitorMixin:
    """Start/stop the monitor and gate the isolated smoke (#442)."""

    jank_monitor: JankMonitor | None = None

    def _start_jank_monitor(self) -> None:
        if not jank_watchdog.enabled_from():
            return
        try:
            self.jank_monitor = JankMonitor()
            self.jank_monitor.start()
        except Exception as exc:  # noqa: BLE001 - monitoring must never keep the desktop from starting
            # Monitoring must never keep the desktop from starting.
            self.jank_monitor = None
            print(f"SmoothCast jank monitor unavailable: {exc}", file=sys.stderr)

    def _check_jank_gate(self) -> None:
        """Raise when the scripted journey stalled the main loop; else stop."""
        monitor = self.jank_monitor
        if monitor is None:
            return
        if monitor.smoke_stall():
            raise RuntimeError(
                f"main-loop stall over {jank_ui_smoke_limit():.0f} ms "
                f"({monitor.max_lag_ms:.0f} ms)")
        self._stop_jank_monitor()

    def _stop_jank_monitor(self) -> None:
        monitor = self.jank_monitor
        if monitor is not None:
            monitor.stop()
            self.jank_monitor = None


def jank_ui_smoke_limit() -> float:
    return SMOKE_STALL_MS
