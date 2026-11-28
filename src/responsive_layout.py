"""Pure geometry decisions for the GTK4 responsive layout.

All dimensions are GTK logical pixels.  Separating the thresholds from GTK
lets us test resize behaviour without a display or PyGObject installed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import density


# Below this window width the side panel (queue, devices, room, settings, info)
# moves underneath the player instead of sitting beside it.
STACK_BELOW = 940
PANEL_MIN, PANEL_MAX = 360, 460
# The tab switcher drops its text labels (icons only) below this panel width.
TABS_LABELS_MIN = 400
# Height of the header bar, for fitting the player into the viewport.
HEADER_HEIGHT = 47


@dataclass(frozen=True)
class Layout:
    stacked: bool
    compact: bool
    transport_wrapped: bool
    actions_wrapped: bool
    margin: int
    spacing: int
    preview_height: int
    # Width reserved for the side panel; 0 while it is stacked under the player.
    panel_width: int = 0
    # Buttons per row in the action strip (Open / Cast / Preview / Stop).
    action_columns: int = 4
    # True when the tab switcher must show icons only to fit the width.
    tabs_icon_only: bool = False


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

    Keep a modest allowance for task bars/decorations and never open larger
    than 85 % of the monitor, so a window never appears to be full screen (an
    old saved or default size can be near the monitor size). When monitor
    geometry is unavailable, use a reasonable default.
    """
    width = max(380, _dimension(configured_width, 1180))
    height = max(330, _dimension(configured_height, 760))
    screen_w = _dimension(monitor_width, 0)
    screen_h = _dimension(monitor_height, 0)
    if screen_w:
        width = min(width, max(320, min(screen_w - 72, screen_w * 85 // 100)))
    if screen_h:
        height = min(height, max(300, min(screen_h - 96, screen_h * 85 // 100)))
    return width, height


def layout_for_size(
    width: int, height: int, density_id: object = None,
    transport_min: object = None, player_fixed: object = None,
) -> Layout:
    """Choose card layout and control density from *allocated* window size.

    *density_id* (compact/comfortable/spacious, see ``density``) scales margins,
    spacing, the preview height and the widths at which control rows wrap, so
    bigger controls wrap earlier instead of being clipped. The default is the
    unscaled layout.

    Wide windows put the player beside a tabbed side panel; narrower ones stack
    the panel under the player. Every threshold is derived from the width the
    *player card* really gets, never from the window width alone.

    *transport_min* is the measured minimum width of the one-row transport
    controls (it grows with the font size). Wrapping when the card is narrower
    than that keeps the wide layout's minimum width below ``STACK_BELOW``, so a
    window can always be shrunk until it stacks. Without a measurement a
    default for the standard font is used.

    *player_fixed* is the measured height of the player card without its
    preview picture. Beside the side panel the preview then shrinks until the
    whole player (including the Cast button) fits the window instead of
    scrolling; stacked layouts scroll anyway and use a smaller share of the
    height so the side-panel tabs stay close to the fold.
    """
    scale = density.scale_for(density_id)
    width = max(1, int(width))
    height = max(1, int(height))
    stacked = width < STACK_BELOW
    compact = width < 760 or height < 720
    margin = density.px(8 if compact else 14, scale, 4)
    panel = 0 if stacked else min(PANEL_MAX, max(PANEL_MIN, int(width * 0.32)))
    page_width = width - 2 * margin
    left_width = page_width if stacked else page_width - panel - margin
    base = density.BASE_COMPACT if compact else density.BASE  # mirrors the stylesheet's .card padding
    card_padding = density.px(base["card_padding"], scale, 4)
    inner = max(1, left_width - 2 * card_padding)
    needed = _dimension(transport_min, 0) or density.px(560, scale)
    # A 16:9 picture, but never more than ~36 % (wide) / 30 % (stacked) of the
    # window height, and, when measured, never so tall the player stops fitting.
    picture = min(inner * 9 // 16, int(height * (0.30 if stacked else 0.36)))
    fixed = _dimension(player_fixed, 0)
    if fixed and not stacked:
        picture = min(picture, height - HEADER_HEIGHT - 2 * margin - fixed)
    return Layout(
        stacked=stacked,
        compact=compact,
        transport_wrapped=inner < needed + density.px(24, scale),
        actions_wrapped=inner < density.px(440, scale),
        margin=margin,
        spacing=density.px(10 if compact else 14, scale, 4),
        preview_height=density.px(max(96, min(picture, 380)), scale, 60),
        panel_width=panel,
        action_columns=4 if inner >= density.px(440, scale) else 2,
        tabs_icon_only=(page_width if stacked else panel) < TABS_LABELS_MIN,
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
