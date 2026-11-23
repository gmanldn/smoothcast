"""Validated FFmpeg filters for reversible output aspect overrides."""
from __future__ import annotations

from typing import Final

MODES: Final = ("original", "16:9", "4:3", "fit", "fill", "crop")


def normalize(mode: object) -> str:
    return mode if isinstance(mode, str) and mode in MODES else "original"


def filters(mode: object) -> list[str]:
    """Return post-rotation video filters; originals are never modified."""
    selected = normalize(mode)
    if selected == "16:9":
        return ["setdar=16/9"]
    if selected == "4:3":
        return ["setdar=4/3"]
    if selected == "fit":
        return [
            "scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2",
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2", "setsar=1",
        ]
    if selected == "fill":
        return [
            "scale=1920:1080:force_original_aspect_ratio=increase:force_divisible_by=2",
            "crop=1920:1080", "setsar=1",
        ]
    if selected == "crop":
        return [
            "crop=w='if(gte(iw/ih,16/9)\\,ih*16/9\\,iw)':"
            "h='if(gte(iw/ih,16/9)\\,ih\\,iw*9/16)'", "setsar=1",
        ]
    return []
