"""Property/fuzz tests for parsers of untrusted files and network replies (#260).

Contract for every parser: hostile input may only produce the module's
documented error type (or a valid result) - never another exception, a hang
or unbounded work. Examples are seeded (derandomize) so CI is reproducible and
bounded (max_examples, no deadline flakiness on slow runners).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import dlna  # noqa: E402
import playlist_control  # noqa: E402
import streamer  # noqa: E402
import subtitle_encoding  # noqa: E402

FUZZ = settings(
    max_examples=150, deadline=None, derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# Arbitrary JSON values, as ffprobe/network replies can contain any shape.
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=40),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=12), children, max_size=5),
    max_leaves=25,
)
STREAM_KEYS = ("index", "codec_type", "codec_name", "width", "height", "avg_frame_rate",
               "duration", "duration_ts", "time_base", "tags", "disposition", "channels",
               "profile", "pix_fmt", "bit_rate", "nb_frames")
STREAM = st.dictionaries(st.sampled_from(STREAM_KEYS), JSON_VALUES, max_size=10)


class SubtitleFuzz(unittest.TestCase):
    @FUZZ
    @given(st.binary(max_size=2048))
    def test_decode_srt_returns_utf8_or_the_documented_error(self, data):
        try:
            result, codec = subtitle_encoding.decode_srt(data)
        except subtitle_encoding.SubtitleEncodingError:
            return
        result.decode("utf-8")  # Always valid UTF-8 when accepted.
        self.assertIn("-->", result.decode("utf-8"))
        self.assertIsInstance(codec, str)

    @FUZZ
    @given(st.text(max_size=300), st.sampled_from(["utf-8", "utf-16", "utf-8-sig"]))
    def test_valid_cues_in_any_bom_encoding_round_trip(self, filler, codec):
        text = "1\n00:00:01,000 --> 00:00:02,000\n" + "".join(
            ch for ch in filler if ch >= " " or ch in "\t\r\n") + "\n"
        try:
            data = text.encode(codec)
        except UnicodeEncodeError:
            return  # Lone surrogates cannot be encoded; not a parser input.
        try:
            result, _ = subtitle_encoding.decode_srt(data)
        except subtitle_encoding.SubtitleEncodingError:
            return
        self.assertIn(b"-->", result)


class PlaylistFuzz(unittest.TestCase):
    @FUZZ
    @given(st.binary(max_size=2048))
    def test_load_playlist_never_raises_anything_but_playlist_error(self, data):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "list.m3u"
            path.write_bytes(data)
            try:
                items, skipped = playlist_control.load_playlist(path)
            except playlist_control.PlaylistError:
                return
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(skipped, 0)
        self.assertEqual(len(items), len(set(items)))  # Documented: unique entries.


class DlnaFuzz(unittest.TestCase):
    LOCATION = "http://192.168.1.20:8080/desc.xml"

    @FUZZ
    @given(st.binary(max_size=4096))
    def test_parse_renderer_only_raises_dlna_error_for_arbitrary_bytes(self, data):
        try:
            dlna.parse_renderer(data, self.LOCATION, "192.168.1.20")
        except dlna.DlnaError:
            pass

    @FUZZ
    @given(st.text(max_size=60), st.text(max_size=60), st.text(max_size=80))
    def test_parse_renderer_with_hostile_fields_cannot_leave_the_lan(self, name, control, base):
        xml = (
            '<root xmlns="urn:schemas-upnp-org:device-1-0">'
            f"<URLBase>{_esc(base)}</URLBase><device>"
            "<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>"
            f"<friendlyName>{_esc(name)}</friendlyName><serviceList><service>"
            "<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>"
            f"<controlURL>{_esc(control)}</controlURL></service></serviceList>"
            "</device></root>").encode("utf-8", "replace")
        try:
            renderer = dlna.parse_renderer(xml, self.LOCATION, "192.168.1.20")
        except dlna.DlnaError:
            return
        self.assertTrue(renderer.transport_url.startswith("http://192.168.1.20"))
        self.assertLessEqual(len(renderer.name), 120)

    @FUZZ
    @given(st.binary(max_size=2048))
    def test_upnp_fault_text_is_bounded_and_free_of_control_characters(self, data):
        text = dlna._upnp_fault(data)
        self.assertLessEqual(len(text), 140)
        self.assertFalse(any(ord(ch) < 32 or ord(ch) == 127 for ch in text))

    def test_entity_expansion_bombs_do_not_hang_or_crash(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
                '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><r>&c;&c;&c;&c;</r>').encode()
        try:
            dlna.parse_renderer(bomb, self.LOCATION, "192.168.1.20")
        except dlna.DlnaError:
            pass
        self.assertEqual(dlna._upnp_fault(bomb), "")

    def test_deeply_nested_xml_is_rejected_cleanly(self):
        deep = b"<a>" * 20000 + b"</a>" * 20000
        try:
            dlna.parse_renderer(deep, self.LOCATION, "192.168.1.20")
        except dlna.DlnaError:
            pass
        self.assertEqual(dlna._upnp_fault(deep), "")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\x00", ""))


class FfprobeRegressions(unittest.TestCase):
    """Concrete shapes found by the fuzzers: each is one clear StreamError."""

    def test_known_malformed_outputs_raise_stream_error(self):
        for text in ("null", "true", "[]", "7", '"x"', "{", "[" * 100000,
                     '{"format": true}', '{"streams": "abc"}', '{"streams": [1, null]}',
                     '{"streams": [{"codec_type": "video", "width": "wide"}]}',
                     '{"streams": [{"codec_type": "video", "index": {}}]}'):
            with self.subTest(text=text[:40]), self.assertRaises(streamer.StreamError):
                FfprobeFuzz.probe(self, text)

    def test_good_output_is_unchanged(self):
        media = FfprobeFuzz.probe(self, {
            "format": {"duration": "12.5", "bit_rate": "1000"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                         "width": 1280, "height": 720, "avg_frame_rate": "25/1"},
                        {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2}],
        })
        self.assertEqual((media.vcodec, media.width, media.acodec, media.duration),
                         ("h264", 1280, "aac", 12.5))


class FfprobeFuzz(unittest.TestCase):
    def probe(self, payload) -> streamer.MediaInfo:
        completed = subprocess.CompletedProcess(
            ["ffprobe"], 0, stdout=payload if isinstance(payload, str) else json.dumps(payload),
            stderr="")
        with mock.patch.object(streamer.subprocess, "run", return_value=completed):
            return streamer.ffprobe(Path("/nonexistent/film.mkv"))

    @FUZZ
    @given(st.text(max_size=300))
    def test_non_json_output_is_a_stream_error_or_media(self, text):
        try:
            self.probe(text)
        except streamer.StreamError:
            pass

    @FUZZ
    @given(JSON_VALUES)
    def test_arbitrary_json_is_a_stream_error_or_media(self, value):
        try:
            self.probe(value)
        except streamer.StreamError:
            pass

    @FUZZ
    @given(st.lists(STREAM, max_size=5), JSON_VALUES)
    def test_malformed_streams_and_format_never_crash(self, streams, fmt):
        try:
            media = self.probe({"streams": streams, "format": fmt})
        except streamer.StreamError:
            return
        self.assertGreaterEqual(media.duration, 0)
        self.assertGreaterEqual(media.width, 0)


if __name__ == "__main__":
    unittest.main()
