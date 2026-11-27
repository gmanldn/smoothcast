"""The FFmpeg version query is paid at window start, not on the first cast."""
from pathlib import Path


def test_window_timers_warm_the_ffmpeg_version_check_off_thread():
    source = (Path(__file__).resolve().parents[1] / "src" / "cast_ui_timers.py").read_text()
    start = source.index("def _start_window_timers")
    body = source[start:source.index("def _publish_core_status")]
    assert "Async.run(streamer.require_compatible_ffmpeg" in body
