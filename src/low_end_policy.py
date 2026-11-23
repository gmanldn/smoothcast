"""Bounded, persisted software-encoding capacity policy for older CPUs (#515).

Never touches GTK, receiver state, media content or the network. A short
synthetic libx264 test runs *after first paint* on a daemon worker. A missing
or failed probe selects the conservative 720p/saver path, never a 1080p bet.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

import benchmark
import process_priority

SCHEMA = 1
HEADROOM = 1.3
SOURCE_FPS = 30.0
GOOD_TTL = 30 * 24 * 3600
FAILED_TTL = 2 * 3600
_lock = threading.Lock()
_running = False


def state_path() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "cast-control" / "low-end-probe.json"


def machine_key() -> str:
    """Opaque hardware/FFmpeg identity; no hostnames, paths or CPU serials persisted."""
    identity: list[str] = [platform.system(), platform.machine(),
                           str(os.cpu_count()), platform.processor()]
    ffmpeg = shutil.which("ffmpeg")
    try:
        if ffmpeg:
            info = Path(ffmpeg).stat()
            identity.extend([ffmpeg, str(info.st_size), str(info.st_mtime_ns)])
        else:
            identity.append("ffmpeg-unavailable")
    except OSError:
        identity.append("ffmpeg-unavailable")
    return hashlib.sha256("\0".join(identity).encode()).hexdigest()


def _valid_fps(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    speed = float(value)
    return speed if math.isfinite(speed) and 0 < speed < 10000 else None


def _record(path: Path, key: str, *, now: float | None = None) -> dict | None:
    try:
        # A corrupt/hostile cache must never allocate unbounded memory on GTK.
        if path.stat().st_size > 2048:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        now = time.time() if now is None else now
        if (not isinstance(data, dict) or data.get("schema") != SCHEMA
                or data.get("machine") != key
                or type(data.get("at")) not in (int, float)):
            return None
        elapsed = now - float(data["at"])
        speed = _valid_fps(data.get("fps"))
        if data.get("fps") is not None and speed is None:
            return None
        ttl = GOOD_TTL if speed is not None else FAILED_TTL
        return data if 0 <= elapsed <= ttl else None
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def cached_speed(path: Path | None = None, *, identity: str | None = None,
                 now: float | None = None) -> float | None:
    data = _record(path or state_path(), identity or machine_key(), now=now)
    return _valid_fps(data["fps"]) if data else None


def persist(speed: float | None, *, path: Path | None = None,
            identity: str | None = None, now: float | None = None) -> bool:
    """Atomic private-cache write. Never damage an existing valid measurement."""
    dest = path or state_path()
    directory = dest.parent
    fps = _valid_fps(speed)
    if speed is not None and fps is None:
        return False
    staged: str | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, staged = tempfile.mkstemp(prefix=".low-end-", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"schema": SCHEMA, "machine": identity or machine_key(),
                       "fps": fps, "at": time.time() if now is None else now},
                      output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, dest)
        return True
    except OSError:
        return False
    finally:
        if staged is not None:
            try:
                Path(staged).unlink(missing_ok=True)
            except OSError:
                pass


def choose_tier(speed: float | None, source: Any) -> str:
    """Choose software 1080p balanced or real 720p saver for source film FPS.

    FFmpeg caps HLS video output to 30 fps, including higher-frame-rate inputs.
    The 1080p synthetic measurement therefore needs 1.3x *output* real time.
    """
    try:
        fps = float(getattr(source, "fps", SOURCE_FPS) or SOURCE_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = SOURCE_FPS
    except (TypeError, ValueError, OverflowError):
        fps = SOURCE_FPS
    rate = min(fps, SOURCE_FPS)
    measured = _valid_fps(speed)
    return "balanced" if measured is not None and measured >= HEADROOM * rate else "saver"


def effective_quality(settings: dict, source: Any, *, path: Path | None = None,
                      identity: str | None = None) -> str:
    """Manual choice always wins, including a manual choice of 'balanced'."""
    manual = str(settings.get("quality", "balanced"))
    if settings.get("quality_auto", True) is not True:
        return manual if manual in {"high", "balanced", "saver"} else "balanced"
    if getattr(source, "is_audio_only", False):
        return manual if manual in {"high", "balanced", "saver"} else "balanced"
    return choose_tier(cached_speed(path, identity=identity), source)


def _priority_runner(args: list[str], *, capture_output: bool, text: bool,
                     timeout: float) -> subprocess.CompletedProcess:
    """Never use preexec_fn in the multithreaded GTK process."""
    del capture_output
    child = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **process_priority.launch_kwargs(True),
    )
    process_priority.lower(child, True)
    try:
        out, err = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise
    return subprocess.CompletedProcess(
        args, child.returncode, out.decode(errors="replace") if text else out,
        err.decode(errors="replace") if text else err,
    )


def schedule_probe(*, enabled: bool, path: Path | None = None,
                   identity: str | None = None, runner=None) -> bool:
    """Return immediately; at most one worker per app, never on the GTK loop."""
    global _running
    if not enabled:
        return False
    target, key = path or state_path(), identity or machine_key()
    with _lock:
        if _running or _record(target, key) is not None:
            return False
        _running = True

    def work() -> None:
        global _running
        try:
            try:
                measured = benchmark.run_probe(
                    seconds=3, height=1080,
                    runner=_priority_runner if runner is None else runner,
                )
            except Exception as exc:
                # Never leak a background traceback or re-probe endlessly.
                logging.getLogger(__name__).warning(
                    "Low-end capacity probe unavailable (%s)", type(exc).__name__)
                measured = None
            persist(measured, path=target, identity=key)
        finally:
            with _lock:
                _running = False

    try:
        threading.Thread(target=work, name="smoothcast-low-end-probe", daemon=True).start()
    except RuntimeError:
        with _lock:
            _running = False
        return False
    return True


def budget() -> dict[str, object]:
    """Informational only: performance SLOs require physical reference hardware."""
    return {"cores": 2, "cpu_ghz_approx": 2.5, "ram_gb": 8,
            "hardware_encoder": False, "source": "1080p30",
            "minimum_software_encode_x": HEADROOM, "first_frame_p95_ms": 4000,
            "measurement": "informational: not a physical-device result"}
