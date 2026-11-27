import inspect
import streamer


def test_subtitle_burn_in_gets_longer_startup_window():
    src = inspect.getsource(streamer.Session.start_transcode)
    assert "timeout *= 3" in src and "embedded_subtitle_index is not None" in src
    assert "ffmpeg was silent" in src
