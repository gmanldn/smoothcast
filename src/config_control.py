"""Pure, bounded validation of untrusted JSON preferences before GTK uses them.

Never mutate caller defaults or retain their nested list/dict identities.
One malformed value must not discard other valid settings.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import islice
import json
import math
import os
from pathlib import Path
import shutil

import cache_policy
import subtitle_delay
import language_prefs
import watch_history


_OPTIONS = {
    "quality": frozenset({"high", "balanced", "saver"}),
    "audio": frozenset({"original", "dialogue", "night"}),
    "subs": frozenset({"off", "auto", "pick", "embedded"}),
    "color_scheme": frozenset({"default", "force-light", "prefer-dark"}),
}
_LIMITED_MAPS = frozenset({
    "positions", "audio_track_by_file", "subtitle_track_by_file",
    "device_last_used", "subtitle_delay_by_file",
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
    for key, value in raw.items():
        if key not in defaults:
            continue
        baseline = defaults[key]
        if key in _OPTIONS:
            if isinstance(value, str) and value in _OPTIONS[key]:
                cfg[key] = value
        elif key == "watch_history":
            if isinstance(value, list):
                clean = []
                for item in islice(value, _MAX_ITEMS):
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path")
                    event = item.get("event")
                    source = item.get("source")
                    position = item.get("position")
                    at = item.get("at")
                    if (isinstance(path, str) and 0 < len(path) <= _MAX_PATH
                            and event in watch_history.EVENTS
                            and source in watch_history.SOURCES
                            and _number(position) and _number(at)):
                        clean.append({
                            "path": path, "event": event, "source": source,
                            "position": float(position), "at": float(at),
                        })
                cfg[key] = clean[:watch_history.LIMIT]
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
                    elif type(selection) is int and -1 <= selection <= 1024:
                        clean[path] = selection
                cfg[key] = clean
        elif type(baseline) is bool:
            if type(value) is bool:
                cfg[key] = value
        elif key == "rotation":
            if type(value) is int and value in (0, 90, 180, 270):
                cfg[key] = value
        elif type(baseline) is int:
            lo, hi = (-100000, 100000) if key in {"window_x", "window_y"} else (
                (0, 1440) if key == "sleep_timer_minutes" else (
                (0, 600) if key == "sleep_fade_seconds" else (
                    (0, cache_policy.MAX_CAP_MB) if key == "cache_cap_mb" else (
                        (1024, 65535) if key == "hls_port" else (1, 10000))))
            )
            if type(value) is int and lo <= value <= hi:
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


def _backup(path: Path, label: str) -> None:
    """Keep one copy of the original; an existing backup is never replaced."""
    target = path.with_name(f"{path.name}.{label}.bak")
    try:
        if not target.exists():
            shutil.copy2(path, target)
    except OSError:
        pass


def load_file(path: Path, defaults: dict) -> dict:
    """Read, migrate and validate settings; protect the original on failure."""
    path = Path(path)
    key = str(path)
    _PROTECTED.discard(key)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return sanitise_config({}, defaults)
    except OSError:
        _PROTECTED.add(key)  # Unreadable now does not mean worthless.
        return sanitise_config({}, defaults)
    except ValueError:
        _backup(path, "corrupt")
        return sanitise_config({}, defaults)
    if not isinstance(raw, dict):
        _backup(path, "corrupt")
        return sanitise_config({}, defaults)
    try:
        migrated, original = migrate(raw)
    except Exception:  # A buggy migration must never cost the user's settings.
        _PROTECTED.add(key)
        return sanitise_config(raw, defaults)
    if original < SCHEMA_VERSION:
        _backup(path, f"schema{original}")
    cfg = sanitise_config(migrated, defaults)
    cfg["schema_version"] = SCHEMA_VERSION
    return cfg


def save_file(path: Path, cfg: dict) -> bool:
    """Atomically write settings unless the original is protected."""
    path = Path(path)
    if str(path) in _PROTECTED:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=1))
        os.replace(tmp, path)
    except OSError:
        return False
    return True
