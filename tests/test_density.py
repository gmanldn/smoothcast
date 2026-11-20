"""Interface density presets (issue #136): pure scaling, CSS, layout and config. No GTK."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import config_control
import density
import preference_choices
import responsive_layout as rl
import ui_theme

CSS = ui_theme.CSS.decode("utf-8")


# --- presets ---------------------------------------------------------------------

def test_presets_are_bounded_ordered_and_default_is_comfortable():
    ids = [p for p, _l, _s in density.PRESETS]
    scales = [s for _p, _l, s in density.PRESETS]
    assert ids == ["compact", "comfortable", "spacious"] and density.DEFAULT_ID == "comfortable"
    assert scales == sorted(scales) and scales[1] == 1.0 and 0.5 <= min(scales) and max(scales) <= 1.5
    assert density.IDS == frozenset(ids)


@pytest.mark.parametrize("junk", [None, 5, "", "tiny", "COMPACT", " compact", ["compact"], "<script>"])
def test_unknown_values_fall_back_to_comfortable(junk):
    assert density.normalize(junk) == "comfortable"
    assert density.scale_for(junk) == 1.0 and density.css_for(junk) == ""


def test_px_scales_rounds_and_never_goes_below_the_minimum():
    assert density.px(18, 1.0) == 18 and density.px(18, 0.85) == 15 and density.px(18, 1.25) == 22
    assert density.px(1, 0.1) == 1 and density.px(2, 0.1, 4) == 4


# --- the numbers must mirror the real stylesheet ----------------------------------------

def rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", CSS, re.S)
    assert match, f"{selector} not found in ui_theme.CSS"
    return match.group(1)


def value(selector: str, prop: str) -> list[int]:
    body = rule(selector)
    found = re.search(prop + r":\s*([0-9px ]+);", body)
    assert found, f"{prop} not found in {selector}"
    return [int(n) for n in re.findall(r"\d+", found.group(1))]


def test_base_values_mirror_ui_theme():
    b, c = density.BASE, density.BASE_COMPACT
    assert value(".card", "padding") == [b["card_padding"]]
    assert value(".card.hero-card", "padding") == [b["hero_padding"]]
    assert value(".empty-state", "padding") == [b["empty_padding"]]
    assert value(".chip, .device-badge", "padding") == [b["chip_pad_y"], b["chip_pad_x"]]
    assert value("button.big-play", "min-width") == [b["big_play"]]
    assert value("button.big-play", "min-height") == [b["big_play"]]
    assert value("button.transport", "min-width") == [b["transport"]]
    assert value("button.action-control", "min-width") == [b["action_min_width"]]
    assert value(".setting-group", "margin-top") == [b["setting_group_top"]]
    assert value(".volume-row", "margin-top") == [b["volume_row_top"]]
    assert value(".compact .card", "padding") == [c["card_padding"]]
    assert value(".compact button.big-play", "min-width") == [c["big_play"]]
    assert value(".compact button.transport", "min-width") == [c["transport"]]
    assert value(".compact button.transport-step, .compact button.pill", "padding") == [c["pill_pad_y"], c["pill_pad_x"]]


# --- generated CSS -----------------------------------------------------------------------

def declared_numbers(css: str, selector: str, prop: str) -> list[int]:
    match = re.search(re.escape(selector) + r"\s*\{[^}]*?" + prop + r":\s*([0-9px ]+);", css)
    assert match, (selector, prop)
    return [int(n) for n in re.findall(r"\d+", match.group(1))]


def test_default_adds_no_override_and_others_scale_every_rule():
    assert density.css_for("comfortable") == ""
    compact, spacious = density.css_for("compact"), density.css_for("spacious")
    for css in (compact, spacious):
        assert css.count("{") == css.count("}")
        declared = set(re.findall(r"([a-z-]+):\s*\d", css))
        assert declared == {"padding", "min-width", "min-height", "margin-top"}
        assert not re.search(r"url\(|@import|expression", css, re.I)
    for selector, prop in ((".card", "padding"), ("button.big-play", "min-width"),
                           ("button.transport", "min-height"), (".compact .card", "padding")):
        small = declared_numbers(compact, selector, prop)[0]
        big = declared_numbers(spacious, selector, prop)[0]
        assert small < big, (selector, prop, small, big)


def test_spacious_and_compact_scale_from_the_base_values():
    spacious = density.css_for("spacious")
    assert declared_numbers(spacious, ".card", "padding") == [density.px(density.BASE["card_padding"], 1.25)]
    assert declared_numbers(spacious, "button.big-play", "min-width") == [density.px(density.BASE["big_play"], 1.25)]
    compact = density.css_for("compact")
    assert declared_numbers(compact, ".compact button.transport", "min-width") == [density.px(density.BASE_COMPACT["transport"], 0.85)]


# --- the responsive layout -----------------------------------------------------------------

@pytest.mark.parametrize("size,expected", [
    ((1600, 1000), rl.Layout(False, False, False, False, 14, 14, 190)),
    ((900, 700), rl.Layout(True, True, False, False, 8, 10, 145)),
    ((360, 800), rl.Layout(True, True, True, True, 8, 10, 145)),
    ((500, 600), rl.Layout(True, True, True, True, 8, 10, 110)),   # left width 484 < 490: actions wrap
])
def test_default_layout_is_exactly_the_unscaled_one(size, expected):
    assert rl.layout_for_size(*size) == expected
    assert rl.layout_for_size(*size, "comfortable") == expected
    assert rl.layout_for_size(*size, "nonsense") == expected


def test_density_scales_margins_spacing_and_preview_height():
    compact = rl.layout_for_size(1600, 1000, "compact")
    normal = rl.layout_for_size(1600, 1000)
    spacious = rl.layout_for_size(1600, 1000, "spacious")
    assert compact.margin < normal.margin < spacious.margin
    assert compact.spacing < normal.spacing < spacious.spacing
    assert compact.preview_height < normal.preview_height < spacious.preview_height


def test_bigger_controls_wrap_earlier_so_nothing_is_clipped():
    # Find a width where the comfortable transport row just fits: spacious must already wrap there.
    width = next(w for w in range(500, 1200) if not rl.layout_for_size(w, 900).transport_wrapped)
    assert rl.layout_for_size(width, 900, "spacious").transport_wrapped
    assert not rl.layout_for_size(width, 900, "compact").transport_wrapped
    for name in ("compact", "comfortable", "spacious"):
        narrow = rl.layout_for_size(360, 800, name)
        assert narrow.stacked and narrow.transport_wrapped and narrow.actions_wrapped


def test_scaled_layout_values_keep_sane_minimums():
    for name in ("compact", "spacious"):
        for width, height in ((1, 1), (360, 300), (5000, 5000)):
            layout = rl.layout_for_size(width, height, name)
            assert layout.margin >= 4 and layout.spacing >= 4 and layout.preview_height >= 60


# --- configuration and choices ----------------------------------------------------------------

def test_config_loader_accepts_only_known_densities():
    defaults = {"density": "comfortable"}
    assert config_control.sanitise_config({"density": "spacious"}, defaults)["density"] == "spacious"
    for bad in ("huge", "", None, 3, ["compact"], "Compact"):
        assert config_control.sanitise_config({"density": bad}, defaults)["density"] == "comfortable"


def test_preference_choices_mirror_the_presets():
    assert [v for _l, v in preference_choices.OPTIONS["density"]] == ["compact", "comfortable", "spacious"]
    assert preference_choices.labels("density") == ["Compact", "Comfortable", "Spacious"]
    assert preference_choices.selected_index("density", "comfortable") == 1
    assert preference_choices.selected_value("density", 2) == "spacious"


# --- wiring -------------------------------------------------------------------------------------

def test_wiring_density_provider_layout_and_text_fit_pass():
    control = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    assert "STYLE_PROVIDER_PRIORITY_APPLICATION + 2" in control and "apply_density(load_config().get(\"density\"))" in control
    prefs = (ROOT / "src" / "preferences_ui.py").read_text(encoding="utf-8")
    assert 'key == "density"' in prefs and "apply_density(value)" in prefs and "_refresh_responsive_layout()" in prefs
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")
    reflow = ui.split("def _refresh_responsive_layout", 1)[1]
    assert 'layout_for_size(width, height, self.cfg.get("density"))' in reflow
    assert reflow.index("text_fit.fit_labels(self)") < reflow.index("if state == self._layout_state")
    assert '"density": "comfortable"' in (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name in ('"density"', '"text_fit"', "src/density.py", "src/responsive_layout.py"):
        assert name in toml


def test_text_fit_never_overrides_deliberate_settings_and_is_narrow_only():
    source = (ROOT / "src" / "text_fit.py").read_text(encoding="utf-8")
    assert "get_ellipsize() == Pango.EllipsizeMode.NONE and not widget.get_wrap()" in source
    assert "NARROW_WIDTH = 1000" in source
