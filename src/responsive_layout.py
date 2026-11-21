"""Pure geometry decisions for the GTK4 responsive layout.

All dimensions are GTK logical pixels.  Separating the thresholds from GTK
lets us test resize behaviour without a display or PyGObject installed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import density


@dataclass(frozen=True)
class Layout:
    stacked: bool
    compact: bool
    transport_wrapped: bool
    actions_wrapped: bool
    margin: int
    spacing: int
    preview_height: int


def _dimension(raw: object, default: int) -> int:
    if not isinstance(raw, (int, float, str)):
        return default
    try:
        number = float(raw)
        if not math.isfinite(number) or number <= 0:
            return default
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return default


def window_size(
    configured_width: object, configured_height: object,
    monitor_width: object = None, monitor_height: object = None,
) -> tuple[int, int]:
    """Preserve a preferred size but never request more than the screen.

    Keep a modest allowance for task bars/decorations.  When monitor geometry
    is unavailable, use a reasonable default instead of forcing fullscreen.
    """
    width = max(380, _dimension(configured_width, 1180))
    height = max(330, _dimension(configured_height, 760))
    screen_w = _dimension(monitor_width, 0)
    screen_h = _dimension(monitor_height, 0)
    if screen_w:
        width = min(width, max(320, screen_w - 72))
    if screen_h:
        height = min(height, max(300, screen_h - 96))
    return width, height


def layout_for_size(width: int, height: int, density_id: object = None) -> Layout:
    """Choose card layout and control density from *allocated* window size.

    *density_id* (compact/comfortable/spacious, see ``density``) scales margins,
    spacing, the preview height and the widths at which control rows wrap, so
    bigger controls wrap earlier instead of being clipped. The default is the
    unscaled layout.
    """
    scale = density.scale_for(density_id)
    width = max(1, int(width))
    height = max(1, int(height))
    stacked = width < 1180
    compact = width < 1000 or height < 800
    margin = density.px(8 if compact else 14, scale, 4)
    # Wide mode reserves a natural-width settings column (~440 logical px).
    left_width = width - 440 - 2 * margin - 14 if not stacked else width - 2 * margin
    return Layout(
        stacked=stacked,
        compact=compact,
        transport_wrapped=left_width < density.px(680, scale),
        actions_wrapped=left_width < density.px(490, scale),
        margin=margin,
        spacing=density.px(10 if compact else 14, scale, 4),
        preview_height=density.px(110 if height < 700 else (145 if compact else 190), scale, 60),
    )


def remember_normal_size(
    allocated_width: object, allocated_height: object,
    previous: tuple[int, int], *, fullscreen: bool, maximized: bool,
) -> tuple[int, int]:
    """Save only an actual normal GTK allocation, never a fullscreen extent.

    GTK's get_default_size() is a preferred/default size, not a reliable
    measurement of a manually resized window.  Do not learn temporary
    compositor allocations (fullscreen/maximised/hidden/zero-size).
    """
    if fullscreen or maximized:
        return previous
    width = _dimension(allocated_width, 0)
    height = _dimension(allocated_height, 0)
    if width < 320 or height < 300:
        return previous
    return width, height
