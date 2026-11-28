"""SC-028: bounded, source-owned, seek-time sidecar subtitle preview."""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest import mock

import pytest

import subtitle_encoding as enc
from gui_source import main_window_methods


def test_srt_cues_at_source_timestamps_and_markup(tmp_path):
    source = tmp_path / "film.srt"
    source.write_text(
        "1\n00:00:01,250 --> 00:00:03,000\n<i>First</i> &amp; clear\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nSecond\n\n"
        "3\n99:60:00,000 --> 99:61:00,000\nNever\n", encoding="utf-8",
    )
    cues = enc.load_timed_cues(source)
    assert enc.cue_at(cues, 0) == ""
    assert enc.cue_at(cues, 1.25) == "First & clear"
    assert enc.cue_at(cues, 2.5) == "Second"
    assert enc.cue_at(cues, 3.7) == "Second"
    assert enc.cue_at(cues, 4.0) == ""
    for value in (math.nan, math.inf, -1.0, True, "bad"):
        assert enc.cue_at(cues, value) == ""


def test_webvtt_uses_cue_identifier_and_scrub_time(tmp_path):
    source = tmp_path / "captions.vtt"
    source.write_text(
        "WEBVTT\n\nintro\n00:01.000 --> 00:02.000 align:start\nHello\n\n"
        "00:02.000 --> 00:03.000\nGoodbye\n", encoding="utf-8",
    )
    cues = enc.load_timed_cues(source)
    assert enc.cue_at(cues, 1.5) == "Hello"
    assert enc.cue_at(cues, 2.5) == "Goodbye"


def test_ass_dialogue_respects_text_commas_and_forced_overrides(tmp_path):
    source = tmp_path / "subs.ass"
    source.write_text(
        "[Script Info]\nTitle: Sample\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\i1}Hi,\Nthere"
        "\n", encoding="utf-8",
    )
    assert enc.cue_at(enc.load_timed_cues(source), 1.8) == "Hi, there"


def test_bad_unsafe_and_excessive_sources_fail_closed(tmp_path):
    bad = tmp_path / "bad.srt"
    bad.write_bytes(b"\0broken")
    with pytest.raises(enc.SubtitleEncodingError):
        enc.load_timed_cues(bad)
    huge = tmp_path / "huge.srt"
    with huge.open("wb") as handle:
        handle.truncate(enc.MAX_SUBTITLE_BYTES + 1)
    with pytest.raises(enc.SubtitleEncodingError):
        enc.load_timed_cues(huge)
    link = tmp_path / "symlink.srt"
    link.symlink_to(bad)
    with pytest.raises(enc.SubtitleEncodingError):
        enc.load_timed_cues(link)
    with pytest.raises(enc.SubtitleEncodingError):
        enc.load_timed_cues(tmp_path / "movie.mkv")


def test_embedded_extraction_maps_one_track_and_builds_source_time_cues(tmp_path, monkeypatch):
    source = tmp_path / "film.mkv"
    source.write_bytes(b"media")
    output = (b"1\n00:00:02,000 --> 00:00:04,000\nEmbedded line\n\n")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return mock.Mock(returncode=0, stdout=output)

    monkeypatch.setattr(enc.subprocess, "run", run)
    cues = enc.load_embedded_timed_cues(source, 3)
    assert enc.cue_at(cues, 2.5) == "Embedded line"
    args, kwargs = calls[0]
    assert args[args.index("-map") + 1] == "0:s:3"
    assert args[args.index("-fs") + 1] == str(enc.MAX_SUBTITLE_BYTES)
    assert kwargs["timeout"] == 15
    assert kwargs["stdin"] is enc.subprocess.DEVNULL


def test_embedded_extraction_rejects_bad_indices_failures_and_output_limit(tmp_path, monkeypatch):
    source = tmp_path / "film.mkv"
    source.write_bytes(b"media")
    for index in (-1, True, "0"):
        with pytest.raises(enc.SubtitleEncodingError, match="index"):
            enc.load_embedded_timed_cues(source, index)
    monkeypatch.setattr(enc.subprocess, "run", lambda *_a, **_k: mock.Mock(returncode=1, stdout=b""))
    with pytest.raises(enc.SubtitleEncodingError, match="could not be extracted"):
        enc.load_embedded_timed_cues(source, 0)
    monkeypatch.setattr(enc.subprocess, "run", lambda *_a, **_k: mock.Mock(
        returncode=0, stdout=b"x" * enc.MAX_SUBTITLE_BYTES))
    with pytest.raises(enc.SubtitleEncodingError, match="exceeds 16 MiB"):
        enc.load_embedded_timed_cues(source, 0)


def preview_window_type(monkeypatch, jobs, **module_overrides):
    """A host that is its own window, with the module's collaborators faked."""
    import cast_subtitle_files as module
    monkeypatch.setattr(module, "Async", SimpleNamespace(
        run=lambda work, done=None, failed=None, **opts: jobs.append((work, done, failed, opts))))
    for name, value in module_overrides.items():
        monkeypatch.setattr(module, name, value)

    class W(module.SubtitleFileController):
        def __init__(self):
            super().__init__(self)

    return W


def test_hover_wiring_is_opt_in_and_preserves_existing_scrub_preview():
    lifecycle = main_window_methods()["_on_hover"]
    assert "w._queue_preview(value, sparse=True)" in lifecycle
    assert "w._timed_subtitle_preview(value)" in lifecycle
    assert "w._timed_subtitle_preview(None)" in lifecycle


def test_rapid_hover_reuses_worker_and_ignores_old_film(tmp_path, monkeypatch):
    jobs = []
    cls = preview_window_type(monkeypatch, jobs, fmt_time=lambda value: str(value))
    subtitle = tmp_path / "film.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nSubtitle\n")
    window = cls()
    window.cfg = {"subs": "pick"}
    window._preview_path = str(tmp_path / "film.mkv")
    window._preview_generation = 1
    window.session = None
    window.external = False
    window._closing = False
    window.media = None
    window.subs_detail = mock.Mock()
    window._subs_status_text = lambda: "Using film.srt"
    window._resolve_subs = lambda _: subtitle
    window._console = mock.Mock()
    window._timed_subtitle_preview(1.0)
    window._timed_subtitle_preview(2.0)
    assert len(jobs) == 1
    work, done, _failed, options = jobs.pop()
    assert options["domain"] == "media" and options["valid"]()
    done(work())
    window.subs_detail.set_text.assert_called_with("Using film.srt\nAt 2.0: Subtitle")
    window._timed_subtitle_preview(None)
    window.subs_detail.set_text.assert_called_with("Using film.srt")
    window._preview_generation += 1
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nIntermediate cue\n")
    window._timed_subtitle_preview(1.0)
    # Source change while worker is outstanding must not replace the new cue cache.
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nNew cue\n")
    work, done, _failed, _ = jobs.pop()
    done(work())
    assert window._caption_cue_cache[1].cues[0][2] == "Subtitle"


def test_embedded_track_preview_extracts_off_thread_and_restores_detail(tmp_path, monkeypatch):
    jobs = []
    source = tmp_path / "film.mkv"
    source.write_bytes(b"film")
    track = SimpleNamespace(index=2, codec="subrip", is_text=True)
    media = SimpleNamespace(path=source, subtitle_tracks=[track])
    extracted = []

    def extract(path, index):
        extracted.append((path, index))
        return enc.TimedCues(((1.0, 3.0, "Embedded cue"),), (1.0,), (3.0,))

    def choose_track(_media, requested):
        return track if requested in (-1, track.index) else None

    cls = preview_window_type(
        monkeypatch, jobs, fmt_time=lambda value: str(value),
        subtitle_encoding=SimpleNamespace(
            load_timed_cues=enc.load_timed_cues, load_embedded_timed_cues=extract,
            cue_at=enc.cue_at),
        streamer=SimpleNamespace(preferred_embedded_subtitle=choose_track))
    window = cls()
    window.cfg = {"subs": "embedded", "subtitle_track_by_file": {str(source): 2}}
    window._preview_path = str(source)
    window._preview_generation = 4
    window.session = None
    window.external = False
    window._closing = False
    window.media = media
    window.subs_detail = mock.Mock()
    window._subs_status_text = lambda: "Embedded: English"
    window._resolve_subs = lambda _path: None
    window._console = mock.Mock()
    window._timed_subtitle_preview(2.0)
    assert len(jobs) == 1
    work, done, _failed, options = jobs.pop()
    assert options["domain"] == "media" and options["valid"]()
    window.cfg["subtitle_track_by_file"][str(source)] = 1
    assert not options["valid"]()
    window.cfg["subtitle_track_by_file"][str(source)] = 2
    done(work())
    assert extracted == [(source, 2)]
    window.subs_detail.set_text.assert_called_with("Embedded: English\nAt 2.0: Embedded cue")
    window._timed_subtitle_preview(None)
    window.subs_detail.set_text.assert_called_with("Embedded: English")
