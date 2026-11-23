"""Pure SC-103 picture-adjustment validation and filter contracts."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import picture_adjustments


def test_neutral_settings_never_modify_video():
    assert picture_adjustments.filters({}) == []
    assert not picture_adjustments.active({})
    assert picture_adjustments.settings(None) == picture_adjustments.DEFAULTS


def test_adjustments_compose_without_shell_interpolation():
    cfg = {"picture_brightness": 0.2, "picture_contrast": 1.25,
           "picture_saturation": 0.8, "picture_hue": -45}
    assert picture_adjustments.filters(cfg) == [
        "eq=brightness=0.2:contrast=1.25:saturation=0.8",
        "hue=h=-45",
    ]
    assert picture_adjustments.active(cfg)


def test_invalid_values_fail_to_neutral_not_injected_into_filters():
    bad = ("1;rm -rf /", True, None, float("nan"), float("inf"),
           -float("inf"), 10**500)
    for key in picture_adjustments.DEFAULTS:
        for value in bad:
            assert picture_adjustments.validated(key, value) == picture_adjustments.DEFAULTS[key]
            assert picture_adjustments.filters({key: value}) == []


def test_bounds_are_inclusive_and_out_of_range_settings_are_rejected():
    for key, (low, high) in picture_adjustments.BOUNDS.items():
        assert picture_adjustments.validated(key, low) == low
        assert picture_adjustments.validated(key, high) == high
        assert picture_adjustments.validated(key, low - 1) == picture_adjustments.DEFAULTS[key]
        assert picture_adjustments.validated(key, high + 1) == picture_adjustments.DEFAULTS[key]


def test_brightness_and_hue_do_not_emit_unneeded_filters():
    assert picture_adjustments.filters({"picture_hue": 12}) == ["hue=h=12"]
    assert picture_adjustments.filters({"picture_brightness": -0.1}) == [
        "eq=brightness=-0.1:contrast=1:saturation=1"
    ]


def test_config_loader_rejects_malformed_picture_settings():
    import config_control
    defaults = picture_adjustments.DEFAULTS.copy()
    corrupted = {key: "bad" for key in defaults}
    assert config_control.sanitise_config(corrupted, defaults) == defaults
    expected = defaults | {"picture_brightness": 0.3, "picture_hue": 90.0}
    assert config_control.sanitise_config(expected, defaults) == expected


def test_transcode_filter_precedes_subtitle_overlay_and_handles_bitmap():
    import streamer
    config = {"picture_brightness": 0.1}
    args = streamer.Session()._filter_args(
        True, Path("/tmp/subs.srt"), True, 1.0,
        picture_config=config,
    )
    assert args[0] == "-vf"
    assert args[1].startswith("eq=brightness=0.1:contrast=1:saturation=1,")
    assert args[1].index("eq=") < args[1].index("subtitles=")
    bitmap = streamer.Session()._filter_args(
        True, None, True, 1.0, embedded_subtitle_index=0,
        embedded_bitmap=True, picture_config=config,
    )
    assert bitmap[0] == "-filter_complex"
    assert bitmap[1].index("eq=") < bitmap[1].index("overlay=")


def test_session_cast_and_restart_pass_picture_config():
    import ast
    text = (Path(__file__).resolve().parents[1] / "src" / "cast_session.py").read_text()
    tree = ast.parse(text)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "start_transcode"]
    assert len(calls) >= 2
    assert all("picture_config" in {kw.arg for kw in call.keywords} for call in calls)
    assert "not picture_adjustments.active(cfg)" in text
