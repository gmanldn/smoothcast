"""SC-028: bounded, source-owned, seek-time sidecar subtitle preview."""
from __future__ import annotations

from pathlib import Path
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


def test_hover_wiring_is_opt_in_and_preserves_existing_scrub_preview():
    lifecycle = main_window_methods()["_on_hover"]
    assert "self._queue_preview(value)" in lifecycle
    assert "self._timed_subtitle_preview(value)" in lifecycle
    assert "self._timed_subtitle_preview(None)" in lifecycle


def test_rapid_hover_reuses_worker_and_ignores_old_film(tmp_path):
    code = main_window_methods()["_timed_subtitle_preview"]
    import pathlib
    import textwrap
    jobs = []
    namespace = {
        "pathlib": pathlib, "subtitle_encoding": enc, "fmt_time": lambda value: str(value),
        "Async": SimpleNamespace(run=lambda work, done=None, failed=None, **opts:
                                  jobs.append((work, done, failed, opts))),
    }
    exec(compile("class W:\n" + textwrap.indent(textwrap.dedent(code), "    "),
                 "<timed-cue-ui>", "exec"), namespace)
    cls = namespace["W"]
    subtitle = tmp_path / "film.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nSubtitle\n")
    window = cls()
    window.cfg = {"subs": "pick"}
    window._preview_path = str(tmp_path / "film.mkv")
    window._preview_generation = 1
    window.session = None
    window.external = False
    window._closing = False
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
    window._timed_subtitle_preview(1.0)
    # Source change while worker is outstanding must not replace the new cue cache.
    subtitle.write_text("1\n00:00:01,000 --> 00:00:03,000\nNew cue\n")
    work, done, _failed, _ = jobs.pop()
    done(work())
    assert window._caption_cue_cache[1].cues[0][2] == "Subtitle"
