"""Interface density presets: compact, comfortable (default) and spacious (issue #136 / SC-127).

GTK-free and standard library only. A density is a single scale factor applied to
spacing and control sizes in two places: the responsive layout (page margins,
column spacing, preview height and the widths at which control rows wrap) and an
extra CSS provider that scales SmoothCast's own paddings and minimum control sizes.
"Comfortable" is the stylesheet as designed and adds no override at all.

The numbers below mirror the base values in ``ui_theme.CSS``; tests keep the two
in step, so a stylesheet change that is not mirrored here fails loudly.
"""
from __future__ import annotations

DEFAULT_ID = "comfortable"

# (id, label, scale)
PRESETS: tuple[tuple[str, str, float], ...] = (
    ("compact", "Compact", 0.85),
    (DEFAULT_ID, "Comfortable", 1.0),
    ("spacious", "Spacious", 1.25),
)
IDS = frozenset(preset_id for preset_id, _label, _scale in PRESETS)
_SCALES = {preset_id: scale for preset_id, _label, scale in PRESETS}

# Base values (px) from ui_theme.CSS, for the normal and the ".compact" layout state.
BASE = {
    "card_padding": 18, "hero_padding": 22, "empty_padding": 18,
    "chip_pad_y": 4, "chip_pad_x": 10,
    "big_play": 62, "transport": 40, "action_min_width": 84,
    "setting_group_top": 8, "volume_row_top": 6,
}
BASE_COMPACT = {
    "card_padding": 12, "big_play": 52, "transport": 36, "pill_pad_y": 5, "pill_pad_x": 8,
}


def normalize(value: object) -> str:
    """A valid density id, or ``comfortable`` for anything else (never raises)."""
    return value if isinstance(value, str) and value in IDS else DEFAULT_ID


def scale_for(value: object) -> float:
    return _SCALES[normalize(value)]


def px(base: int, scale: float, minimum: int = 1) -> int:
    """*base* pixels scaled and rounded, never below *minimum*."""
    return max(minimum, int(round(base * scale)))


def css_for(value: object) -> str:
    """Override CSS for a density; empty for the default (no override at all)."""
    density = normalize(value)
    if density == DEFAULT_ID:
        return ""
    s = scale_for(density)
    n, c = BASE, BASE_COMPACT
    return f"""
.card {{ padding: {px(n['card_padding'], s)}px; }}
.card.hero-card {{ padding: {px(n['hero_padding'], s)}px; }}
.empty-state {{ padding: {px(n['empty_padding'], s)}px; }}
.chip, .device-badge {{ padding: {px(n['chip_pad_y'], s)}px {px(n['chip_pad_x'], s)}px; }}
button.big-play {{ min-width: {px(n['big_play'], s)}px; min-height: {px(n['big_play'], s)}px; }}
button.transport {{ min-width: {px(n['transport'], s)}px; min-height: {px(n['transport'], s)}px; }}
button.action-control {{ min-width: {px(n['action_min_width'], s)}px; }}
.setting-group {{ margin-top: {px(n['setting_group_top'], s)}px; }}
.volume-row {{ margin-top: {px(n['volume_row_top'], s)}px; }}
.compact .card {{ padding: {px(c['card_padding'], s)}px; }}
.compact button.big-play {{ min-width: {px(c['big_play'], s)}px; min-height: {px(c['big_play'], s)}px; }}
.compact button.transport {{ min-width: {px(c['transport'], s)}px; min-height: {px(c['transport'], s)}px; }}
.compact button.transport-step, .compact button.pill {{ padding: {px(c['pill_pad_y'], s)}px {px(c['pill_pad_x'], s)}px; }}
"""
