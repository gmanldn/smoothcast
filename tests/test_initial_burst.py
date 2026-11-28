"""Casts start sooner with an initial readrate burst, never on a growing upload (#686)."""
import ffmpeg_compat
import streamer


def test_burst_needs_a_verified_ffmpeg_6_1(monkeypatch):
    monkeypatch.setattr(ffmpeg_compat, "_verified", {})
    assert ffmpeg_compat.initial_burst_args() == []
    monkeypatch.setattr(ffmpeg_compat, "_verified", {("ff", 1, 2): (5, 0)})
    assert ffmpeg_compat.initial_burst_args() == []
    monkeypatch.setattr(ffmpeg_compat, "_verified", {("ff", 1, 2): (7, 1)})
    assert ffmpeg_compat.initial_burst_args() == ["-readrate_initial_burst", "10"]


def test_guest_uploads_never_burst(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    upload = tmp_path / streamer.paths.APP_DIR / "portal-uploads" / "a.mkv"
    assert streamer._may_still_be_arriving(upload) is True
    assert streamer._may_still_be_arriving(tmp_path / "Films" / "a.mkv") is False
