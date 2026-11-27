"""Three-band Bass/Mid/Treble tone control (#346). Pure; one FFmpeg filter chain.

Bass = low shelf @100 Hz, Mid = peaking @1 kHz (Q 0.8), Treble = high shelf
@10 kHz; each -12..+12 dB, 0 is neutral and emits no filter. Positive boosts add
a limiter ceiling for headroom. ``Room`` keeps revisioned last-confirmed state
with a rate limit so two clients can't cause restart storms. This is separate
from the 10-band EQ (#111): ``compose`` refuses to stack both on one stream.
"""
from __future__ import annotations

MAX_DB = 12.0
BANDS = ("bass", "mid", "treble")
MIN_INTERVAL_S = 0.5
_FILTER = {"bass": "bass=g={g}:f=100:w=0.7",
           "mid": "equalizer=f=1000:t=q:w=0.8:g={g}",
           "treble": "treble=g={g}:f=10000:w=0.7"}


def clamp(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v:
        return 0.0
    return round(max(-MAX_DB, min(MAX_DB, v)), 1)


def normalize(gains: dict | None) -> dict[str, float]:
    gains = gains or {}
    return {b: clamp(gains.get(b, 0.0)) for b in BANDS}


def is_neutral(gains: dict | None) -> bool:
    return all(v == 0.0 for v in normalize(gains).values())


def filter_args(gains: dict | None) -> list[str]:
    """['-af', chain] or [] when neutral. Boosts get an alimiter ceiling."""
    g = normalize(gains)
    parts = [_FILTER[b].format(g=g[b]) for b in BANDS if g[b] != 0.0]
    if not parts:
        return []
    if any(v > 0 for v in g.values()):
        parts.append("alimiter=limit=0.89:level=disabled")      # ~ -1 dBFS ceiling
    return ["-af", ",".join(parts)]


def compose(tone: dict | None, tenband_active: bool) -> tuple[list[str], str]:
    """Filter args plus a note; never double-filter with the 10-band EQ."""
    if is_neutral(tone):
        return [], ""
    if tenband_active:
        return [], "Tone knobs are off while the 10-band equaliser is on."
    return filter_args(tone), ""


class Room:
    """Revisioned shared knob state with per-band rate limiting."""

    def __init__(self) -> None:
        self.gains = normalize(None)
        self.revision = 0
        self._last: dict[str, float] = {}

    def set(self, band: str, value, expected_revision: int, now: float) -> tuple[bool, str]:
        if band not in BANDS:
            return False, "Unknown control."
        if expected_revision != self.revision:
            return False, "Someone else changed this. Showing the latest."
        if now - self._last.get(band, -1e9) < MIN_INTERVAL_S:
            return False, "Too fast."
        new = clamp(value)
        if new != self.gains[band]:
            self.gains[band] = new
            self.revision += 1
        self._last[band] = now
        return True, ""

    def reset(self) -> None:
        self.gains = normalize(None)
        self.revision += 1
