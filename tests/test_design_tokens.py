"""Web remote design tokens (#447): dark unchanged, light and high contrast readable."""
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


def test_dark_values_are_the_colours_the_page_always_used():
    golden = {"bg": "#101722", "card": "#1c2735", "accent": "#4d9de0", "muted": "#b7c3d0",
              "text": "#f4f7fb", "input": "#121b27", "danger": "#ffb4a9", "focus": "#ffd166"}
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
