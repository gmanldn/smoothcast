import playback_state as ps


def test_external_details_describe_stream_without_leaking_url():
    info = {"content_type": "video/webm", "stream_type": "LIVE", "duration": None,
            "content_id": "https://r3.googlevideo.com/a/b?token=secret",
            "media_metadata": {"title": "Concert", "width": 1920, "height": 1080}}
    text = ps.external_details(info)
    assert text == "WebM video · 1920×1080 · Live · r3.googlevideo.com"
    assert "secret" not in text
    assert ps.external_media_labels(info)[0] == "Concert"


def test_external_details_length_and_lan_source_hidden():
    text = ps.external_details({"content_type": "audio/mpeg", "duration": 3725.0,
                                "content_id": "http://192.168.0.5:8000/x.mp3"})
    assert text == "MP3 audio · 1:02:05"
