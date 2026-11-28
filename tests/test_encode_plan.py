from encode_plan import Capabilities, Media, choose, plan_encode, plan_sequence

HEVC10_SUBS = Media(codec="hevc", bit_depth=10, burn_subtitles=True)
HW = Capabilities(hw_encoder="h264_vaapi", hw_decodes=frozenset({"h264", "hevc"}))


def test_golden_10bit_hevc_with_burned_subtitles_is_software_with_a_reason():
    plan = plan_encode(HEVC10_SUBS, HW)
    assert plan.profile == "software" and "burned subtitles" in plan.reason
    assert plan.argv == ("-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                         "-vf", "format=yuv420p")


def test_hardware_used_when_qualified_and_able_to_decode():
    plan = plan_encode(Media(codec="hevc"), HW)
    assert (plan.profile, plan.encoder) == ("hardware", "h264_vaapi")
    assert plan.argv == ("-c:v", "h264_vaapi")


def test_each_software_reason_is_distinct():
    assert "no qualified" in plan_encode(Media(), Capabilities()).reason
    cap = Capabilities(hw_encoder="h264_vaapi", hw_decodes=frozenset({"h264"}))
    assert "cannot decode hevc" in plan_encode(Media(codec="hevc"), cap).reason


def test_slow_machine_degrades_to_a_lighter_plan_instead_of_timing_out():
    caps = Capabilities(speed={"software": 0.52, "software-720p": 1.4})
    plan, degraded = choose(HEVC10_SUBS, caps)
    assert degraded and plan.profile == "software-720p" and plan.height == 720
    assert "scale=-2:720" in plan.argv[-1]


def test_nothing_fast_enough_still_returns_the_lightest_plan():
    caps = Capabilities(speed={"software": 0.2, "software-720p": 0.4, "software-480p": 0.7})
    plan, degraded = choose(HEVC10_SUBS, caps)
    assert degraded and plan.profile == "software-480p"


def test_unmeasured_plan_is_trusted_and_not_degraded():
    plan, degraded = choose(Media(), HW)
    assert plan.profile == "hardware" and not degraded
    assert [p.profile for p in plan_sequence(Media(), HW)][:2] == ["hardware", "software"]


import pytest

NO_HW = Capabilities()
SW = ("-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p")
VA = ("-c:v", "h264_vaapi")
# (media, caps, expected profile, expected argv): the golden matrix. Rotation filters mirror
# streamer._ROTATION_FILTERS; VAAPI round trips mirror streamer._filter_args.
GOLDEN = [
    (Media(), NO_HW, "software", SW),
    (Media(bit_depth=10), NO_HW, "software", SW + ("-vf", "format=yuv420p")),
    (Media(codec="hevc", height=2160, width=3840), NO_HW, "software", SW),
    (Media(rotation=90), NO_HW, "software", SW + ("-vf", "transpose=1")),
    (Media(rotation=180), NO_HW, "software", SW + ("-vf", "transpose=2,transpose=2")),
    (Media(rotation=270, bit_depth=10), NO_HW, "software",
     SW + ("-vf", "transpose=2,format=yuv420p")),
    (Media(burn_subtitles=True), HW, "software", SW),
    (Media(), HW, "hardware", VA),
    (Media(codec="hevc"), HW, "hardware", VA),
    (Media(codec="vp9"), HW, "software", SW),
    (Media(bit_depth=10), HW, "hardware",
     VA + ("-vf", "hwdownload,format=p010le,format=nv12,hwupload")),
    (Media(rotation=90), HW, "hardware",
     VA + ("-vf", "hwdownload,format=nv12,transpose=1,hwupload")),
]


@pytest.mark.parametrize("media,caps,profile,argv", GOLDEN)
def test_golden_argv_matrix(media, caps, profile, argv):
    plan = plan_encode(media, caps)
    assert (plan.profile, plan.argv) == (profile, argv)
    assert plan.reason  # every plan says why it chose hardware or software


def test_rotated_portrait_is_scaled_by_its_output_height():
    # 1920x1080 rotated 90 degrees is 1080 wide x 1920 tall: the 720p profile scales that.
    plan = plan_sequence(Media(rotation=90), NO_HW)[1]
    assert plan.profile == "software-720p" and plan.height == 720
    assert plan.argv[-1] == "transpose=1,scale=-2:720,format=yuv420p"
    # An unrotated 1080p source has no 1080p+ profile above it either way.
    assert [p.profile for p in plan_sequence(Media(width=1280, height=720), NO_HW)] == [
        "software", "software-480p"]


def test_hardware_failure_sequence_falls_back_to_software_with_rotation_kept():
    seq = plan_sequence(Media(rotation=90), HW)
    assert [p.profile for p in seq][:2] == ["hardware", "software"]
    assert seq[1].argv[-1] == "transpose=1"
