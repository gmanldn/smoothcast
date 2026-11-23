"""Aspect override values stay bounded and produce reversible FFmpeg filters."""
import aspect_override
import config_control
import streamer

DEFAULTS = {"aspect_override": "original"}


def test_supported_modes_and_distortion_are_explicit():
    assert aspect_override.normalize("16:9") == "16:9"
    assert aspect_override.normalize("corrupt") == "original"
    assert aspect_override.filters("original") == []
    assert aspect_override.filters("16:9") == ["setdar=16/9"]
    assert aspect_override.filters("4:3") == ["setdar=4/3"]
    assert "force_original_aspect_ratio=decrease" in aspect_override.filters("fit")[0]
    assert "pad=1920:1080" in aspect_override.filters("fit")[1]
    assert "force_original_aspect_ratio=increase" in aspect_override.filters("fill")[0]
    assert aspect_override.filters("fill")[1] == "crop=1920:1080"
    assert aspect_override.filters("crop")[0].startswith("crop=w=")


def test_config_accepts_only_known_aspect_override_values():
    cleaned = config_control.sanitise_config(
        {"aspect_override": "fill"}, DEFAULTS,
    )
    assert cleaned["aspect_override"] == "fill"
    cleaned = config_control.sanitise_config(
        {"aspect_override": "movie:unsafe"}, DEFAULTS,
    )
    assert cleaned["aspect_override"] == "original"


def test_aspect_filters_reach_cast_transcode_and_vaapi_uses_software_filters():
    session = streamer.Session()
    assert session._filter_args(
        False, None, True, 1.0, aspect_mode="16:9",
    ) == ["-vf", "setdar=16/9"]
    assert session._filter_args(
        False, None, False, 1.0, aspect_mode="4:3",
    ) == ["-vf", "hwdownload,format=nv12,setdar=4/3,hwupload"]
    assert session._filter_args(
        False, None, True, 1.0, aspect_mode="original",
    ) == []
