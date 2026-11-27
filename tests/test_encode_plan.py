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
