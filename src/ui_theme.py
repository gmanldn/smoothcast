"""SmoothCast visual system: readable, calm, native GTK4 media controls.

CSS selectors are intentionally simple GTK4/Adwaita nodes or explicit app classes.
Keep all contrast-critical colours centralized here instead of scattering one-off
overrides across the UI widgets.
"""
from __future__ import annotations

import ui_tokens


def is_dark_hour(hour: int) -> bool:
    """True during the scheduled night window (19:00–06:59 local time)."""
    return hour >= 19 or hour < 7


# Libadwaita supplies the paired foreground and background colours for each
# appearance, including high contrast. Native controls retain their own states.
CSS = """
/* ---- Surfaces ---------------------------------------------------------- */
.card {
    padding: 18px;
    border-radius: 16px;
    background-color: @card_bg_color;
    color: @card_fg_color;
    border: 1px solid alpha(@card_fg_color, 0.12);
}
.card.hero-card {
    padding: 22px;
    background-image: linear-gradient(160deg, alpha(@accent_bg_color, 0.10), transparent 48%);
}
.card .heading {
    font-size: 1.05em;
    font-weight: 700;
}
.eyebrow {
    color: @accent_color;
    font-size: 0.8em;
    font-weight: 800;
    letter-spacing: 1px;
}
.hero-title {
    font-size: 1.65em;
    font-weight: 800;
}
.hero-subtitle, .section-caption { font-size: 0.95em; }
.card .caption, .empty-subtitle, .detail-key, .console-idle { font-size: 0.9em; }
.setting-group, .detail-section, .meter-legend, .volume-label {
    color: @accent_color;
    font-size: 0.85em;
    font-weight: 700;
    letter-spacing: 0.5px;
}
.setting-group { margin-top: 8px; }
.label-strong, .queue-title, .detail-value { font-weight: 600; }
.mono, .console-line { font-family: monospace; }
.preview-frame {
    border-radius: 12px;
    border: 1px solid alpha(@card_fg_color, 0.14);
}

/* ---- Status chips ------------------------------------------------------ */
.chip, .device-badge {
    border-radius: 99px;
    padding: 4px 10px;
    font-size: 0.85em;
    font-weight: 700;
    background-color: alpha(currentColor, 0.09);
}
.chip.playing, .device-badge.online { color: @success_color; background-color: alpha(@success_color, 0.16); }
.chip.paused, .chip.buffering { color: @warning_color; background-color: alpha(@warning_color, 0.16); }
.chip.error, .chip.offline, .device-badge.offline { color: @error_color; background-color: alpha(@error_color, 0.16); }

/* ---- Transport and actions ---------------------------------------------- */
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
    box-shadow: 0 3px 10px alpha(@accent_bg_color, 0.38);
}
button.big-play:disabled { box-shadow: none; }
button.transport, button.transport-step, button.pill { border-radius: 99px; min-height: 44px; }
button.transport { min-width: 44px; min-height: 44px; padding: 0; }
button.transport-step { min-width: 48px; padding: 0 6px; font-weight: 700; font-size: 0.92em; }
button.stop-control { color: @error_color; }
button.action-control { min-width: 84px; min-height: 44px; font-weight: 600; }
.volume-row { margin-top: 6px; }
.volume-row button.flat { min-width: 38px; min-height: 38px; }
.actions-strip flowboxchild { padding: 0; }
.actions-strip flowboxchild:focus { outline: none; }
.seekbar:focus-visible { outline: 2px solid @accent_color; outline-offset: 2px; border-radius: 8px; }
.receiver-row { margin-top: 2px; }
dropdown.receiver-online > button { box-shadow: inset 3px 0 @success_color; }
dropdown.receiver-offline > button { box-shadow: inset 3px 0 @error_color; }

/* ---- Side panel (queue / devices / room / settings / info) --------------- */
.side-panel {
    border-radius: 16px;
    background-color: @card_bg_color;
    color: @card_fg_color;
    border: 1px solid alpha(@card_fg_color, 0.12);
}
.side-panel .panel-tabs { padding: 6px 6px 0 6px; }
.side-panel .panel-tabs viewswitcher { min-height: 54px; }
.tab-badge {
    border-radius: 99px;
    padding: 0 6px;
    min-height: 16px;
    font-size: 0.75em;
    font-weight: 800;
    background-color: @accent_bg_color;
    color: @accent_fg_color;
}
.tab-badge.attention { background-color: @warning_color; color: @window_bg_color; }
.side-panel .panel-sep { min-height: 1px; background-color: alpha(@card_fg_color, 0.12); }
.side-panel .card {
    padding: 14px 16px;
    border-radius: 0;
    border: none;
    background: none;
}
.side-panel .card:not(:first-child) { border-top: 1px solid alpha(@card_fg_color, 0.10); }
.side-panel scrolledwindow, .side-panel viewport { background: none; }

/* ---- Queue --------------------------------------------------------------- */
row.queue-row { border-radius: 10px; }
row.queue-row.current {
    background-color: alpha(@accent_bg_color, 0.14);
    box-shadow: inset 3px 0 @accent_color;
}
row.queue-row.current .queue-title { color: @accent_color; }
.queue-meta { margin-top: 2px; }
.empty-state {
    padding: 18px;
    border-radius: 12px;
    background-color: alpha(@card_fg_color, 0.045);
}
.empty-icon { color: @accent_color; }
.empty-title { font-size: 1.1em; font-weight: 700; }
.mini-divider { min-height: 1px; background-color: alpha(currentColor, 0.15); }

/* ---- Compact (small windows) ---------------------------------------------- */
.compact .card { padding: 12px; border-radius: 12px; }
.compact .side-panel .card { padding: 10px 12px; border-radius: 0; }
.compact .hero-title { font-size: 1.35em; }
.compact button.big-play { min-width: 52px; min-height: 52px; }
.compact button.transport { min-width: 44px; min-height: 44px; }
.compact button.transport-step, .compact button.pill { min-height: 44px; padding: 5px 5px; }
.compact button.transport-step { min-width: 40px; }
""".encode("utf-8")
CSS = ui_tokens.snap_gtk_radii(CSS)
