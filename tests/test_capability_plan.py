"""#11: per-session compatibility plan from probed receiver capabilities."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import capability_plan as cp
from capability_plan import CAST_BASELINE, MediaFacts, ReceiverCaps, Request, plan_session

GOOD = MediaFacts(container="mp4", video_codec="h264", audio_codec="aac", height=1080)


def test_known_compatible_media_plays_direct_with_native_seek():
    plan = plan_session(CAST_BASELINE, GOOD)
    assert (plan.mode, plan.video, plan.audio, plan.seek) == ("direct", "copy", "copy", "native")
    assert plan.subtitles == "none" and not plan.conservative and plan.notes == ()


def test_unknown_receiver_is_never_assumed_to_support_direct():
    plan = plan_session(ReceiverCaps(), GOOD)
    assert plan.mode == "transcode" and plan.conservative
    assert plan.video == "encode" and plan.audio == "encode"
    assert any("not confirmed" in n for n in plan.notes)


def test_wrong_container_with_good_codecs_is_a_remux_not_a_transcode():
    plan = plan_session(CAST_BASELINE, MediaFacts("mkv", "h264", "aac", 1080))
    assert (plan.mode, plan.video, plan.audio, plan.seek) == ("remux", "copy", "copy", "restart_at_offset")
    assert any("repackaging" in n for n in plan.notes) and not plan.conservative


@pytest.mark.parametrize("media,field", [
    (MediaFacts("mp4", "hevc", "aac", 1080), "video"),
    (MediaFacts("mp4", "h264", "dts", 1080), "audio"),
])
def test_unsupported_codec_forces_transcode_of_only_that_stream(media, field):
    plan = plan_session(CAST_BASELINE, media)
    assert plan.mode == "transcode" and getattr(plan, field) == "encode"
    other = "audio" if field == "video" else "video"
    assert getattr(plan, other) == "copy"
    assert not plan.conservative  # known-unsupported, not unknown


def test_resolution_over_the_receiver_limit_scales_down():
    plan = plan_session(CAST_BASELINE, MediaFacts("mp4", "h264", "aac", 2160))
    assert plan.mode == "transcode" and plan.scale_to_height == 1080 and plan.video == "encode"
    assert plan_session(CAST_BASELINE, GOOD).scale_to_height is None
    assert plan_session(ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",),
                                           audio_codecs=("aac",), seekable=True), 
                        MediaFacts("mp4", "h264", "aac", 4320)).scale_to_height is None  # unknown limit


def test_hdr_needs_confirmed_hdr_support_or_is_tone_mapped():
    hdr = MediaFacts("mp4", "h264", "aac", 1080, hdr=True)
    assert plan_session(CAST_BASELINE, hdr).mode == "transcode"
    unknown = ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac",),
                                 seekable=True)
    assert plan_session(unknown, hdr).conservative
    capable = ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac",),
                                 hdr=True, seekable=True)
    assert plan_session(capable, hdr).mode == "direct"


@pytest.mark.parametrize("kind,fmt,expected,mode", [
    ("none", "", "none", "direct"),
    ("sidecar", "vtt", "sidecar", "direct"),
    ("sidecar", "srt", "burn_in", "transcode"),
    ("sidecar", "ass", "burn_in", "transcode"),
    ("embedded", "", "burn_in", "transcode"),
])
def test_subtitle_strategy(kind, fmt, expected, mode):
    plan = plan_session(CAST_BASELINE, MediaFacts("mp4", "h264", "aac", 720, subtitle_kind=kind,
                                                   subtitle_format=fmt))
    assert (plan.subtitles, plan.mode) == (expected, mode)


def test_speed_is_native_only_when_the_receiver_lists_it():
    plan = plan_session(CAST_BASELINE, GOOD, Request(speed=1.5))
    assert plan.mode == "transcode" and not plan.speed_native
    fast = ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac",),
                              seekable=True, speeds=(1.0, 1.5), hdr=False)
    ok = plan_session(fast, GOOD, Request(speed=1.5))
    assert ok.mode == "direct" and ok.speed_native


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0, 99, "fast", True])
def test_hostile_speed_values_fall_back_to_normal_speed(bad):
    plan = plan_session(CAST_BASELINE, GOOD, Request(speed=bad))
    assert plan.mode == "direct" and plan.speed_native


def test_rotation_and_audio_processing_force_the_matching_conversion():
    assert plan_session(CAST_BASELINE, GOOD, Request(rotation=90)).video == "encode"
    plan = plan_session(CAST_BASELINE, GOOD, Request(audio_processing=True))
    assert (plan.mode, plan.audio, plan.video) == ("transcode", "encode", "copy")
    assert plan_session(CAST_BASELINE, GOOD, Request(rotation=360)).mode == "direct"


def test_seek_without_confirmed_range_support_never_plays_direct():
    caps = ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac",),
                              hdr=False, seekable=False)
    assert plan_session(caps, GOOD).mode == "remux"
    assert plan_session(caps, GOOD, Request(needs_seek=False)).mode == "direct"
    unknown = ReceiverCaps.build(containers=("mp4",), video_codecs=("h264",), audio_codecs=("aac",),
                                 hdr=False)
    plan = plan_session(unknown, GOOD)
    assert plan.mode == "remux" and plan.conservative


def test_learned_history_can_veto_direct_but_never_grant_it():
    assert plan_session(CAST_BASELINE, GOOD, Request(prior_direct="failed")).mode == "remux"
    worked = plan_session(CAST_BASELINE, GOOD, Request(prior_direct="worked"))
    assert worked.mode == "direct" and any("worked" in n for n in worked.notes)
    bad = MediaFacts("mp4", "hevc", "aac", 1080)
    assert plan_session(CAST_BASELINE, bad, Request(prior_direct="worked")).mode == "transcode"


def test_audio_only_media_ignores_video_and_subtitle_rules():
    music = MediaFacts("mp3", "", "mp3", 0, audio_only=True, subtitle_kind="sidecar", subtitle_format="srt")
    caps = ReceiverCaps.build(containers=("mp3",), audio_codecs=("mp3",), seekable=True)
    plan = plan_session(caps, music)
    assert (plan.mode, plan.video, plan.audio, plan.subtitles) == ("direct", "none", "copy", "none")


def test_media_without_audio_stream_is_not_forced_to_encode_audio():
    plan = plan_session(CAST_BASELINE, MediaFacts("mp4", "h264", "", 720))
    assert plan.mode == "direct" and plan.audio == "none"


def test_case_whitespace_and_garbage_in_probe_data_are_normalised_or_ignored():
    caps = ReceiverCaps.build(containers=(" MP4 ", "bad token!", 7), video_codecs=("H264",),
                              audio_codecs=("AAC",), max_height=10**9, seekable="yes", hdr=False)
    assert caps.containers == frozenset({"mp4"}) and caps.max_height is None and caps.seekable is None
    assert plan_session(caps, MediaFacts("MP4", "H264", "AAC", 1080), Request(needs_seek=False)).mode == "direct"


@pytest.mark.parametrize("mimes,containers", [
    (["video/mp4", "audio/mpeg"], {"mp4", "mp3"}),
    (["VIDEO/MPEG"], {"mpegts"}),
    (["*"], {"mp4", "mpegts"}),
    (["application/x-unknown"], None),
    ([], None),
])
def test_dlna_sink_types_become_container_capabilities_with_unknown_codecs(mimes, containers):
    caps = cp.caps_from_http_formats(iter(mimes))
    assert caps.containers == (frozenset(containers) if containers else None)
    assert caps.video_codecs is None and caps.audio_codecs is None
    assert plan_session(caps, GOOD).mode == "transcode"  # codecs unknown => conservative


def test_plan_is_deterministic_and_immutable():
    assert plan_session(CAST_BASELINE, GOOD) == plan_session(CAST_BASELINE, GOOD)
    with pytest.raises(Exception):
        plan_session(CAST_BASELINE, GOOD).mode = "transcode"
