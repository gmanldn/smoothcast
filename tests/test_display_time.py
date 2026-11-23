"""Cross-surface clock contract: one golden vector suite for Python and web JS."""
import json
import math
import shutil
import subprocess

import castctl
import portal


VECTORS = [
    (0, "0:00"),
    (59, "0:59"),
    (60, "1:00"),
    (3599, "59:59"),
    (3600, "1:00:00"),
    (7500, "2:05:00"),
    (86399, "23:59:59"),
    (None, "--:--"),
    (math.nan, "--:--"),
    (-7, "0:00"),
]


def test_python_display_clock_golden_vectors():
    for seconds, expected in VECTORS:
        assert castctl.fmt_time(seconds) == expected
        if expected != "--:--":
            assert castctl.fmt_remaining(seconds) == "-" + expected
    assert castctl.fmt_time(math.inf) == "--:--"
    assert castctl.fmt_time(-math.inf) == "--:--"
    assert castctl.fmt_remaining(None) == "--:--"


def test_web_display_clock_matches_python_and_deduplicates_activity_clock():
    # The single-line function is evaluated in Node if available. Without Node,
    # structural guards still protect against the old >60 minute regression.
    line = next(line for line in portal._HTML.splitlines() if line.startswith("function clock(s){"))
    assert "s%3600" in line
    assert "Math.floor(s/3600)" in line
    assert "String(sec).padStart(2" in line
    assert portal._HTML.count("function clock(s){") == 1
    assert "const time=n=>" not in portal._HTML
    assert "${clock(item.position)}" in portal._HTML
    assert "${clock(item.duration)}" in portal._HTML
    if shutil.which("node"):
        source = (line + "\n" +
                  "const inputs=[0,59,60,3599,3600,7500,86399,null,NaN,-7];" +
                  "console.log(JSON.stringify(inputs.map(clock)));")
        result = subprocess.run(
            ["node", "-e", source], check=True, capture_output=True,
            text=True, timeout=8,
        )
        assert json.loads(result.stdout) == [label for _, label in VECTORS]


def test_dlna_wire_clock_is_not_display_clock():
    # DLNA AVTransport uses HH:MM:SS on the wire: this is intentionally not
    # replaced with the human-facing m:ss convention.
    assert castctl.fmt_time(7500) == "2:05:00"
