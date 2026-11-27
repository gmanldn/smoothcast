import pytest

from video_settings import VideoSettings


def test_defaults_for_empty_or_non_dict_config():
    assert VideoSettings.from_config({}) == VideoSettings()
    assert VideoSettings.from_config(None) == VideoSettings()


def test_valid_values_are_kept():
    v = VideoSettings.from_config({"quality": "saver", "quality_auto": False, "rotation": 270,
                                   "aspect_override": "16:9", "show_cover_art": False})
    assert (v.quality, v.quality_auto, v.rotation, v.aspect_override, v.show_cover_art) == \
        ("saver", False, 270, "16:9", False)


@pytest.mark.parametrize("bad", [45, "90", None, True, 360, -90])
def test_bad_rotation_falls_back(bad):
    assert VideoSettings.from_config({"rotation": bad}).rotation == 0


def test_bad_quality_and_aspect_fall_back():
    v = VideoSettings.from_config({"quality": "ultra", "aspect_override": ""})
    assert v.quality == "balanced" and v.aspect_override == "original"
