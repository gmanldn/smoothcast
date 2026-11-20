"""Per-film audio delay (lip-sync) and the FFmpeg filters it needs (issue #113 / SC-104).

GTK-free and standard library only. A positive delay plays the soundtrack
*later* (use it when sound arrives before the lips move); a negative delay plays
it *earlier*. The value is whole milliseconds, clamped to +/-5 s and stored per
film so it survives restarts.

Timing model: the delay is applied as the *last* audio filter, after any
``atempo`` speed change, so it is always measured in output time. A seek (-ss) or
a speed change therefore never changes the offset between picture and sound, and
nothing accumulates: the shift is one constant applied to the start of each
encode. Direct play cannot be shifted, so a non-zero delay forces a transcode.
"""
from __future__ import annotations

import math
from collections.abc import MutableMapping

STEP_MS = 50
LIMIT_MS = 5_000
CONFIG_KEY = "audio_delay_by_file"
MAX_ENTRIES = 512


def normalize(value: object) -> int:
    """Return a safe whole-millisecond delay; unusable input means no delay."""
    if type(value) is bool or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return max(-LIMIT_MS, min(LIMIT_MS, int(round(value))))


def step(current: object, direction: int) -> int:
    """Move one 50 ms step later (direction > 0) or earlier (< 0)."""
    value = normalize(current)
    if direction == 0:
        return value
    return normalize(value + (STEP_MS if direction > 0 else -STEP_MS))


def label(delay_ms: object) -> str:
    """Short human label such as ``+0.15 s`` or ``-1.5 s``; ``Off`` at zero."""
    ms = normalize(delay_ms)
    if ms == 0:
        return "Off"
    text = f"{ms / 1000:+.3f}".rstrip("0").rstrip(".")
    return f"{text.replace('-', chr(0x2212))} s"


def filters(delay_ms: object) -> list[str]:
    """FFmpeg ``-af`` entries that shift the soundtrack; empty when there is no delay.

    Positive: pad the start with silence (``adelay`` on every channel).
    Negative: drop the first ``|delay|`` of audio and restart its clock at zero.
    """
    ms = normalize(delay_ms)
    if ms > 0:
        return [f"adelay=delays={ms}:all=1"]
    if ms < 0:
        return [f"atrim=start={-ms / 1000:.3f}", "asetpts=PTS-STARTPTS"]
    return []


def get(cfg: object, path: object) -> int:
    """Saved delay for a film (0 when none or when the stored value is bad)."""
    saved = cfg.get(CONFIG_KEY) if isinstance(cfg, dict) else None
    if not isinstance(saved, dict):
        return 0
    return normalize(saved.get(str(path), 0))


def put(cfg: MutableMapping, path: object, delay_ms: object) -> int:
    """Store (or clear, at zero) a film's delay; returns the stored value."""
    ms = normalize(delay_ms)
    current = cfg.get(CONFIG_KEY)
    saved = dict(current) if isinstance(current, dict) else {}
    key = str(path)
    saved.pop(key, None)  # re-insert so the newest entry is kept last
    if ms != 0:
        while len(saved) >= MAX_ENTRIES:
            saved.pop(next(iter(saved)))
        saved[key] = ms
    cfg[CONFIG_KEY] = saved
    return ms
