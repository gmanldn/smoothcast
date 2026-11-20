"""SmoothCast visual system: readable, calm, native GTK4 media controls.

CSS selectors are intentionally simple GTK4/Adwaita nodes or explicit app classes.
Keep all contrast-critical colours centralized here instead of scattering one-off
overrides across the UI widgets.
"""
from __future__ import annotations


def is_dark_hour(hour: int) -> bool:
    """True during the scheduled night window (19:00–06:59 local time)."""
    return hour >= 19 or hour < 7


# Libadwaita supplies the paired foreground and background colours for each
# appearance, including high contrast. Native controls retain their own states.
CSS = """
.card {
    padding: 18px;
    border-radius: 14px;
    background-color: @card_bg_color;
    color: @card_fg_color;
    border: 1px solid alpha(@card_fg_color, 0.14);
}
.card.hero-card {
    padding: 22px;
    background-image: linear-gradient(145deg, alpha(@accent_bg_color, 0.10), transparent 55%);
}
.card .heading {
    font-size: 1.08em;
    font-weight: 700;
}
.hero-title {
    font-size: 1.7em;
    font-weight: 800;
}
.hero-subtitle, .section-caption { font-size: 0.96em; }
.card .caption, .empty-subtitle, .detail-key, .console-idle { font-size: 0.9em; }
.setting-group, .detail-section, .meter-legend, .volume-label {
    color: @accent_color;
    font-size: 0.9em;
    font-weight: 700;
}
.setting-group { margin-top: 8px; }
.label-strong, .queue-title, .detail-value { font-weight: 600; }
.mono, .console-line { font-family: monospace; }
.chip, .device-badge {
    border-radius: 99px;
    padding: 4px 10px;
    font-size: 0.87em;
    font-weight: 700;
    background-color: alpha(currentColor, 0.09);
}
.chip.playing, .device-badge.online { color: @success_color; }
.chip.paused, .chip.buffering { color: @warning_color; }
.chip.error, .chip.offline, .device-badge.offline { color: @error_color; }
button.big-play, button.primary-action {
    color: @accent_fg_color;
    background-color: @accent_bg_color;
}
button.big-play:hover, button.primary-action:hover {
    background-color: mix(@accent_bg_color, @window_fg_color, 0.12);
}
button.big-play {
    min-width: 62px;
    min-height: 62px;
    padding: 0;
    border-radius: 99px;
}
button.transport, button.transport-step, button.pill { border-radius: 10px; min-height: 44px; }
button.transport { min-width: 44px; min-height: 44px; padding: 3px; }
button.stop-control { color: @error_color; }
button.action-control { min-width: 84px; min-height: 44px; }
.volume-row { margin-top: 6px; }
row.queue-row { border-radius: 8px; }
row.queue-row.current {
    background-color: alpha(@accent_bg_color, 0.12);
    box-shadow: inset 3px 0 @accent_color;
}
.empty-state {
    padding: 18px;
    border-radius: 10px;
    background-color: alpha(@card_fg_color, 0.045);
}
.empty-icon { color: @accent_color; }
.empty-title { font-size: 1.1em; font-weight: 700; }
.mini-divider { min-height: 1px; background-color: alpha(currentColor, 0.15); }
.compact .card { padding: 12px; border-radius: 11px; }
.compact .hero-title { font-size: 1.4em; }
.compact button.big-play { min-width: 52px; min-height: 52px; }
.compact button.transport { min-width: 44px; min-height: 44px; }
.compact button.transport-step, .compact button.pill { min-height: 44px; padding: 5px 5px; }
""".encode("utf-8")
