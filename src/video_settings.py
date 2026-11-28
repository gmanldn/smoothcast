"""Typed, validated view of the video-related config keys (#693). GTK-free.

Callers read `VideoSettings.from_config(cfg)` instead of scattering
`cfg.get("rotation")`-style lookups with their own defaults; a hand-edited or
corrupt config falls back to the default instead of reaching ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass

QUALITIES = ("high", "balanced", "saver")
ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class VideoSettings:
    quality: str = "balanced"
    quality_auto: bool = True      # CPU probe picks quality until the user chooses
    rotation: int = 0
    aspect_override: str = "original"
    show_cover_art: bool = True

    @classmethod
    def from_config(cls, cfg: object) -> "VideoSettings":
        data = cfg if isinstance(cfg, dict) else {}
        quality = data.get("quality")
        rotation = data.get("rotation")
        aspect = data.get("aspect_override")
        return cls(
            quality=quality if quality in QUALITIES else "balanced",
            quality_auto=data.get("quality_auto", True) is not False,
            rotation=rotation if type(rotation) is int and rotation in ROTATIONS else 0,
            aspect_override=aspect if isinstance(aspect, str) and aspect else "original",
            show_cover_art=data.get("show_cover_art", True) is not False,
        )
