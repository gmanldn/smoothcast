"""Optional EBU R128 loudness normalisation for the transcoded audio chain.

The receiver gets the same two-channel AAC stream as before; this module only
adds FFmpeg's ``loudnorm`` filter when the user opts in. Programme and album
targets are conservative broadcast-style presets, and the filter's true-peak
limiter keeps intersample peaks below -1.5 dBFS. It never changes system-wide
audio or the local preview's device volume.

Pure module: no GTK, processes or network.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import threading

import cache_privacy

# ``loudnorm`` measures integrated loudness, loudness range and true peak while
# it runs, so a single pass is already EBU R128 based rather than a fixed gain.
TARGETS: dict[str, tuple[str, float]] = {
    "off": ("Off", 0.0),
    "programme": ("Programme (-16 LUFS)", -16.0),
    "album": ("Album (-18 LUFS)", -18.0),
}
DEFAULT = "off"
TRUE_PEAK_DB = -1.5
LOUDNESS_RANGE_LU = 11.0
MUSIC_TARGET_LUFS = -16.0
ANALYSIS_TIMEOUT = 30
ANALYSIS_CACHE_LIMIT = 128


@dataclass(frozen=True)
class Analysis:
    integrated_lufs: float
    true_peak_db: float
    loudness_range_lu: float
    threshold_db: float


def parse_analysis(stderr: str) -> Analysis | None:
    """Read the final valid loudnorm JSON block; reject silence and NaNs."""
    decoder = json.JSONDecoder()
    blocks = []
    for index, character in enumerate(stderr):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(stderr[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and "input_i" in value:
            blocks.append(value)
    if not blocks:
        return None
    values = []
    for name in ("input_i", "input_tp", "input_lra", "input_thresh"):
        try:
            number = float(blocks[-1][name])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        values.append(number)
    integrated, peak, lra, threshold = values
    if integrated < -70 or integrated > 10 or peak > 20 or lra < 0 or lra > 100:
        return None
    return Analysis(integrated, peak, lra, threshold)


def cache_key(path: str | os.PathLike, track: int, profile: str,
              downmix: str | None, pre_filters: tuple[str, ...] = ()) -> str | None:
    """Fingerprint the file and exact analysis path without storing its name."""
    try:
        resolved = Path(path).resolve(strict=True)
        info = resolved.stat()
    except (OSError, RuntimeError):
        return None
    identity = (str(resolved), info.st_size, info.st_mtime_ns, track, profile,
                downmix or "", tuple(pre_filters), MUSIC_TARGET_LUFS, TRUE_PEAK_DB,
                LOUDNESS_RANGE_LU)
    return hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()


def _cache_read(path: Path, key: str) -> Analysis | None:
    try:
        if path.is_symlink() or path.stat().st_size > 256 * 1024:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = raw.get("entries", {}).get(key) if isinstance(raw, dict) else None
        if not isinstance(data, dict):
            return None
        result = Analysis(**data)
        if not all(math.isfinite(v) for v in asdict(result).values()):
            return None
        return result
    except (OSError, ValueError, TypeError):
        return None


def analysis_cache_path() -> Path:
    return Path.home() / ".cache/cast-control/music-autogain.json"


def get_cached(path: str | os.PathLike, track: int, profile: str,
               *, downmix: str | None = None,
               pre_filters: tuple[str, ...] = ()) -> Analysis | None:
    key = cache_key(path, track, profile, downmix, pre_filters)
    return _cache_read(analysis_cache_path(), key) if key else None


def _cache_write(path: Path, key: str, analysis: Analysis) -> None:
    entries: OrderedDict[str, dict] = OrderedDict()
    try:
        if not path.is_symlink() and path.stat().st_size <= 256 * 1024:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
                entries.update((k, v) for k, v in raw["entries"].items()
                               if isinstance(k, str) and isinstance(v, dict))
    except (OSError, ValueError):
        pass
    entries.pop(key, None)
    entries[key] = asdict(analysis)
    while len(entries) > ANALYSIS_CACHE_LIMIT:
        entries.popitem(last=False)
    try:
        cache_privacy.write_private_json_atomic(path, {"version": 1, "entries": entries})
    except (OSError, ValueError, TypeError):
        pass


def music_filter(analysis: Analysis | None, manual_offset_db: float = 0.0) -> str:
    """Build two-pass R128 audio normalization with a -1.5 dBTP ceiling."""
    try:
        offset = float(manual_offset_db)
    except (TypeError, ValueError, OverflowError):
        offset = 0.0
    if not math.isfinite(offset):
        offset = 0.0
    offset = max(-12.0, min(6.0, offset))
    args = [f"I={MUSIC_TARGET_LUFS:g}", f"TP={TRUE_PEAK_DB:g}",
            f"LRA={LOUDNESS_RANGE_LU:g}"]
    if analysis is not None:
        args.extend((
            f"measured_I={analysis.integrated_lufs:.3f}",
            f"measured_TP={analysis.true_peak_db:.3f}",
            f"measured_LRA={analysis.loudness_range_lu:.3f}",
            f"measured_thresh={analysis.threshold_db:.3f}",
            f"offset={offset:g}", "linear=true",
        ))
    return "loudnorm=" + ":".join(args)


def analyze(path: str | os.PathLike, track: int, profile: str,
            *, downmix: str | None = None, pre_filters: tuple[str, ...] = (),
            cache_file: str | os.PathLike | None = None,
            timeout: float = ANALYSIS_TIMEOUT) -> Analysis | None:
    """Run one bounded R128 analysis and persist its stats in a private cache."""
    track = track if type(track) is int and track >= 0 else 0
    path = Path(path)
    key = cache_key(path, track, profile, downmix, pre_filters)
    if key is None:
        return None
    cache_path = Path(cache_file) if cache_file is not None else analysis_cache_path()
    cached = _cache_read(cache_path, key)
    if cached is not None:
        return cached
    filters = [*pre_filters]
    if downmix:
        filters.insert(0, downmix)
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json")
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostats", "-i", str(path), "-map",
             f"0:a:{track}", "-vn", "-sn", "-dn", "-af", ",".join(filters),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=max(1.0, min(float(timeout), 60.0)),
        )
    except (OSError, subprocess.SubprocessError, ValueError, OverflowError):
        return None
    if result.returncode != 0:
        return None
    analysis = parse_analysis(result.stderr or "")
    if analysis is not None:
        _cache_write(cache_path, key, analysis)
    return analysis


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-loudness")
_SCHEDULED: OrderedDict[str, Future] = OrderedDict()
_SCHEDULE_LOCK = threading.RLock()


def schedule_analysis(path: str | os.PathLike, track: int, profile: str,
                      *, downmix: str | None = None,
                      pre_filters: tuple[str, ...] = ()) -> Future | None:
    """Coalesce background analyses and keep the queue of work bounded."""
    key = cache_key(path, track, profile, downmix, pre_filters)
    if key is None:
        return None
    if get_cached(path, track, profile, downmix=downmix,
                  pre_filters=pre_filters) is not None:
        return None
    with _SCHEDULE_LOCK:
        existing = _SCHEDULED.get(key)
        if existing is not None:
            return existing
        if len(_SCHEDULED) >= 4:
            for old_key, old_future in tuple(_SCHEDULED.items()):
                if not old_future.running() and old_future.cancel():
                    _SCHEDULED.pop(old_key, None)
                    break
            if len(_SCHEDULED) >= 4:
                return None
        future = _EXECUTOR.submit(
            analyze, path, track, profile, downmix=downmix,
            pre_filters=pre_filters)
        _SCHEDULED[key] = future

        def finished(_future):
            with _SCHEDULE_LOCK:
                _SCHEDULED.pop(key, None)

        future.add_done_callback(finished)
        return future


def normalize(choice: object) -> str:
    """A known normalisation choice, else ``off`` (bad config never raises)."""
    return choice if isinstance(choice, str) and choice in TARGETS else DEFAULT


def label(choice: object) -> str:
    """Human-readable label for a choice."""
    return TARGETS[normalize(choice)][0]


def target_lufs(choice: object) -> float:
    """Integrated loudness target in LUFS, or ``0.0`` when normalisation is off."""
    return TARGETS[normalize(choice)][1]


def filter_args(choice: object) -> list[str]:
    """FFmpeg ``-af`` entries for *choice*, or an empty list when disabled."""
    choice = normalize(choice)
    if choice == DEFAULT:
        return []
    target = target_lufs(choice)
    return [
        f"loudnorm=I={target:g}:TP={TRUE_PEAK_DB:g}:LRA={LOUDNESS_RANGE_LU:g}"
    ]


def choices() -> list[tuple[str, str]]:
    """Ordered ``(label, value)`` pairs shared by settings and preferences."""
    return [(label, value) for value, (label, _target) in TARGETS.items()]
