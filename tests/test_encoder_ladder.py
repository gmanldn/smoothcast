import encoder_ladder as e

ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 (codec h264)
 V....D h264_vaapi           H.264/AVC (VAAPI) (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
"""
FILTERS = """Filters:
  T.. = Timeline support
 ... overlay          VV->V      Overlay one video on top of another.
 T.C loudnorm         A->A       EBU R128 loudness normalization
 ..C alimiter         A->A       Audio lookahead limiter.
"""


def test_parse_encoders_ignores_audio_and_legend():
    got = e.parse_encoders(ENCODERS)
    assert got == {"libx264", "h264_vaapi", "h264_nvenc"}


def test_parse_filters_and_missing_report():
    got = e.parse_filters(FILTERS)
    assert {"overlay", "loudnorm", "alimiter"} <= got
    msgs = e.missing_filters(got)
    assert any("libass" in m for m in msgs) and any("acompressor" in m for m in msgs)
    assert len(msgs) == 2


def test_ladder_trusts_only_verified_hardware_and_ends_in_x264():
    enc = e.parse_encoders(ENCODERS)
    assert e.ladder("linux", enc) == ["libx264"]
    assert e.ladder("linux", enc, {"h264_vaapi": True}) == ["h264_vaapi", "libx264"]
    assert e.ladder("linux", enc, {"h264_nvenc": False, "h264_vaapi": True}) == ["h264_vaapi", "libx264"]
    assert e.ladder("darwin", enc, {"h264_videotoolbox": True}) == ["libx264"]  # not in build


def test_untested_and_cache_key():
    enc = e.parse_encoders(ENCODERS)
    assert e.untested("linux", enc, {"h264_nvenc": False}) == ["h264_vaapi"]
    assert e.cache_key("6.1  build", "Intel  HD", "i965") == "6.1 build|Intel HD|i965"
    assert e.parse_encoders(None) == frozenset()
