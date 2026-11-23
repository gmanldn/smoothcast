"""Output cap and configuration contracts for the 720p low-end tier (#515)."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_control  # noqa: E402
import streamer  # noqa: E402

SCALE_720 = ("scale=w=1280:h=720:force_original_aspect_ratio=decrease:"
             "force_divisible_by=2")


def filters(*, quality="balanced", width=1920, height=1080, bitmap=False, software=True):
    return streamer.Session()._filter_args(
        False, None, software, 1.0,
        video_size=(width, height),
        video_stream_index=0,
        embedded_bitmap=bitmap,
        embedded_subtitle_index=0 if bitmap else None,
        quality=quality,
    )


def test_software_saver_really_caps_1080p_and_4k_at_720p():
    assert SCALE_720 in filters(quality="saver")[1]
    assert SCALE_720 in filters(quality="saver", width=3840, height=2160)[1]


def test_small_source_never_upscaled_and_balanced_1080p_keeps_resolution():
    assert filters(quality="saver", width=640, height=360) == []
    assert filters(quality="balanced", width=1920, height=1080) == []


def test_bitmap_overlay_keeps_subtitles_and_caps_software_output():
    result = filters(quality="saver", bitmap=True)
    assert result[0] == "-filter_complex"
    assert "overlay=eof_action=pass:repeatlast=0" in result[1]
    assert SCALE_720 in result[1]
    assert result[1].endswith("[v]")


def test_hardware_and_high_quality_maintain_original_paths():
    assert SCALE_720 not in "".join(filters(quality="saver", software=False))
    assert SCALE_720 not in "".join(filters(quality="high", software=True))


def test_software_encoder_preserves_fast_preset_and_lower_priority_implementation():
    args = streamer.Session()._codec_args("saver", software=True)
    assert args[args.index("-preset") + 1] in {"veryfast", "superfast"}
    source = (Path(__file__).resolve().parents[1] / "src" / "streamer.py").read_text()
    assert "process_priority.lower(self.ffmpeg" in source


def test_existing_quality_preference_remains_manual_on_upgrade():
    defaults = {"quality": "balanced", "quality_auto": True}
    assert config_control.sanitise_config({}, defaults)["quality_auto"] is True
    cfg = config_control.sanitise_config({"quality": "high"}, defaults)
    assert cfg == {"quality": "high", "quality_auto": False}
    cfg = config_control.sanitise_config(
        {"quality": "balanced", "quality_auto": True}, defaults)
    assert cfg["quality_auto"] is True
    cfg = config_control.sanitise_config(
        {"quality": "saver", "quality_auto": False}, defaults)
    assert cfg["quality_auto"] is False


def test_quality_ui_exposes_explicit_manual_override():
    root = Path(__file__).resolve().parents[1] / "src"
    assert '"quality_auto", "Automatically choose video quality"' in (
        root / "preferences_ui.py").read_text()
    assert 'self.cfg["quality_auto"] = False' in (root / "cast_av.py").read_text()
    assert 'low_end_policy.schedule_probe(enabled=bool' in (root / "cast_control.py").read_text()
    content = (root / "cast_session.py").read_text()
    assert content.count("low_end_policy.effective_quality(cfg, media)") == 2
