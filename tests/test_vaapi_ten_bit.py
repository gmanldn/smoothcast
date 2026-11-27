"""10-bit 4:2:0 sources use the GPU path with an explicit p010 -> nv12 conversion."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


def _vf(**kw):
    args = streamer.Session()._filter_args(False, None, False, 1.0, **kw)
    return args[args.index("-vf") + 1] if args else ""


def test_ten_bit_is_converted_before_the_vaapi_encoder():
    vf = _vf(ten_bit=True)
    assert vf.startswith("hwdownload,format=p010le,format=nv12")
    assert vf.endswith("hwupload")


def test_eight_bit_stays_on_the_gpu_with_no_round_trip():
    assert _vf(ten_bit=False) == ""


def test_ten_bit_formats_are_accepted_for_vaapi():
    assert "yuv420p10le" in streamer.VAAPI_PIX_FMTS
    assert "yuv444p" not in streamer.VAAPI_PIX_FMTS
