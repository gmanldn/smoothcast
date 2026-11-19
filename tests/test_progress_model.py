"""Typed FFmpeg progress and receiver-status models (issue #249). No GTK, no ffmpeg."""
from __future__ import annotations

import dataclasses
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import castctl
import progress_model as pm
import streamer

SAMPLE = """frame=120
fps=29.97
bitrate=1500.2kbits/s
total_size=1048576
out_time_us=4000000
out_time_ms=4000000
dup_frames=0
drop_frames=2
speed=1.52x
progress=continue
"""


def test_parses_a_full_progress_block():
    p = pm.parse_progress(SAMPLE)
    assert p == pm.Progress(
        out_time=4.0, progress="continue", speed=1.52, fps=29.97, frame=120,
        total_size=1048576, bitrate="1500.2kbits/s", dup_frames=0, drop_frames=2)
    assert not p.done and p.speed_text == "1.52x" and p.fps_text == "29.97"


def test_end_marker_means_done():
    assert pm.parse_progress("progress=end\n").done
    assert not pm.parse_progress("progress=continue\n").done
    assert not pm.EMPTY.done


def test_later_values_win_and_truncated_lines_are_tolerated():
    p = pm.parse_progress("speed=1x\nspeed=2x\nout_time_us=\nfra")
    assert p.speed == 2.0 and p.out_time == 0.0 and p.frame is None


@pytest.mark.parametrize("junk", ["N/A", "", "abc", "nan", "inf", "-5"])
def test_untrusted_numbers_never_raise_or_go_negative(junk):
    p = pm.parse_progress(f"speed={junk}\nfps={junk}\nframe={junk}\nout_time_us={junk}\nout_time_ms={junk}\n")
    assert p.speed is None and p.fps is None and p.frame is None
    assert p.out_time == 0.0
    assert p.speed_text == "—" and p.fps_text == "—"


def test_out_time_falls_back_to_the_milli_labelled_field():
    assert pm.parse_progress("out_time_ms=2500000\n").out_time == 2.5
    assert pm.parse_progress("out_time_us=0\nout_time_ms=1000000\n").out_time == 1.0
    assert pm.parse_progress("out_time_us=-8000000\n").out_time == 0.0


def test_progress_is_immutable_and_empty_is_shared_safe():
    with pytest.raises(dataclasses.FrozenInstanceError):
        pm.EMPTY.out_time = 3.0  # type: ignore[misc]
    assert pm.parse_progress("") == pm.EMPTY


def test_session_reads_the_progress_file_into_the_model(tmp_path):
    path = tmp_path / "progress.log"
    path.write_text(SAMPLE)
    assert streamer.Session()._read_progress(path).out_time == 4.0
    assert streamer.Session()._read_progress(tmp_path / "missing") == pm.EMPTY
    path.write_bytes(b"\xff\xfe" + SAMPLE.encode())
    assert streamer.Session()._read_progress(path).speed == 1.52


def test_fresh_session_has_an_empty_typed_snapshot():
    session = streamer.Session()
    assert session.progress() == pm.EMPTY and not session.progress().done


def test_receiver_info_is_typed_for_the_helpers_castctl_exposes():
    info: pm.ReceiverInfo = {"player_state": "playing", "volume_level": 0.5,
                             "volume_muted": True, "duration": 90.0, "current_time": 3.0}
    assert castctl.player_state(info) == "PLAYING"
    assert castctl.volume_percent(info) == 50 and castctl.volume_muted(info)
    assert castctl.is_seekable(info)
    assert set(pm.ReceiverInfo.__optional_keys__) == set(pm.ReceiverInfo.__annotations__)


def test_module_is_installed_and_in_the_mypy_gate():
    text = (ROOT / "pyproject.toml").read_text()
    assert '"progress_model"' in text and "src/progress_model.py" in text
