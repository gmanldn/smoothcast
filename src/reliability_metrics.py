"""Private, bounded session reliability summaries.

The event recorder is in-memory and GTK-free. Persistence and diagnostic export
are explicit so callers can run disk work in an existing background worker.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

SCHEMA_VERSION = 1
MAX_SUMMARIES = 100
MAX_AGE_DAYS = 30
MAX_FILE_BYTES = 128 * 1024
_STORE_LOCK = threading.Lock()
STATES = frozenset({"PLAYING", "BUFFERING", "PAUSED", "IDLE", "OFFLINE", "UNKNOWN"})
PROTOCOLS = frozenset({"cast", "dlna"})
MODES = frozenset({"direct", "transcode", "dlna", "unknown"})
OUTCOMES = frozenset({"completed", "stopped", "replaced", "failed", "interrupted"})


class SessionMetrics:
    """Collect monotonic event durations without reading GUI or receiver data."""

    def __init__(self, protocol: str, *, started: float | None = None,
                 wall_time: float | None = None) -> None:
        self.started = time.monotonic() if started is None else float(started)
        self.wall_time = time.time() if wall_time is None else float(wall_time)
        self.protocol = protocol if protocol in PROTOCOLS else "cast"
        self.mode = "unknown"
        self.encoder = "unknown"
        self._last_state: str | None = None
        self._last_state_at = self.started
        self._first_playing: float | None = None
        self._playing_s = 0.0
        self._buffering_s = 0.0
        self._rebuffer_count = 0
        self._seen_playing = False
        self._seek_started: float | None = None
        self._seek_latency_ms: list[float] = []

    def observe_state(self, state: str, *, now: float | None = None) -> None:
        """Account for the last observed state interval; unknown states are ignored."""
        if state not in STATES:
            return
        now = time.monotonic() if now is None else float(now)
        if now < self._last_state_at:
            return
        if self._last_state == "PLAYING":
            self._playing_s += now - self._last_state_at
        elif self._last_state == "BUFFERING":
            self._buffering_s += now - self._last_state_at
        if state == "PLAYING" and self._first_playing is None:
            self._first_playing = now
        if state == "BUFFERING" and self._seen_playing and self._last_state != "BUFFERING":
            self._rebuffer_count += 1
        if state == "PLAYING":
            self._seen_playing = True
        self._last_state = state
        self._last_state_at = now

    def begin_seek(self, *, now: float | None = None) -> None:
        self._seek_started = time.monotonic() if now is None else float(now)

    def confirm_seek(self, *, now: float | None = None) -> None:
        if self._seek_started is None:
            return
        now = time.monotonic() if now is None else float(now)
        if now >= self._seek_started:
            self._seek_latency_ms.append((now - self._seek_started) * 1000.0)
            self._seek_latency_ms = self._seek_latency_ms[-20:]
        self._seek_started = None

    def finish(self, outcome: str, *, now: float | None = None) -> dict:
        """Return a privacy-safe summary; absent measurements remain ``None``."""
        now = time.monotonic() if now is None else float(now)
        self.observe_state(self._last_state or "UNKNOWN", now=now)
        elapsed = max(0.0, now - self.started)
        denominator = self._playing_s + self._buffering_s
        return {
            "schema": SCHEMA_VERSION,
            "started_at": datetime.fromtimestamp(self.wall_time, timezone.utc).isoformat(),
            "duration_ms": round(elapsed * 1000.0),
            "protocol": self.protocol,
            "mode": self.mode if self.mode in MODES else "unknown",
            "encoder": self.encoder if self.encoder in {"software", "hardware", "unknown"} else "unknown",
            "outcome": outcome if outcome in OUTCOMES else "failed",
            "first_playing_ms": (round((self._first_playing - self.started) * 1000.0)
                                 if self._first_playing is not None else None),
            "playing_ms": round(self._playing_s * 1000.0),
            "buffering_ms": round(self._buffering_s * 1000.0),
            "stall_ratio": (round(self._buffering_s / denominator, 4) if denominator else None),
            "rebuffer_count": self._rebuffer_count,
            "seek_latency_ms": list(self._seek_latency_ms),
            "recovery_ms": None,
            "cpu_peak_percent": None,
            "rss_peak_bytes": None,
            "disk_written_bytes": None,
            "orphan_processes": None,
        }


def _safe_summary(value: object) -> dict | None:
    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA_VERSION:
        return None
    protocol, mode, outcome = value.get("protocol"), value.get("mode"), value.get("outcome")
    if protocol not in PROTOCOLS or mode not in MODES or outcome not in OUTCOMES:
        return None
    # Deliberately select fields. Paths, titles, receiver names/IPs, and future
    # unknown keys never cross the local metrics or diagnostic boundary.
    fields = (
        "schema", "started_at", "duration_ms", "protocol", "mode", "encoder",
        "outcome", "first_playing_ms", "playing_ms", "buffering_ms", "stall_ratio",
        "rebuffer_count", "seek_latency_ms", "recovery_ms", "cpu_peak_percent",
        "rss_peak_bytes", "disk_written_bytes", "orphan_processes",
    )
    safe = {key: value.get(key) for key in fields}
    try:
        started = datetime.fromisoformat(str(safe["started_at"]).replace("Z", "+00:00"))
        if started.tzinfo is None:
            return None
        if safe["encoder"] not in {"software", "hardware", "unknown"}:
            safe["encoder"] = "unknown"
        for key in ("duration_ms", "playing_ms", "buffering_ms", "rebuffer_count"):
            number = safe[key]
            if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                return None
        for key in ("first_playing_ms", "recovery_ms", "rss_peak_bytes", "disk_written_bytes",
                    "orphan_processes"):
            number = safe[key]
            if number is not None and (
                    isinstance(number, bool) or not isinstance(number, int) or number < 0):
                return None
        ratio = safe["stall_ratio"]
        if ratio is not None and (
                isinstance(ratio, bool) or not isinstance(ratio, (int, float))
                or not 0.0 <= ratio <= 1.0):
            return None
        cpu = safe["cpu_peak_percent"]
        if cpu is not None and (
                isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or cpu < 0):
            return None
        samples = safe["seek_latency_ms"]
        if not isinstance(samples, list) or len(samples) > 20 or any(
                isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0
                for item in samples):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return safe


def recent(path: str | Path | None = None, *, now: float | None = None) -> list[dict]:
    """Load bounded, allow-listed recent summaries; invalid files return empty."""
    target = Path(path) if path is not None else default_path()
    try:
        if target.stat().st_size > MAX_FILE_BYTES:
            return []
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_VERSION:
        return []
    rows = document.get("sessions")
    if not isinstance(rows, list):
        return []
    now = time.time() if now is None else float(now)
    cutoff = now - MAX_AGE_DAYS * 86400
    result = []
    for row in rows[-MAX_SUMMARIES:]:
        safe = _safe_summary(row)
        if safe is None:
            continue
        created = datetime.fromisoformat(safe["started_at"].replace("Z", "+00:00"))
        if created.timestamp() >= cutoff:
            result.append(safe)
    return result


def dashboard_summary(path: str | Path | None = None, *, now: float | None = None) -> dict:
    """Return an aggregate-only format for the local release dashboard hook."""
    rows = recent(path, now=now)
    first_playing = [row["first_playing_ms"] for row in rows
                     if row["first_playing_ms"] is not None]
    stalls = [row["stall_ratio"] for row in rows if row["stall_ratio"] is not None]
    return {
        "schema": SCHEMA_VERSION,
        "sample_count": len(rows),
        "outcomes": {key: sum(row["outcome"] == key for row in rows) for key in sorted(OUTCOMES)},
        "protocols": {key: sum(row["protocol"] == key for row in rows)
                      for key in sorted(PROTOCOLS)},
        "modes": {key: sum(row["mode"] == key for row in rows)
                  for key in sorted(MODES)},
        "median_first_playing_ms": (round(statistics.median(first_playing), 3)
                                    if first_playing else None),
        "median_stall_ratio": round(statistics.median(stalls), 4) if stalls else None,
    }


def append(summary: Mapping, path: str | Path | None = None, *, now: float | None = None) -> Path:
    """Atomically store one allow-listed summary with age/count/byte bounds."""
    with _STORE_LOCK:
        return _append_locked(summary, path, now=now)


def _append_locked(summary: Mapping, path: str | Path | None, *, now: float | None) -> Path:
    safe = _safe_summary(summary)
    if safe is None:
        raise ValueError("Invalid reliability summary")
    target = Path(path) if path is not None else default_path()
    rows = recent(target, now=now)
    rows.append(safe)
    document = {"schema": SCHEMA_VERSION, "sessions": rows[-MAX_SUMMARIES:]}
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("Reliability summary store exceeds its size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="wb", prefix=".reliability-", suffix=".tmp",
                                         dir=target.parent, delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def submit(metrics: SessionMetrics | None, outcome: str, run) -> None:
    """Finalize in memory and queue the bounded atomic write off the UI thread."""
    if metrics is None:
        return
    summary = metrics.finish(outcome)
    run(lambda: append(summary), done=lambda _result: None,
        failed=lambda _message: None, domain="media")


def start_attempt(owner, protocol: str) -> None:
    owner._cast_attempt_metrics = SessionMetrics(protocol)


def fail_attempt(owner, run) -> None:
    submit(getattr(owner, "_cast_attempt_metrics", None), "failed", run)
    owner._cast_attempt_metrics = None


def accept_attempt(owner, session, run) -> None:
    finish_active(owner, "replaced", run)
    metrics = getattr(owner, "_cast_attempt_metrics", None)
    if metrics is not None:
        metrics.mode = session.mode
        metrics.encoder = (
            "software" if getattr(session, "used_software_fallback", False)
            else "hardware" if session.mode == "transcode" else "unknown"
        )
        owner._active_metrics = metrics
    owner._cast_attempt_metrics = None


def finish_active(owner, outcome: str, run) -> None:
    submit(getattr(owner, "_active_metrics", None), outcome, run)
    owner._active_metrics = None


def observe(owner, state: str) -> None:
    metrics = getattr(owner, "_active_metrics", None)
    if metrics is not None:
        metrics.observe_state(state)


def default_path() -> Path:
    """Return the per-user, local-only reliability store path."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys_platform() == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "cast-control" / "reliability.json"


def sys_platform() -> str:
    return sys.platform
