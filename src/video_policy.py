"""Automatic crop and deinterlace policies (issue #54 / SC-045).

GTK-free, standard library only. Two opt-in, conservative detectors decide
whether a film needs black-bar cropping or deinterlacing, using short, bounded
FFmpeg passes on a few sample windows (never the whole file):

* ``cropdetect`` samples: crop only when most samples agree on the same, even,
  sensibly sized rectangle that actually removes at least 2% of the picture.
* ``idet`` field analysis: deinterlace only when most frames are interlaced
  **and** the field order is consistent (genuine interlaced video has one;
  noisy progressive content does not), so progressive video is never blurred.

Enable with ``"auto_crop": true`` and/or ``"auto_deinterlace": true`` in
``config.json`` (both default to false: detection adds a few seconds to a
cast start). Results are cached per file, size and mtime so seek restarts and
retries reuse them. Any failure, timeout or doubt means "do nothing".
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable
import media_tools

CONFIG_KEYS = ("auto_crop", "auto_deinterlace")
SAMPLE_FRACTIONS = (0.25, 0.5, 0.75)
CROP_SAMPLE_SECONDS = 3
IDET_SAMPLE_SECONDS = 5
PASS_TIMEOUT = 12.0
MIN_CROP_SAMPLES = 3
MIN_CROP_AGREEMENT = 0.6
MIN_CROP_SAVING = 0.02       # must remove at least 2% of the picture to be worth a re-encode filter
MIN_CROP_KEEP = 0.4          # never keep less than 40% of the picture (dark scenes)
MIN_IDET_FRAMES = 30
MIN_INTERLACED_RATIO = 0.5
MIN_FIELD_ORDER_DOMINANCE = 0.8
DEINTERLACE_FILTER = "yadif=mode=0:parity=-1:deint=interlaced"
_CACHE_LIMIT = 64

_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_IDET = re.compile(r"Multi frame detection:\s*TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+Progressive:\s*(\d+)"
                   r"\s+Undetermined:\s*(\d+)")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Crop:
    width: int
    height: int
    x: int
    y: int

    @property
    def filter(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"


@dataclass(frozen=True)
class Idet:
    tff: int = 0
    bff: int = 0
    progressive: int = 0
    undetermined: int = 0

    @property
    def frames(self) -> int:
        return self.tff + self.bff + self.progressive


@dataclass(frozen=True)
class Plan:
    """What to add to the video filter chain; the default is 'nothing'."""

    deinterlace: bool = False
    crop: Crop | None = None

    @property
    def empty(self) -> bool:
        return not self.deinterlace and self.crop is None

    def filters(self) -> list[str]:
        out = [DEINTERLACE_FILTER] if self.deinterlace else []
        if self.crop is not None:
            out.append(self.crop.filter)
        return out

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        return (self.crop.width, self.crop.height) if self.crop is not None else (width, height)


EMPTY_PLAN = Plan()


# --- parsing and decisions (pure) -------------------------------------------------

def parse_crops(text: str) -> list[Crop]:
    """Every ``crop=W:H:X:Y`` suggestion in cropdetect's log output."""
    return [Crop(*(int(v) for v in m.groups())) for m in _CROP.finditer(text or "")]


def parse_idet(text: str) -> Idet:
    """The last non-empty 'Multi frame detection' summary (ffmpeg prints it twice)."""
    best = Idet()
    for m in _IDET.finditer(text or ""):
        found = Idet(*(int(v) for v in m.groups()))
        if found.frames:
            best = found
    return best


def choose_crop(samples: list[Crop], width: int, height: int) -> Crop | None:
    """The agreed crop, or None unless it is clearly safe and worthwhile."""
    if width <= 0 or height <= 0 or len(samples) < MIN_CROP_SAMPLES:
        return None
    counts: dict[Crop, int] = {}
    for crop in samples:
        counts[crop] = counts.get(crop, 0) + 1
    best, votes = max(counts.items(), key=lambda item: (item[1], -item[0].x, -item[0].y))
    if votes / len(samples) < MIN_CROP_AGREEMENT:
        return None
    if (best.width < 16 or best.height < 16 or best.width % 2 or best.height % 2
            or best.x < 0 or best.y < 0 or best.x + best.width > width or best.y + best.height > height):
        return None
    kept = (best.width * best.height) / (width * height)
    if kept > 1 - MIN_CROP_SAVING or kept < MIN_CROP_KEEP:
        return None
    return best


def is_interlaced(idet: Idet) -> bool:
    """Mostly interlaced frames with one consistent field order."""
    if idet.frames < MIN_IDET_FRAMES:
        return False
    fielded = idet.tff + idet.bff
    if fielded / idet.frames < MIN_INTERLACED_RATIO:
        return False
    return max(idet.tff, idet.bff) / fielded >= MIN_FIELD_ORDER_DOMINANCE


# --- detection (bounded FFmpeg passes) ----------------------------------------------

def _sample_starts(duration: float) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        return [0.0]
    span = max(0.0, duration - CROP_SAMPLE_SECONDS - 1)
    return [round(span * f, 2) for f in SAMPLE_FRACTIONS]


class Health:
    """Records whether every detection pass ran; failed passes are not cached."""

    def __init__(self) -> None:
        self.failed = False


def _run(command: list[str], runner: Runner, health: Health | None = None) -> str:
    try:
        result = runner(command, capture_output=True, text=True, timeout=PASS_TIMEOUT)
    except (subprocess.SubprocessError, OSError, ValueError):
        if health is not None:
            health.failed = True
        return ""
    return str(getattr(result, "stderr", "") or "")


def detect_crop(path: str, duration: float, width: int, height: int,
                *, video_stream: int = 0, runner: Runner = subprocess.run,
                health: Health | None = None) -> Crop | None:
    samples: list[Crop] = []
    for start in _sample_starts(duration):
        text = _run([media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-ss", str(start), "-i", path,
                     "-map", f"0:{video_stream}", "-t", str(CROP_SAMPLE_SECONDS),
                     "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-sn", "-f", "null", "-"],
                    runner, health)
        found = parse_crops(text)
        if found:
            samples.append(found[-1])  # the last suggestion of a window has seen the most frames
    return choose_crop(samples, width, height)


def detect_interlaced(path: str, duration: float, *, video_stream: int = 0,
                      runner: Runner = subprocess.run, health: Health | None = None) -> bool:
    start = _sample_starts(duration)[len(SAMPLE_FRACTIONS) // 2 if duration > 0 else 0]
    text = _run([media_tools.resolve_media_tool("ffmpeg"), "-hide_banner", "-ss", str(start), "-i", path,
                 "-map", f"0:{video_stream}", "-t", str(IDET_SAMPLE_SECONDS),
                 "-vf", "idet", "-an", "-sn", "-f", "null", "-"], runner, health)
    return is_interlaced(parse_idet(text))


# --- preview (what the detectors would do, without applying anything) ---------------

@dataclass(frozen=True)
class Detection:
    crop: Crop | None = None
    interlaced: bool = False


def preview(path: str, duration: float, width: int, height: int, *, video_stream: int = 0,
            runner: Runner = subprocess.run) -> Detection:
    """Run both detectors regardless of the config flags; nothing is cached or applied."""
    return Detection(
        crop=detect_crop(path, duration, width, height, video_stream=video_stream, runner=runner),
        interlaced=detect_interlaced(path, duration, video_stream=video_stream, runner=runner),
    )


def describe(found: Detection, width: int, height: int) -> str:
    """One plain-language line for the Preferences preview."""
    if found.crop is not None and width > 0 and height > 0:
        removed = round(100 * (1 - (found.crop.width * found.crop.height) / (width * height)))
        bars = f"Black bars: crop to {found.crop.width}\u00d7{found.crop.height} (removes {removed}% of the picture)"
    else:
        bars = "No black bars found"
    lines = "Interlaced: deinterlacing would apply" if found.interlaced else "Progressive: no deinterlacing needed"
    return f"{bars} \u00b7 {lines}"


# --- configuration and the cached plan --------------------------------------------------

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cast-control" / "config.json"


def load_flags(path: Path | None = None) -> tuple[bool, bool]:
    """(auto_crop, auto_deinterlace) from config.json; only a literal true enables."""
    try:
        raw = json.loads((path or config_path()).read_text())
    except (OSError, ValueError, RuntimeError):
        return (False, False)
    if not isinstance(raw, dict):
        return (False, False)
    return (raw.get("auto_crop") is True, raw.get("auto_deinterlace") is True)


_CACHE: "OrderedDict[tuple, Plan]" = OrderedDict()
_LOCK = threading.Lock()


def make_plan(path: str, duration: float, width: int, height: int, *, video_stream: int = 0,
              crop: bool | None = None, deinterlace: bool | None = None,
              runner: Runner = subprocess.run) -> Plan:
    """The filters to add for *path*; flags default to config.json. Never raises."""
    if crop is None or deinterlace is None:
        cfg_crop, cfg_deint = load_flags()
        crop = cfg_crop if crop is None else crop
        deinterlace = cfg_deint if deinterlace is None else deinterlace
    if not crop and not deinterlace:
        return EMPTY_PLAN
    try:
        info = os.stat(path)
        key: tuple | None = (os.path.realpath(path), info.st_size, info.st_mtime_ns,
                             video_stream, bool(crop), bool(deinterlace))
    except OSError:
        key = None
    if key is not None:
        with _LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
    health = Health()
    plan = Plan(
        deinterlace=bool(deinterlace) and detect_interlaced(
            path, duration, video_stream=video_stream, runner=runner, health=health),
        crop=detect_crop(path, duration, width, height, video_stream=video_stream,
                         runner=runner, health=health) if crop else None,
    )
    if key is not None and not health.failed:  # a timeout or crash is retried, not remembered
        with _LOCK:
            _CACHE[key] = plan
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
    return plan
