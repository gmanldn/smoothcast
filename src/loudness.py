"""Optional EBU R128 loudness normalisation for the transcoded audio chain.

The receiver gets the same two-channel AAC stream as before; this module only
adds FFmpeg's ``loudnorm`` filter when the user opts in. Programme and album
targets are conservative broadcast-style presets, and the filter's true-peak
limiter keeps intersample peaks below -1.5 dBFS. It never changes system-wide
audio or the local preview's device volume.

Pure module: no GTK, processes or network.
"""
from __future__ import annotations

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