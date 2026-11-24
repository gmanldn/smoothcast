"""Screen and dashboard colours share the web room's semantic token system (#525)."""
from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import design_tokens
import portal_screen_page


def test_screen_page_serves_shared_dark_light_and_high_contrast_tokens():
    html = portal_screen_page.screen_page().decode("utf-8")
    assert "/*TOKENS*/" not in html
    assert 'content="dark light"' in html
    assert "@media(prefers-color-scheme:light)" in html
    assert "@media(prefers-contrast:more)" in html
    for scheme in ("dark", "light"):
        colors = design_tokens.SCHEMES[scheme]
        assert f"--bg:{colors['bg']}" in html
        assert f"--card:{colors['card']}" in html
        assert f"--text:{colors['text']}" in html
        assert f"--accent:var(--sc-user-accent-{scheme}, {colors['accent']})" in html
        assert f"--on-accent:var(--sc-user-on-accent-{scheme}, {colors['on_accent']})" in html
        assert design_tokens.contrast_ratio(colors["text"], colors["bg"]) >= 4.5
        assert design_tokens.contrast_ratio(colors["on_accent"], colors["accent"]) >= 4.5


def test_screen_css_has_no_independent_literal_palette():
    html = portal_screen_page.screen_page().decode("utf-8")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ":root{--bg:" in css
    # The only literal colour values are inside design_tokens.css().
    token_end = css.index("@media(prefers-contrast:more) and (prefers-color-scheme:light)")
    body = css[css.index("}}", token_end) + 2:]
    assert not re.search(r"(?<=:)\s*#[0-9a-fA-F]{3,8}\b", body), "Use shared semantic colour tokens"
    assert "var(--accent)" in body and "var(--text)" in body
    assert "var(--qr-paper)" in body
    assert "--qr-paper:#ffffff" in css
    assert "--ink:" not in body and "--mut:" not in body


def test_screen_dashboard_panel_reuses_host_room_tokens():
    panel = portal_screen_page.panel_html()
    assert "background:var(--input)" in panel
    assert "border:1px solid var(--border)" in panel
    assert "color:var(--danger)" in panel
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", panel.split("</style>", 1)[0])


def test_screen_palette_has_no_credential_or_network_side_effects():
    # GTK-free generation; private state is never inserted into the page markup.
    html = portal_screen_page.screen_page()
    assert b"<script>" in html and b"__MIMES__" not in html
    assert b"localStorage.getItem" in html
    assert b"sc_portal_session=" not in html

def test_theme_colour_audit_distinguishes_numeric_ids_from_literal_values():
    # A CSS selector may legitimately be '#420'; its digits are not a colour.
    value_colour = re.compile(r"(?<=:)\\s*#[0-9a-fA-F]{3,8}\\b")
    assert not value_colour.search("#420{display:block}")
    assert not value_colour.search("#fff{background:var(--card)}")
    assert value_colour.search(".screen{background: #123abc;}")
    assert value_colour.search(".screen{border-color:#fff;}")
