"""Web remote design tokens (#447): shared brand, light and high contrast readable."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import design_tokens as dt
import portal

TEXT_PAIRS = [("text", "bg"), ("text", "card"), ("muted", "card"), ("muted", "bg"), ("dim", "card"),
              ("dim", "bg"), ("danger", "card"), ("on_accent", "accent"), ("on_secondary", "secondary"),
              ("on_vote", "vote"), ("on_nav", "nav"), ("on_nav", "nav_hover"), ("text", "input")]
UI_PAIRS = [("focus", "bg"), ("focus", "card"), ("border", "card"), ("border", "bg"), ("accent", "card")]


def test_schemes_define_the_same_tokens():
    assert set(dt.DARK) == set(dt.LIGHT)


def test_dark_values_match_smoothcast_brand():
    golden = {"bg": "#0B1220", "card": "#151F30", "accent": "#76C7FF", "muted": "#B7C4D6",
              "text": "#F4F7FB", "input": "#101A2A", "danger": "#FFB4A9", "focus": "#FFD166"}
    assert {k: dt.DARK[k] for k in golden} == golden


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_text_pairs_meet_wcag_aa(scheme):
    colours = dt.SCHEMES[scheme]
    for fg, bg in TEXT_PAIRS:
        assert dt.contrast_ratio(colours[fg], colours[bg]) >= 4.5, (scheme, fg, bg)
    for fg, bg in UI_PAIRS:
        assert dt.contrast_ratio(colours[fg], colours[bg]) >= 3.0, (scheme, fg, bg)


def test_contrast_formula_matches_known_values():
    assert dt.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert dt.contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_high_contrast_uses_full_text_colour():
    css = dt.css()
    assert "@media(prefers-contrast:more)" in css
    assert f"--muted:{dt.DARK['text']}" in css and f"--muted:{dt.LIGHT['text']}" in css


def test_served_page_follows_light_dark_and_contrast_preferences():
    html = portal._HTML
    assert "/*TOKENS*/" not in html
    assert "@media(prefers-color-scheme:light)" in html
    assert "@media(prefers-contrast:more)" in html
    style = html[html.index("<style>"):html.index("</style>")]
    root_end = style.index("@media(prefers-contrast:more) and (prefers-color-scheme:light)")
    rest = style[style.index("}}", root_end) + 2:]
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", rest) == [], "hard-coded colour outside the token block"
    assert "button.secondary{background:var(--secondary);color:var(--on-secondary)}" in style


def test_forced_colors_maps_every_surface_to_system_colours():
    css = dt.css()
    block = css[css.index("@media(forced-colors:active)"):]
    assert "#" not in block, "forced-colors must use system colours only"
    assert "--sc-user" not in block, "a custom accent must not override the user's palette"
    assert "--bg:Canvas;" in block and "--text:CanvasText;" in block
    assert "--accent:Highlight;--on-accent:HighlightText;" in block
    # every override names a real token, and text/surface pairs stay paired
    assert set(dt.FORCED) <= set(dt.DARK)
    assert dt.FORCED["on_secondary"] == "ButtonText" and dt.FORCED["secondary"] == "ButtonFace"
    assert dt.FORCED["on_nav"] == "ButtonText" and dt.FORCED["nav_hover"] == "ButtonFace"
    assert dt.FORCED["on_accent"] == "HighlightText" and dt.FORCED["accent"] == "Highlight"


def test_both_pages_serve_forced_colors_support():
    import portal_screen_page
    assert "@media(forced-colors:active)" in portal._HTML
    assert "@media(forced-colors:active)" in portal_screen_page.screen_page().decode()


def test_dark_gtk_and_web_tokens_golden_parity():
    """#525 acceptance: golden parity test connecting dark GTK colors and web tokens."""
    import accent
    import ui_theme
    assert dt.DARK["bg"] == "#0B1220"
    assert dt.DARK["card"] == "#151F30"
    assert dt.DARK["text"] == "#F4F7FB"
    default_accent = accent.accent_hex(accent.DEFAULT_ID)
    assert default_accent == "#79baff"
    web_presets = dt.web_accents()
    for pid, _lbl, _hex in accent.PRESETS:
        assert pid in web_presets
        assert "dark" in web_presets[pid] and "light" in web_presets[pid]
    css_str = ui_theme.CSS.decode("utf-8")
    assert "@card_bg_color" in css_str
    assert "@card_fg_color" in css_str
    assert "@accent_bg_color" in css_str
    assert "@accent_fg_color" in css_str


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_custom_accent_presets_meet_text_contrast_on_room_surfaces(scheme):
    colours = dt.SCHEMES[scheme]
    for preset, variants in dt.web_accents().items():
        pair = variants[scheme]
        assert dt.contrast_ratio(pair["on_accent"], pair["accent"]) >= 4.5, (preset, scheme)
        for surface in ("bg", "card", "input"):
            assert dt.contrast_ratio(pair["accent"], colours[surface]) >= 4.5, (preset, scheme, surface)


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_brand_primary_and_selected_vote_contrast(scheme):
    colours = dt.SCHEMES[scheme]
    for surface in ("bg", "card", "input"):
        assert dt.contrast_ratio(colours["accent"], colours[surface]) >= 4.5
    assert dt.contrast_ratio("#ffffff", colours["vote_on"]) >= 4.5
