import art_source as a

FILM = {"streams": [
    {"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}},
    {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 0}},
    {"index": 2, "codec_type": "audio"}]}


def test_attached_pic_is_not_the_motion_stream():
    assert a.motion_video_index(FILM) == 1
    assert a.embedded_art_index(FILM) == 0


def test_prefers_embedded_then_frame_then_none():
    assert a.choose(FILM, 100) == {"kind": "embedded", "stream": 0}
    no_art = {"streams": [FILM["streams"][1]]}
    assert a.choose(no_art, 100) == {"kind": "frame", "stream": 1, "position": 10.0}
    assert a.choose({"streams": [{"index": 0, "codec_type": "audio"}]}, 100) is None


def test_opt_out_and_garbage():
    assert a.choose(FILM, 100, enabled=False) is None
    assert a.choose(None, 100) is None and a.choose({"streams": 3}, 100) is None


def test_frame_position_bounds():
    assert a.frame_position(0) == 0.0 and a.frame_position(float("nan")) == 0.0
    assert a.frame_position(5) == 1.0 and a.frame_position(1) == 0.5
    assert a.frame_position(100000) == 120.0
