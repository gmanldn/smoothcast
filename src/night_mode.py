"""Night mode (#390): audio-only compression + dialogue lift. Pure filter strings and policy.

Filter order is fixed and tested: downmix -> night -> EQ -> limiter. ``Rooms`` stores a level per room
(atomic JSON) plus optional quiet-hours auto-on. ``toggle`` returns a restart plan that keeps the
source-time position; video stays copied and only audio is re-encoded.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

LEVELS = ("off", "light", "strong")
LABEL, SUBLABEL = "Night mode", "Softer bangs, clearer voices"
ORDER = ("downmix", "night", "eq", "limiter")
_PARAMS = {"light": dict(thr=-26, ratio=2.5, att=20, rel=250, boost=2, makeup=3), "strong": dict(thr=-32, ratio=5, att=10, rel=200, boost=4, makeup=6)}
LIMITER = "alimiter=limit=0.89:level=disabled"


def clean_level(v) -> str:
    return v if v in LEVELS else "off"


def night_filter(level: str, channels: int = 2) -> str:
    """Compressor + speech-band (≈2–4 kHz) lift. Mono/stereo/surround use the same chain post-downmix;
    a still-multichannel stream lifts only the centre channel (dialogue)."""
    level = clean_level(level)
    if level == "off":
        return ""
    p = _PARAMS[level]
    comp = f"acompressor=threshold={p['thr']}dB:ratio={p['ratio']}:attack={p['att']}:release={p['rel']}:makeup={p['makeup']}"
    speech = f"equalizer=f=3000:t=q:w=1.2:g={p['boost']}"
    if channels > 2:
        return f"pan=5.1|FL=FL|FR=FR|FC=1.4*FC|LFE=0.6*LFE|BL=BL|BR=BR,{comp},{speech}"[: 400]
    return f"{comp},{speech}"


def chain(level: str, channels: int = 2, downmix: str = "", eq: str = "", limiter: bool = True) -> str:
    """Compose in the documented order, skipping empty stages."""
    stages = {"downmix": downmix, "night": night_filter(level, 2 if downmix else channels), "eq": eq, "limiter": LIMITER if limiter else ""}
    return ",".join(stages[k] for k in ORDER if stages[k])


def in_quiet_hours(hhmm: int, start: int, end: int) -> bool:
    """Minutes since midnight; midnight-safe window (e.g. 22:00-07:00)."""
    if start == end:
        return False
    return start <= hhmm < end if start < end else hhmm >= start or hhmm < end


def toggle(old: str, new: str, position: float, direct_play: bool, has_video: bool, audio_only_cast: bool = False) -> dict:
    old, new = clean_level(old), clean_level(new)
    if old == new:
        return {"restart": False}
    plan = {"restart": True, "seek_to": max(0.0, float(position)), "budget_s": 2.0, "reason": "audio_filter_changed",
            "video": "copy" if has_video and not audio_only_cast else "none", "audio": "transcode" if new != "off" else ("copy" if direct_play else "transcode")}
    if new == "off" and direct_play:
        plan["audio"] = "copy"                           # back to direct play when night mode ends
    return plan


class Rooms:
    def __init__(self, path: Path | None = None) -> None:
        self.path, self.d = (Path(path) if path else None), {}
        if self.path:
            try:
                self.d = json.loads(self.path.read_text("utf-8"))
            except (OSError, ValueError):
                self.d = {}
            if not isinstance(self.d, dict):
                self.d = {}

    def set(self, room: str, level: str | None = None, auto: tuple[int, int] | None = ..., auto_level: str = "light") -> None:
        e = self.d.setdefault(room, {"level": "off", "auto": None, "auto_level": "light"})
        if level is not None:
            e["level"] = clean_level(level)
        if auto is not ...:
            e["auto"] = list(auto) if auto else None
        e["auto_level"] = clean_level(auto_level) if auto_level != "off" else "light"
        self._save()

    def level(self, room: str, minutes_since_midnight: int) -> str:
        e = self.d.get(room)
        if not e:
            return "off"
        if e.get("level", "off") != "off":
            return clean_level(e["level"])
        a = e.get("auto")
        return clean_level(e.get("auto_level")) if a and in_quiet_hours(minutes_since_midnight, a[0], a[1]) else "off"

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".nm")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.d, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
