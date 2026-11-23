"""Phone playhead projection (#336): advance only while playing, clamp, never lie."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal

FUNCTION = next(line for line in portal._HTML.splitlines() if line.startswith("function projectPosition("))

CASES = [
    # (snapshot, ageMs, sinceMs, expected)
    ({"state": "PLAYING", "position": 10, "duration": 100}, 0, 0, 10),
    ({"state": "PLAYING", "position": 10, "duration": 100}, 500, 1500, 12),
    ({"state": "PAUSED", "position": 10, "duration": 100}, 500, 5000, 10),
    ({"state": "BUFFERING", "position": 10, "duration": 100}, 0, 5000, 10),
    ({"state": "IDLE", "position": 10, "duration": 100}, 0, 5000, 10),
    ({"state": "PLAYING", "position": 98, "duration": 100}, 0, 9000, 100),
    ({"state": "PLAYING", "position": 5, "duration": 0}, 0, 3000, 8),
    ({"state": "PLAYING", "position": "x", "duration": 100}, 0, 3000, 0),
    ({"state": "PLAYING", "position": -4, "duration": 100}, 0, 3000, 0),
    ({"state": "PLAYING", "position": 10, "duration": 100}, "bad", -50, 10),
    ({"state": "PLAYING", "position": 10, "duration": 1e9}, 9e12, 0, 10 + 21600),
]


def test_page_wires_projection_to_animation_frames_without_overwriting_scrubs():
    html = portal._HTML
    assert "function trackPlayhead(" in html and "function paintPlayhead(" in html
    assert "requestAnimationFrame(playheadFrame)" in html and "typeof requestAnimationFrame" in html
    assert "if(!document.hidden)paintPlayhead()" in html  # hidden tabs do not paint
    paint = next(line for line in html.splitlines() if line.startswith("function paintPlayhead("))
    assert 'if(!editingControls.has("seek"))$("seek").value' in paint
    assert "trackPlayhead(s)" in html


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_projection_function_in_node():
    script = FUNCTION + "\nconst cases=" + json.dumps([[c[0], c[1], c[2]] for c in CASES]) + \
        ";console.log(JSON.stringify(cases.map(c=>projectPosition(c[0],c[1],c[2]))));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=8)
    got = json.loads(result.stdout)
    for (snap, _a, _s, expected), value in zip(CASES, got):
        assert value == pytest.approx(expected), snap


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_projection_handles_non_finite_without_throwing():
    script = FUNCTION + "\nconsole.log(JSON.stringify([projectPosition({state:'PLAYING',position:NaN,duration:5},0,0),"\
        "projectPosition({state:'PLAYING',position:Infinity,duration:5},0,0),"\
        "projectPosition({},0,0),projectPosition({state:'PLAYING',position:3},NaN,NaN)]));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=8)
    assert json.loads(result.stdout) == [0, 0, 0, 3]
