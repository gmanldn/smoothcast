"""Per-receiver quality/subtitle presets with validation and reset (#47). Pure.

A preset only remembers choices known to be safe for one receiver. Unknown keys
and out-of-range values are dropped so a corrupt or hostile config cannot reach
the encoder. ``reset`` removes a receiver's entry entirely.
"""
from __future__ import annotations

import math

CODECS = ("h264", "hevc")
SUBTITLE_METHODS = ("off", "burn", "sidecar")
MAX_BITRATE_KBPS = 80_000
MIN_BITRATE_KBPS = 500
MAX_ENTRIES = 64
CONFIG_KEY = "device_presets"


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def clean(raw) -> dict:
    """Validated preset fields only; empty dict when nothing usable."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if raw.get("codec") in CODECS:
        out["codec"] = raw["codec"]
    if raw.get("subtitles") in SUBTITLE_METHODS:
        out["subtitles"] = raw["subtitles"]
    bitrate = _number(raw.get("bitrate_kbps"))
    if bitrate is not None and MIN_BITRATE_KBPS <= bitrate <= MAX_BITRATE_KBPS:
        out["bitrate_kbps"] = int(bitrate)
    volume = _number(raw.get("volume"))
    if volume is not None and 0.0 <= volume <= 1.0:
        out["volume"] = round(volume, 3)
    return out


def get(cfg: dict, receiver: str) -> dict:
    table = cfg.get(CONFIG_KEY)
    return clean(table.get(str(receiver))) if isinstance(table, dict) else {}


def remember(cfg: dict, receiver: str, **fields) -> dict:
    """Merge validated fields into the receiver's preset and return it."""
    table = cfg.get(CONFIG_KEY)
    if not isinstance(table, dict):
        table = cfg[CONFIG_KEY] = {}
    merged = {**clean(table.get(str(receiver))), **clean(fields)}
    if merged:
        table[str(receiver)] = merged
        while len(table) > MAX_ENTRIES:  # drop the oldest-inserted receiver
            table.pop(next(iter(table)))
    return merged


def reset(cfg: dict, receiver: str) -> bool:
    table = cfg.get(CONFIG_KEY)
    return isinstance(table, dict) and table.pop(str(receiver), None) is not None
