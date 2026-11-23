"""P1 #26: no unproven HDR detection or unprepared receiver handoff."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import hdr_tonemap
import streamer


def media(transfer="smpte2084", primaries="bt2020", matrix="bt2020nc"):
    return SimpleNamespace(color_transfer=transfer, color_primaries=primaries, color_space=matrix)


def test_hdr10_requires_all_three_colour_metadata_fields():
    assert hdr_tonemap.filter_for(media()) == hdr_tonemap.SDR_FILTER
    assert hdr_tonemap.filter_for(media(matrix="bt2020c")) == hdr_tonemap.SDR_FILTER
    for item in [media(transfer=""), media(primaries=""), media(matrix=""),
                 media(transfer="arib-std-b67"), media(primaries="bt709"),
                 media(matrix="bt709"), SimpleNamespace()]:
        assert hdr_tonemap.filter_for(item) is None


def test_missing_filters_fail_closed_without_probing_sdr():
    hdr_tonemap.filters_available.cache_clear()
    with patch.object(hdr_tonemap, "filters_available", return_value=False) as probe:
        hdr_tonemap.require_available(media("bt709", "bt709", "bt709"))
        probe.assert_not_called()
        with pytest.raises(hdr_tonemap.TonemapUnavailable, match="zscale and tonemap"):
            hdr_tonemap.require_available(media())
    hdr_tonemap.filters_available.cache_clear()


def test_ffmpeg_filter_detection_rejects_unrelated_filter_names():
    hdr_tonemap.filters_available.cache_clear()
    good = " .S. zscale V->V\n ... tonemap V->V\n"
    with patch.object(hdr_tonemap.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0, good, "")):
        assert hdr_tonemap.filters_available()
    hdr_tonemap.filters_available.cache_clear()
    with patch.object(hdr_tonemap.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0, " ... tonemap_opencl V->V\n", "")):
        assert not hdr_tonemap.filters_available()
    hdr_tonemap.filters_available.cache_clear()


def test_ffprobe_uses_only_selected_motion_video_colour_metadata():
    item = streamer.MediaInfo(Path("film.mkv"))
    streamer._read_probe(item, {"format": {}, "streams": [
        {"codec_type": "video", "index": 0, "codec_name": "mjpeg",
         "disposition": {"attached_pic": 1}, "color_transfer": "bt709"},
        {"codec_type": "video", "index": 1, "codec_name": "hevc",
         "width": 1920, "height": 1080, "pix_fmt": "yuv420p10le",
         "color_transfer": "smpte2084", "color_primaries": "bt2020",
         "color_space": "bt2020nc"},
    ]})
    assert item.video_stream_index == 1
    assert hdr_tonemap.filter_for(item) == hdr_tonemap.SDR_FILTER


def test_hdr_filter_precedes_caption_overlay():
    args = streamer.Session()._filter_args(
        True, Path("/tmp/subs.srt"), True, 1.0,
        video_size=(1920, 1080), hdr_filter=hdr_tonemap.SDR_FILTER,
    )
    assert args[:1] == ["-vf"]
    assert args[1].startswith(hdr_tonemap.SDR_FILTER + ",")
    assert args[1].index("tonemap=") < args[1].index("subtitles=")


@pytest.mark.skipif(
    os.environ.get("SMOOTHCAST_REAL_FFMPEG") != "1"
    or not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="run in the gated real-FFmpeg media integration job",
)
def test_real_ffmpeg_hdr10_to_sdr(tmp_path):
    if not hdr_tonemap.filters_available():
        pytest.skip("selected FFmpeg lacks zscale or tonemap; application reports this clearly")
    source, target = tmp_path / "pq.mkv", tmp_path / "sdr.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc2=size=160x90:rate=8:duration=1",
        "-vf", "format=yuv420p10le,setparams=color_primaries=bt2020:"
               "color_trc=smpte2084:colorspace=bt2020nc",
        "-c:v", "ffv1", "-y", str(source),
    ], check=True, timeout=45, capture_output=True)
    info = streamer.ffprobe(source)
    assert hdr_tonemap.filter_for(info)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", hdr_tonemap.filter_for(info), "-frames:v", "8",
        "-c:v", "libx264", "-y", str(target),
    ], check=True, timeout=45, capture_output=True)
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt,color_primaries,color_transfer,color_space",
        "-of", "default=noprint_wrappers=1", str(target),
    ], check=True, timeout=20, capture_output=True, text=True).stdout
    assert "pix_fmt=yuv420p" in probe
    assert "color_primaries=bt709" in probe
    assert "color_transfer=bt709" in probe
    assert "color_space=bt709" in probe
