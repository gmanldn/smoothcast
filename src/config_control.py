"""Pure, bounded validation of untrusted JSON preferences before GTK uses them.

Never mutate caller defaults or retain their nested list/dict identities.
One malformed value must not discard other valid settings.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import errno
from itertools import islice
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
import aspect_override
import picture_adjustments

import audio_delay
import bookmarks
import cache_policy
import subtitle_delay
import accent
import density
import subtitle_style
import language_prefs
import library_folders
import loudness
import watch_history


_OPTIONS = {
    "quality": frozenset({"high", "balanced", "saver"}),
    "audio": frozenset({"original", "dialogue", "night"}),
    "audio_loudness": frozenset(loudness.TARGETS),
    "subs": frozenset({"off", "auto", "pick", "embedded"}),
    "color_scheme": frozenset({"default", "force-light", "prefer-dark"}),
    "subtitle_style": frozenset(subtitle_style.PRESETS),
    "accent": accent.IDS,
    "density": density.IDS,
    "update_channel": frozenset({"develop", "main"}),
}
_LIMITED_MAPS = frozenset({
    "positions", "audio_track_by_file", "subtitle_track_by_file",
    "device_last_used", "subtitle_delay_by_file", "audio_delay_by_file",
})
_MAX_PATH = 4096
_MAX_ITEMS = 512


def _number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def sanitise_config(raw: object, defaults: dict) -> dict:
    """Return an independent validated settings map.

    Corrupt/unknown individual keys revert to defaults, not the whole file.
    Small bounded collections prevent hostile JSON from blocking the GTK
    thread when the user launches the application.
    """
    cfg = deepcopy(defaults)
    if not isinstance(raw, dict):
        return cfg
    # Existing installations had an explicit quality choice but no auto-mode
    # flag. Preserve that user's preference; only fresh profiles default auto.
    if ("quality_auto" in defaults and "quality" in raw
            and "quality_auto" not in raw):
        cfg["quality_auto"] = False
    for key, value in raw.items():
        if key not in defaults:
            continue
        baseline = defaults[key]
        if key in _OPTIONS:
            if isinstance(value, str) and value in _OPTIONS[key]:
                cfg[key] = value
        elif key in picture_adjustments.DEFAULTS:
            cfg[key] = picture_adjustments.validated(key, value)
        elif key == "watch_history":
            cfg[key] = watch_history.clean(value)
        elif key == "bookmarks":
            cfg[key] = bookmarks.clean(value)
        elif key == "library_folders":
            cfg[key] = library_folders.to_config(library_folders.load({key: value}))
        elif key in {"recents", "favourites", "cast_targets", "device_favourites"}:
            if isinstance(value, list):
                limit = 8 if key == "recents" else (
                    16 if key in {"favourites", "device_favourites"} else 32)
                cfg[key] = [
                    item for item in value[:_MAX_ITEMS]
                    if isinstance(item, str) and 0 < len(item) <= _MAX_PATH
                ][:limit]
        elif key in {"preferred_audio_languages", "preferred_subtitle_languages"}:
            cfg[key] = language_prefs.clean_languages(value)
        elif key == "language_overrides":
            cfg[key] = language_prefs.clean_overrides(value)
        elif key in _LIMITED_MAPS:
            if isinstance(value, dict):
                clean: dict = {}
                for path, selection in islice(value.items(), _MAX_ITEMS):
                    if not isinstance(path, str) or not 0 < len(path) <= _MAX_PATH:
                        continue
                    if key in {"positions", "device_last_used"}:
                        if _number(selection) and 0 <= selection <= 1e12:
                            clean[path] = float(selection)
                    elif key == "subtitle_delay_by_file":
                        if (type(selection) is int and selection != 0
                                and -subtitle_delay.LIMIT_MS <= selection <= subtitle_delay.LIMIT_MS):
                            clean[path] = selection
                    elif key == "audio_delay_by_file":
                        if (type(selection) is int and selection != 0
                                and -audio_delay.LIMIT_MS <= selection <= audio_delay.LIMIT_MS):
                            clean[path] = selection
                    elif type(selection) is int and -1 <= selection <= 1024:
                        clean[path] = selection
                cfg[key] = clean
        elif type(baseline) is bool:
            if type(value) is bool:
                cfg[key] = value
        elif key == "rotation":
            if type(value) is int and value in (0, 90, 180, 270):
                cfg[key] = value
        elif key == "aspect_override":
            if isinstance(value, str) and value in aspect_override.MODES:
                cfg[key] = value
        elif type(baseline) is int:
            lo, hi = (-100000, 100000) if key in {"window_x", "window_y"} else (
                (0, 1440) if key == "sleep_timer_minutes" else (
                (0, 600) if key == "sleep_fade_seconds" else (
                    (0, cache_policy.MAX_CAP_MB) if key == "cache_cap_mb" else (
                        (1024, 65535) if key == "hls_port" else (
                            (0, 65535) if key == "portal_port" else (1, 10000)
                        ))))
            )
            if type(value) is int and lo <= value <= hi:
                if key != "portal_port" or value == 0 or 49152 <= value <= 65535:
                    cfg[key] = value
        elif type(baseline) is float:
            bounds = {
                "audio_gain": (0, 24),
                "playback_speed": (0.5, 2),
                "sleep_timer_deadline": (0, 1e12),
            }
            lo, hi = bounds.get(key, (-1e12, 1e12))
            if _number(value) and lo <= value <= hi:
                cfg[key] = float(value)
        elif isinstance(baseline, str):
            if isinstance(value, str) and len(value) <= _MAX_PATH and (
                key != "device" or value.strip()
            ):
                cfg[key] = value
    return cfg


# --- Schema versioning and migration (issue #273) ---------------------------
#
# ``schema_version`` is the integer format of config.json. A file without it is
# version 0 (every release before versioning); its keys already match version
# 1, so that migration only stamps the version. To change the format: bump
# SCHEMA_VERSION, add MIGRATIONS[old] returning the new-shape dict, test it.
SCHEMA_VERSION = 1


class ConfigSchemaError(ValueError):
    """The saved settings use a schema this release cannot safely handle."""


def _v0_to_v1(raw: dict) -> dict:
    return raw


MIGRATIONS = {0: _v0_to_v1}
# Paths whose original file must not be overwritten (newer schema, failed
# migration, unreadable). Saves to them are skipped for this process.
_PROTECTED: set[str] = set()
_CORRUPT_BACKED_UP: set[str] = set()
_STATE_LOCK = threading.RLock()
_BASELINES: dict[str, dict] = {}
_FILE_LOCKS: dict[str, threading.RLock] = {}
_MISSING = object()


def _path_key(path: Path) -> str:
    return str(path.resolve())


def _remember(path: Path, cfg: dict) -> dict:
    with _STATE_LOCK:
        _BASELINES[_path_key(path)] = deepcopy(cfg)
    return cfg


@contextmanager
def _advisory_lock(path: Path) -> Iterator[None]:
    """Serialize writers across threads and processes on all supported OSes."""
    key = _path_key(path)
    with _STATE_LOCK:
        thread_lock = _FILE_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                if lock_file.read(1) == b"":
                    lock_file.seek(0)
                    lock_file.write(b"0")
                    lock_file.flush()
                deadline = time.monotonic() + 30
                while True:
                    lock_file.seek(0)
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out locking SmoothCast settings") from exc
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_object(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, cfg: dict) -> None:
    """Durably replace a config without sharing a temporary pathname."""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    tmp = Path(tmp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(cfg, handle, indent=1, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _as_current_config(raw: dict | None, defaults: dict) -> dict:
    if raw is None:
        return deepcopy(defaults)
    try:
        migrated, _ = migrate(raw)
    except ConfigSchemaError:
        raise
    except Exception as exc:
        raise ConfigSchemaError("saved settings cannot be migrated") from exc
    config = sanitise_config(migrated, defaults)
    for name, value in migrated.items():
        if name not in defaults:
            config[name] = deepcopy(value)
    config["schema_version"] = SCHEMA_VERSION
    return config


def migrate(raw: dict) -> tuple[dict, int]:
    """Return (migrated copy, original version); never mutates *raw*."""
    version = raw.get("schema_version", 0)
    if type(version) is not int or version < 0:
        raise ConfigSchemaError(f"invalid schema_version {version!r}")
    if version > SCHEMA_VERSION:
        raise ConfigSchemaError(
            f"settings are schema {version}; this release understands {SCHEMA_VERSION}")
    original, data = version, deepcopy(raw)
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ConfigSchemaError(f"no migration from schema {version}")
        data = step(deepcopy(data))
        if not isinstance(data, dict):
            raise ConfigSchemaError(f"migration from schema {version} returned no mapping")
        version += 1
        data["schema_version"] = version
    return data, original


def _backup(path: Path, label: str) -> bool:
    """Keep one copy of the original; an existing backup is never replaced."""
    target = path.with_name(f"{path.name}.{label}.bak")
    try:
        if target.exists():
            return False
        shutil.copy2(path, target)
    except OSError:
        return False
    return True


def load_file(path: Path, defaults: dict) -> dict:
    """Read, migrate and validate settings; protect the original on failure."""
    path = Path(path)
    key = _path_key(path)
    with _STATE_LOCK:
        _PROTECTED.discard(key)
        _CORRUPT_BACKED_UP.discard(key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _remember(path, sanitise_config({}, defaults))
    except OSError:
        with _STATE_LOCK:
            _PROTECTED.add(key)  # Unreadable now does not mean worthless.
        return _remember(path, sanitise_config({}, defaults))
    except ValueError:
        if _backup(path, "corrupt"):
            with _STATE_LOCK:
                _CORRUPT_BACKED_UP.add(key)
        else:
            with _STATE_LOCK:
                _PROTECTED.add(key)
        return _remember(path, sanitise_config({}, defaults))
    if not isinstance(raw, dict):
        if _backup(path, "corrupt"):
            with _STATE_LOCK:
                _CORRUPT_BACKED_UP.add(key)
        else:
            with _STATE_LOCK:
                _PROTECTED.add(key)
        return _remember(path, sanitise_config({}, defaults))
    try:
        migrated, original = migrate(raw)
    except Exception:  # A buggy migration must never cost the user's settings.
        with _STATE_LOCK:
            _PROTECTED.add(key)
        return _remember(path, sanitise_config(raw, defaults))
    if original < SCHEMA_VERSION:
        _backup(path, f"schema{original}")
    cfg = sanitise_config(migrated, defaults)
    cfg["schema_version"] = SCHEMA_VERSION
    return _remember(path, cfg)


def save_file(path: Path, cfg: dict, *, snapshot_only: bool = False) -> bool:
    """Merge this process's changed keys and durably replace the config."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = _path_key(path)
        with _STATE_LOCK:
            if key in _PROTECTED:
                return False
            may_replace_corrupt = key in _CORRUPT_BACKED_UP
            baseline = deepcopy(_BASELINES.get(key, cfg))
        with _advisory_lock(path):
            raw = _read_object(path)
            if raw is None and path.exists() and not may_replace_corrupt:
                return False
            try:
                disk_config = _as_current_config(raw, baseline)
            except ConfigSchemaError:
                with _STATE_LOCK:
                    _PROTECTED.add(key)
                return False
            changed = {
                name for name in set(baseline) | set(cfg)
                if baseline.get(name, _MISSING) != cfg.get(name, _MISSING)
            }
            merged = deepcopy(disk_config)
            for name in changed:
                if name in cfg:
                    merged[name] = deepcopy(cfg[name])
                else:
                    merged.pop(name, None)
            merged["schema_version"] = SCHEMA_VERSION
            _atomic_write(path, merged)
        saved_baseline = deepcopy(cfg) if snapshot_only else deepcopy(merged)
        cfg.clear()
        cfg.update(merged)
        with _STATE_LOCK:
            _BASELINES[key] = saved_baseline
            _CORRUPT_BACKED_UP.discard(key)
    except (OSError, TypeError, ValueError):
        return False
    return True


def refresh_file(path: Path, cfg: dict, defaults: dict) -> bool:
    """Refresh keys untouched locally, preserving unsaved in-memory edits."""
    path = Path(path)
    key = _path_key(path)
    with _STATE_LOCK:
        baseline = deepcopy(_BASELINES.get(key))
        if key in _PROTECTED:
            return False
    if baseline is None:
        return False
    raw = _read_object(path)
    if raw is None:
        return False
    try:
        disk = _as_current_config(raw, defaults)
    except (OSError, ConfigSchemaError, TypeError, ValueError):
        return False
    for name in baseline:
        old = baseline[name]
        if cfg.get(name) == old:
            cfg[name] = deepcopy(disk.get(name, old))
            baseline[name] = deepcopy(disk.get(name, old))
    with _STATE_LOCK:
        _BASELINES[key] = baseline
    return True


class DebouncedWriter:
    """Coalesce bursty config updates onto one serialized background writer."""

    def __init__(
        self, write: Callable[[dict], bool], *, delay: float = 0.15,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        if delay < 0:
            raise ValueError("debounce delay cannot be negative")
        self._write = write
        self._delay = delay
        self._on_error = on_error
        self._condition = threading.Condition()
        self._pending: tuple[int, dict, float] | None = None
        self._sequence = 0
        self._completed_sequence = 0
        self._last_result = True
        self._running = False
        self._thread: threading.Thread | None = None

    def submit(self, cfg: dict) -> int:
        with self._condition:
            self._sequence += 1
            sequence = self._sequence
            self._pending = (sequence, deepcopy(cfg), time.monotonic() + self._delay)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="smoothcast-config-writer", daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()
            return sequence

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None:
                    self._condition.wait()
                sequence, cfg, deadline = self._pending
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                if self._pending is None or self._pending[0] != sequence:
                    continue
                self._pending = None
                self._running = True
            ok = False
            error = None
            try:
                ok = self._write(cfg)
            except Exception as exc:
                error = f"Could not save SmoothCast settings: {exc}"
            if not ok and self._on_error is not None:
                try:
                    self._on_error(error or "Could not save SmoothCast settings")
                except Exception:
                    pass
            with self._condition:
                self._completed_sequence = sequence
                self._last_result = ok
                self._running = False
                self._condition.notify_all()

    def flush(self, timeout: float | None = 5.0) -> bool:
        """Force pending data now and wait until the current write completes."""
        end = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            target = self._sequence
            if self._pending is not None:
                sequence, cfg, _ = self._pending
                self._pending = (sequence, cfg, time.monotonic())
                self._condition.notify_all()
            while (self._pending is not None or self._running
                   or self._completed_sequence < target):
                remaining = None if end is None else end - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._last_result
