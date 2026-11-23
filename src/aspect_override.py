"""Bounded, square-pixel FFmpeg geometry for output aspect overrides."""
from __future__ import annotations

from typing import Final

MODES: Final = ("original", "16:9", "4:3", "fit", "fill", "crop")


def normalize(mode: object) -> str:
    return mode if isinstance(mode, str) and mode in MODES else "original"


def filters(mode: object, *, width: int = 1920, height: int = 1080) -> list[str]:
    """Transform a rotated source to a bounded 16:9 canvas or 4:3 stretch."""
    selected = normalize(mode)
    if selected == "original":
        return []
    if selected in {"16:9", "4:3"}:
        stretched = width if selected == "16:9" else (height * 2 // 3) * 2
        return [f"scale={stretched}:{height}", "setsar=1"]
    if selected == "fit":
        # DAR includes the source pixel aspect, unlike the raw width/height.
        scale = (f"scale=w='max(2,min({width},2*trunc({height}*dar/2)))':"
                 f"h='max(2,min({height},2*trunc({width}/dar/2)))'")
        return [scale, "setsar=1", f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"]

    crop = ("crop=w='if(gte(dar,16/9),ih*16/(9*sar),iw)':"
            "h='if(gte(dar,16/9),ih,iw*sar*9/16)'")
    if selected == "fill":
        return [crop, f"scale={width}:{height}", "setsar=1"]
    # Crop without upscaling the source vertically. Width follows the 16:9
    # display shape even when the incoming pixels are anamorphic.
    scale = (f"scale=w='max(2,min({width},2*trunc(oh*8/9)))':"
             f"h='max(2,2*trunc(min({height},ih)/2))'")
    return [crop, scale, "setsar=1"]
