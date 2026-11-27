"""#11: the capability plan may only veto direct play, and only with certainty."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import capability_gate as gate
from gui_source import main_window_methods


def media(**kw):
    base = dict(vcodec="h264", acodec="aac", height=1080, color_transfer="bt709", audio_only=False)
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize("model", [None, "", "Chromecast", "BRAVIA 4K", "Vizio SmartCast", "x" * 9000])
def test_unknown_or_ambiguous_models_are_never_vetoed_even_for_4k_hevc(model):
    assert gate.direct_allowed(media(vcodec="hevc", height=2160), "mkv", model) == (True, "")


def test_speakers_cannot_play_video_directly_but_can_play_music():
    allowed, note = gate.direct_allowed(media(), "mp4", "Nest Mini")
    assert allowed is False and note.startswith("Nest Mini:")
    assert gate.direct_allowed(media(vcodec="", audio_only=True, acodec="mp3"), "mp3", "Nest Mini")[0] is True


def test_capable_streamers_keep_direct_play_for_modern_media():
    assert gate.direct_allowed(media(vcodec="hevc", height=2160), "mp4", "Chromecast Ultra")[0] is True
    hdr = media(vcodec="hevc", height=2160, color_transfer="smpte2084")
    assert gate.direct_allowed(hdr, "mp4", "Google TV Streamer")[0] is True


def test_ambiguous_google_tv_model_stays_conservative_for_hdr_hevc():
    # #11/#207: the bare "Chromecast with Google TV" is the HD/4K ambiguity, so
    # its profile keeps the baseline class and vetoes direct HDR HEVC playback.
    hdr = media(vcodec="hevc", height=2160, color_transfer="smpte2084")
    allowed, note = gate.direct_allowed(hdr, "mp4", "Chromecast with Google TV")
    assert allowed is False and note.startswith("Chromecast with Google TV:")


def test_recognised_streamer_still_vetoes_what_it_documents_it_cannot_play():
    assert gate.direct_allowed(media(vcodec="mpeg2video"), "mp4", "Chromecast Ultra")[0] is False
    assert gate.direct_allowed(media(acodec="dts"), "mp4", "Chromecast Ultra")[0] is False


def test_container_only_mismatch_is_a_remux_not_a_veto():
    assert gate.direct_allowed(media(), "avi", "Chromecast Ultra")[0] is True


@pytest.mark.parametrize("bad", [None, object(), SimpleNamespace(vcodec=None, height="tall")])
def test_a_broken_probe_never_blocks_casting(bad):
    assert gate.direct_allowed(bad, None, "Nest Mini")[0] in (True, False)  # no exception
    assert gate.direct_allowed(bad, None, object()) == (True, "")


def test_cast_path_only_adds_the_gate_as_an_extra_and_term():
    body = main_window_methods()["_cast_path"]
    assert "capability_gate.direct_allowed(" in body
    start = body.index("direct_eligible = (")
    block = body[start:body.index("if receiver_memory.should_try_direct(", start)]
    assert "use_direct and media.direct_ok and not burn and gate_ok" in block
    assert block.count("gate_ok") == 1  # it can only remove direct play, never add it
