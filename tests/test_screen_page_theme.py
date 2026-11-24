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


def _literal_css_colours(css: str) -> list[str]:
    """Inspect declaration values, not selector IDs or issue-number comments.

    This generated stylesheet has ordinary flat declaration blocks nested in
    @media rules. Search all values, including shorthand and gradient stops.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    values = (
        declaration.partition(":")[2]
        for block in re.findall(r"\{([^{}]*)\}", css)
        for declaration in block.split(";")
        if ":" in declaration
    )
    return [
        match
        for value in values
        for match in re.findall(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b", value)
    ]


def test_screen_css_has_no_independent_literal_palette():
    html = portal_screen_page.screen_page().decode("utf-8")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ":root{--bg:" in css
    # The only literal colour values are inside design_tokens.css().
    token_end = css.index("@media(prefers-contrast:more) and (prefers-color-scheme:light)")
    body = css[css.index("}}", token_end) + 2:]
    assert not _literal_css_colours(body), "Use shared semantic colour tokens"
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
    assert not _literal_css_colours("#420{display:block}")
    assert not _literal_css_colours("#fff{background:var(--card)}")
    assert not _literal_css_colours("/* Issue #420 */ .screen{color:var(--text)}")
    assert _literal_css_colours(".screen{background: #123abc;}") == ["#123abc"]
    assert _literal_css_colours(".screen{border:1px solid #fff;}") == ["#fff"]
    assert _literal_css_colours(".screen{background:linear-gradient(#1234,#12345678)}") == [
        "#1234", "#12345678",
    ]
    assert _literal_css_colours("@media(prefers-color-scheme:light){.screen{color:#abc}}") == ["#abc"]


def test_video_overlay_has_theme_independent_readable_colours():
    for scheme in design_tokens.SCHEMES.values():
        assert design_tokens.contrast_ratio(scheme["media_text"], scheme["media_surface"]) >= 4.5
    assert design_tokens.FORCED["media_text"] == "CanvasText"
    assert design_tokens.FORCED["media_surface"] == "Canvas"
    html = portal_screen_page.screen_page().decode("utf-8")
    for selector in ("#hud", "#banner"):
        rule = re.search(re.escape(selector) + r"\{([^}]+)\}", html).group(1)
        assert "background:var(--media-surface)" in rule
        assert "color:var(--media-text)" in rule
    assert "#hud .meta{display:flex;justify-content:space-between;gap:12px;color:var(--media-text)" in html


def test_screen_controls_remain_reachable_on_short_or_narrow_viewports():
    html = portal_screen_page.screen_page().decode("utf-8")
    assert "align-items:safe center;overflow:auto" in html
    assert "#tools.hide:focus-within{opacity:1;pointer-events:auto}" in html
    assert "@media(max-width:600px)" in html
    assert "@media(prefers-reduced-motion:reduce){#hud,#tools,.home-link,.screen-version{transition:none}}" in html
