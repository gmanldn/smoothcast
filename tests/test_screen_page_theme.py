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
        assert f"--accent:{colors['accent']}" in html
        assert design_tokens.contrast_ratio(colors["text"], colors["bg"]) >= 4.5
        assert design_tokens.contrast_ratio(colors["on_accent"], colors["accent"]) >= 4.5


def test_screen_css_has_no_independent_literal_palette():
    html = portal_screen_page.screen_page().decode("utf-8")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert css.startswith("\\n:root{--bg:") or ":root{--bg:" in css
    # The only literal colour values are inside design_tokens.css().
    token_end = css.index("@media(prefers-contrast:more) and (prefers-color-scheme:light)")
    body = css[css.index("}}", token_end) + 2:]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\\b", body)
    assert "var(--accent)" in body and "var(--text)" in body
    assert "--ink:" not in body and "--mut:" not in body


def test_screen_dashboard_panel_reuses_host_room_tokens():
    panel = portal_screen_page.panel_html()
    assert "background:var(--input)" in panel
    assert "border:1px solid var(--border)" in panel
    assert "color:var(--danger)" in panel
    assert not re.search(r"#[0-9a-fA-F]{3,8}\\b", panel.split("</style>", 1)[0])


def test_screen_palette_has_no_credential_or_network_side_effects():
    # GTK-free generation; private state is never inserted into the page markup.
    html = portal_screen_page.screen_page()
    assert b"<script>" in html and b"__MIMES__" not in html
    assert b"localStorage.getItem" in html
    assert b"sc_portal_session=" not in html
