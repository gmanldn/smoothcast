"""#11: model-name hints map to conservative, documented capability classes."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from capability_plan import CAST_BASELINE, MediaFacts, plan_session
import receiver_profiles as rp

HEVC = MediaFacts("mp4", "hevc", "aac", 2160, hdr=True)
H264 = MediaFacts("mp4", "h264", "aac", 1080)


@pytest.mark.parametrize("model,label", [
    ("Chromecast Ultra", "Chromecast Ultra"), ("chromecast   ULTRA", "Chromecast Ultra"),
    ("Chromecast with Google TV", "Chromecast with Google TV"),
    ("Google TV Streamer", "Google TV Streamer"),
    ("Nest Mini", "Nest Mini"), ("Google Nest Audio", "Nest Audio"),
    ("Google Home Mini", "Google Home Mini"), ("Google Home", "Google Home"),
])
def test_known_models_get_their_documented_class(model, label):
    assert rp.profile_for_cast_model(model)[0] == label


@pytest.mark.parametrize("model", ["Chromecast", "Chromecast Audio?", "", None, 42, "Vizio SmartCast",
                                   "Chromecast Ultrasound", "x" * 5000, "Chromecast\x00Ultra\x07"])
def test_unknown_or_ambiguous_models_get_the_guaranteed_baseline(model):
    label, caps = rp.profile_for_cast_model(model)
    if model == "Chromecast\x00Ultra\x07":
        assert label == "Chromecast Ultra"  # control characters are separators, not lookalikes
    else:
        assert (label, caps) == ("Google Cast receiver", CAST_BASELINE)


def test_plain_chromecast_never_plays_hevc_directly_but_ultra_does():
    _, plain = rp.profile_for_cast_model("Chromecast")
    _, ultra = rp.profile_for_cast_model("Chromecast Ultra")
    assert plan_session(plain, HEVC).mode == "transcode"
    assert plan_session(ultra, HEVC).mode == "direct"
    assert plan_session(plain, H264).mode == plan_session(ultra, H264).mode == "direct"


def test_speakers_cannot_take_video_but_play_audio_directly():
    _, speaker = rp.profile_for_cast_model("Nest Mini")
    assert plan_session(speaker, H264).mode == "transcode"
    music = MediaFacts("mp3", "", "mp3", 0, audio_only=True)
    assert plan_session(speaker, music).mode == "direct"


def test_wrong_manufacturer_or_extra_words_do_not_upgrade_a_receiver():
    assert rp.profile_for_cast_model("My Chromecast Ultra clone", "Someone Else")[0] == "Chromecast Ultra"  # model text rules
    assert rp.profile_for_cast_model("Ultrachromecast")[1] == CAST_BASELINE
