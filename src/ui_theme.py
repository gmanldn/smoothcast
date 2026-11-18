"""SmoothCast visual system: readable, calm, native GTK4 media controls.

CSS selectors are intentionally simple GTK4/Adwaita nodes or explicit app classes.
Keep all contrast-critical colours centralized here instead of scattering one-off
overrides across the UI widgets.
"""
from __future__ import annotations

PALETTE = {
    "canvas": "#0b111b",
    "surface": "#151f2d",
    "surface_raised": "#1b293b",
    "stroke": "#2b3b50",
    "text": "#eef4ff",
    "muted": "#9fb0c9",
    "accent": "#79baff",
    "success": "#77ddb2",
    "warning": "#ffd17d",
    "danger": "#ff8995",
}

CSS = """
window {
    font-size: 14px;
    color: #eef4ff;
    background-color: #0b111b;
}
headerbar {
    min-height: 52px;
    background-color: #0c1521;
    border-bottom: 1px solid #29384e;
    box-shadow: none;
}
.dim-label {
    opacity: 0.93;
    color: #a6bad1;
}
headerbar .title {
    font-size: 17px;
    font-weight: 800;
    color: #f4f8ff;
}
headerbar .subtitle {
    font-size: 12px;
    color: #a9bdd5;
}
.card {
    padding: 20px;
    border-radius: 18px;
    border: 1px solid #2b3b50;
    background-color: #151f2d;
    box-shadow: 0 5px 16px rgba(0, 0, 0, 0.12);
}
.card.hero-card {
    border: 1px solid #385470;
    background-image: linear-gradient(to bottom right, #1a2b40, #131e2c);
}
.card.device-card {
    border-color: #35516b;
}
.card.settings-card {
    background-color: #141e2c;
}
.card.meter-card {
    border-color: #34506b;
    background-image: linear-gradient(to bottom right, #182739, #131e2b);
}
.card.queue-card {
    background-color: #141e2c;
}
.card.activity-card, .card.diagnostics-card {
    background-color: #121d2a;
}
.card .heading {
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 1.1px;
    color: #bdcde3;
}
.card .caption, .caption {
    font-size: 12px;
    color: #a4b4cc;
}
.hero-title {
    font-size: 24px;
    font-weight: 750;
    color: #f7faff;
}
.hero-subtitle {
    font-size: 13px;
    color: #b2c4da;
}
.section-caption {
    font-size: 13px;
    color: #adc0d8;
}
.setting-group {
    margin-top: 9px;
    color: #86baff;
    letter-spacing: 1px;
    font-size: 11px;
    font-weight: 800;
}
.setting-row {
}
.label-strong {
    font-weight: 600;
    color: #e3edfc;
}
.mono {
    font-family: monospace;
    font-size: 12px;
}
.chip {
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 750;
    border: 1px solid #3a526d;
}
.chip.idle {
    background-color: #21364d;
    color: #b9d7fa;
}
.chip.playing {
    border-color: #386f5a;
    background-color: #194734;
    color: #a2efd0;
}
.chip.buffering {
    border-color: #76623b;
    background-color: #4a3921;
    color: #ffe4ac;
}
.chip.paused {
    background-color: #524126;
    color: #ffe0a0;
}
.chip.offline, .chip.error {
    border-color: #8a4351;
    background-color: #532935;
    color: #ffbac1;
}
.device-badge {
    border-radius: 999px;
    padding: 5px 10px;
    background-color: #223146;
    color: #aac0da;
    font-size: 11px;
    font-weight: 750;
}
.device-badge.online {
    background-color: #194735;
    color: #a7edc8;
}
.device-badge.offline {
    background-color: #482936;
    color: #ffd0d3;
}
button {
    border-radius: 10px;
    padding: 8px 13px;
    font-size: 13px;
    font-weight: 650;
    color: #e7f1ff;
    background-color: #233349;
    border: 1px solid #334961;
    box-shadow: none;
}
button:hover {
    background-color: #2a405a;
    border-color: #628bb9;
}
button:active {
    background-color: #344e6b;
}
button:disabled {
    opacity: 0.50;
}
button.suggested-action, button.primary-action {
    color: #0c1c2b;
    background-color: #79baff;
    border-color: #9ccfff;
    font-weight: 800;
}
button.suggested-action:hover, button.primary-action:hover {
    background-color: #a0d0ff;
    border-color: #c0e1ff;
}
button.destructive-action {
    color: #ffc1c6;
    background-color: #322932;
    border-color: #58404d;
}
button.destructive-action:hover {
    background-color: #60323e;
}
button.flat {
    background-color: transparent;
    border-color: transparent;
}
button.flat:hover {
    background-color: #283a52;
}
button.big-play {
    min-width: 66px;
    min-height: 66px;
    border-radius: 33px;
    background-color: #7bbcff;
    border-color: #a8d5ff;
    color: #102238;
}
button.big-play:hover {
    background-color: #a3d3ff;
}
button.transport {
    min-width: 44px;
    min-height: 44px;
    border-radius: 13px;
    background-color: #223247;
}
button.transport-step, button.pill {
    min-width: 43px;
    border-radius: 12px;
    color: #c7d7ec;
    background-color: #1c2b3e;
    border-color: #2e445e;
}
button.transport-step:hover, button.pill:hover {
    color: #ffffff;
    background-color: #294461;
}
button.stop-control {
    color: #ffbac3;
}
button.action-control {
    min-width: 84px;
}
.volume-row {
    margin-top: 6px;
    margin-bottom: 2px;
}
.volume-label {
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.8px;
    color: #9cb5d1;
}
scale trough {
    min-height: 6px;
    border-radius: 3px;
    background-color: #304158;
}
scale highlight {
    background-color: #71b7ff;
    border-radius: 3px;
}
scale slider {
    min-width: 17px;
    min-height: 17px;
    border-radius: 50%;
    border: 2px solid #d6eaff;
    background-color: #76baff;
}
dropdown, spinbutton, entry {
    border-radius: 10px;
    background-color: #202f43;
    border: 1px solid #364b65;
    color: #f0f6ff;
}
dropdown:hover, spinbutton:hover, entry:hover {
    border-color: #659bcf;
}
switch:checked {
    background-color: #318bc6;
}
.queue-title {
    font-size: 13px;
    font-weight: 650;
    color: #e3ecfb;
}
.queue-row.current .queue-title {
    color: #94c9ff;
}
row.queue-row {
    border-bottom: 1px solid #27374b;
}
.empty-state {
    margin-top: 10px;
    padding: 20px;
    border: 1px dashed #39536e;
    border-radius: 14px;
    background-color: #172537;
}
.empty-icon {
    color: #78baff;
}
.empty-title {
    font-size: 15px;
    font-weight: 750;
    color: #eef4ff;
}
.empty-subtitle {
    font-size: 12px;
    color: #a4b7d1;
}
.meter-legend {
    font-size: 11px;
    font-weight: 700;
    color: #82bbff;
}
.detail-key {
    font-size: 12px;
    color: #a1b3cb;
}
.detail-value {
    font-size: 12px;
    font-weight: 600;
    color: #e5effc;
}
.detail-section {
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.9px;
    color: #7dbdff;
}
.console-idle {
    color: #a4b6ce;
    font-size: 12px;
}
.console-line {
    font-family: monospace;
    color: #c8d9ef;
    font-size: 12px;
}
.mini-divider {
    min-height: 1px;
    background-color: #2b3e56;
}
statuspage {
    color: #a4b6ce;
}
label {
    text-shadow: none;
}
separator {
    background-color: #2c4056;
}
/* Compact state is applied to the native window at the responsive breakpoint. */
.compact .card {
    padding: 13px;
    border-radius: 13px;
}
.compact .hero-title {
    font-size: 20px;
}
.compact button.big-play {
    min-width: 56px;
    min-height: 56px;
}
.compact button.transport {
    min-width: 38px;
    min-height: 38px;
}
.compact button.transport-step, .compact button.pill {
    min-width: 37px;
    min-height: 36px;
    padding: 5px 8px;
}
""".encode("utf-8")
