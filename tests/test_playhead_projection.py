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
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": 0.5}, 500, 1500, 11),
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": 2.0}, 500, 1500, 14),
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": 4.0}, 500, 1500, 18),
    ({"state": "PAUSED", "position": 10, "duration": 100, "rate": 2.0}, 500, 1500, 10),
    ({"state": "BUFFERING", "position": 10, "duration": 100, "rate": 2.0}, 500, 1500, 10),
    ({"state": "PLAYING", "position": 99, "duration": 100, "rate": 2.0}, 500, 1500, 100),
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": None}, 500, 1500, 12),
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": "2"}, 500, 1500, 12),
    ({"state": "PLAYING", "position": 10, "duration": 100, "rate": -5}, 500, 1500, 12),
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


def test_page_wires_projection_to_a_timer_without_overwriting_scrubs():
    html = portal._HTML
    assert "function trackPlayhead(" in html and "function paintPlayhead(" in html
    assert "function schedulePlayhead(" in html and "playheadTimer=setTimeout(" in html
    assert "if(document.hidden||!csrf||stalePage)return;" in html  # hidden tabs do not paint
    paint = next(line for line in html.splitlines() if line.startswith("function paintPlayhead("))
    # The seek control is painted only when the guest is not editing it.
    assert 'if(!editingControls.has("seek")){' in paint
    assert '$("seek").value' in paint
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


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_room_snapshot_version_fences_delayed_status_messages():
    # Only the pure browser helper: no GTK, network or real browser.
    source = portal._HTML
    initial = next(line for line in source.splitlines()
                   if line.startswith('let roomSnapshotEpoch='))
    function = next(line for line in source.splitlines()
                    if line.startswith('function acceptRoomSnapshot('))
    scenario = """
    const assert=require('node:assert/strict');
    const frame=(epoch,ver)=>({stream_epoch:epoch,state:{snapshot_version:ver}});
    assert.equal(acceptRoomSnapshot(frame('a',5)),true);
    assert.equal(acceptRoomSnapshot(frame('a',5)),true);  // age refresh
    assert.equal(acceptRoomSnapshot(frame('a',4)),false); // stale poll
    assert.equal(acceptRoomSnapshot(frame('a',6)),true);
    assert.equal(acceptRoomSnapshot(frame('a',3)),false);
    assert.equal(acceptRoomSnapshot(frame('b',1)),true); // portal restart
    assert.equal(acceptRoomSnapshot(frame('b',0)),false);
    assert.equal(acceptRoomSnapshot(frame('b',2)),true);
    assert.equal(acceptRoomSnapshot({state:{snapshot_version:3}}),true); // legacy
    assert.equal(acceptRoomSnapshot(frame('b',1)),false); // missing metadata cannot reset fence
    assert.equal(acceptRoomSnapshot(frame('c',NaN)),true);
    assert.equal(acceptRoomSnapshot(frame('b',1)),false);
    """
    result = subprocess.run(["node", "-"], input=initial+"\n"+function+"\n"+scenario,
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr

 

def test_server_snapshot_uses_tracked_source_playback_rate():
    # Extract the GTK method as source, never import gi, start a window or touch a receiver.
    from types import SimpleNamespace
    import textwrap

    from gui_source import main_window_methods

    methods = main_window_methods()
    method = methods["_portal_handle"] + "\n" + methods["_portal_timing"]
    state_label = SimpleNamespace(label="Playing", short="Playing",
                                  accessible="Playing", icon="play")
    namespace = {
        "portal": SimpleNamespace(PortalRequestError=RuntimeError),
        "castctl": SimpleNamespace(volume_percent=lambda _: 50),
        "state_labels": SimpleNamespace(present=lambda _: state_label),
        "network_activity": SimpleNamespace(portal_entries=lambda *_: []),
        "action_state": __import__("action_state"),
        "accent": __import__("accent"),
    }
    exec(compile("class Window:\n" + textwrap.indent(method, "    "),
                 "<isolated-room-status>", "exec"), namespace)
    window = namespace["Window"]()
    window._closing = False
    window._portal = None
    window.tracker = SimpleNamespace(value=lambda: 18.0, duration=120.0,
                                     rate=2.0, known=True)
    window.media = None
    window.queue = []
    window._external_runtime = (7.0, 300.0)
    window.np_title = SimpleNamespace(get_text=lambda: "Film")
    window.now_playing = None
    window._portal_queue_status = lambda: []
    window._portal_copy_status = lambda: []
    window.device_info = None
    window.session = object()
    window.external = False
    window.busy = False
    window._device = lambda: "Receiver"
    window.device_state = "PLAYING"
    window._portal_observe_queue = lambda: 1
    window.cfg = {"music_autogain": False, "accent": "default"}
    window._network_activity_entries = []
    window._device_host = lambda _device: "192.168.1.10"
    window._portal_fence = None

    assert window._portal_handle("status", {})["rate"] == 2.0
    window.tracker.rate = 0.5
    assert window._portal_handle("status", {})["rate"] == 0.5
    window.tracker.rate = float("inf")
    assert window._portal_handle("status", {})["rate"] == 1.0
    window.tracker.rate = float("nan")
    assert window._portal_handle("status", {})["rate"] == 1.0

    # An external stream (not ours) reports the receiver's own runtime and position.
    window.tracker = SimpleNamespace(value=lambda: None, duration=0.0, rate=1.0, known=False)
    window.session, window.external = None, True
    snapshot = window._portal_handle("status", {})
    assert (snapshot["position"], snapshot["duration"]) == (7.0, 300.0)
    window.external = False  # once the receiver is idle again the runtime must not linger
    assert window._portal_handle("status", {})["duration"] == 0.0




def test_scrub_change_is_single_commit_cancel_is_noop_zero_valid():
    """Extract browser scrub helpers and run them with fake DOM and fake clock."""
    html = portal._HTML
    cancel = html.split("function cancelSeekPreview(){", 1)[1].split("\n}", 1)[0]
    commit = html.split("function commitSeekPreview(){", 1)[1].split("\n}", 1)[0]
    script = FUNCTION + "\n" + """
const assert=require("node:assert/strict");
let seekCanceled=false,playhead=null,at=0,editingControls=new Set(["seek"]);
const values={seek:{value:"45"},progress:{value:12},elapsed:{textContent:""}};
const $=name=>values[name];
const performance={now:()=>1000};
const clock=x=>String(x);
const commands=[];
const act=(name,value)=>commands.push([name,value]);
""" + "\nfunction cancelSeekPreview(){" + cancel + "\n}" + \
        "\nfunction commitSeekPreview(){" + commit + "\n}" + """
$("seek").value="38";
cancelSeekPreview();
$("seek").value="63";
commitSeekPreview();
assert.deepEqual(commands,[]);
assert.equal($("seek").value,12);
assert.equal($("elapsed").textContent,"12");
editingControls.add("seek");
$("seek").value="0";
commitSeekPreview();
assert.deepEqual(commands,[["seek",0]]);
assert.equal($("elapsed").textContent,"0");
$("seek").value="72.5";
commitSeekPreview();
assert.deepEqual(commands,[["seek",0],["seek",72.5]]);
$("seek").value="-4";
commitSeekPreview();
$("seek").value="Infinity";
commitSeekPreview();
assert.equal(commands.length,2);
playhead={s:{state:"PLAYING",position:10,duration:100,rate:2},age:500,at:0};
cancelSeekPreview();
assert.equal($("seek").value,13);
assert.equal($("elapsed").textContent,"13");
"""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    result = subprocess.run(["node", "-e", script], check=False,
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr


def test_scrub_wiring_previews_without_network_and_cancels_escape():
    html = portal._HTML
    assert 'function commitSeekPreview(){' in html
    assert 'function cancelSeekPreview(){' in html
    assert '"seek").addEventListener("input",()=>{' in html
    assert 'if(!seekCanceled)$("elapsed").textContent=clock(' in html
    assert '"seek").addEventListener("pointercancel",cancelSeekPreview)' in html
    assert 'event.key==="Escape"' in html
    assert '"seek").addEventListener("change",commitSeekPreview)' in html
    assert 'void act("seek",value)' in html


# Documented tolerance (#336): a phone's one-way network delay is the only
# unknown, so its displayed source second may lag the authoritative clock by at
# most ``delay * rate`` and must never run ahead of it.
DELAYS_MS = [200, 400, 700, 1000]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("rate", [0.5, 1.0, 2.0])
def test_two_delayed_clients_stay_within_documented_tolerance_of_authority(rate):
    """Two phones with 200-1000 ms delay track one fake authoritative clock."""
    script = FUNCTION + """
const rate=%s, delays=%s, sendAgeMs=120;
const authority=t=>100+(t/1000)*rate;              // source second at fake time t (ms)
const rows=[];
for(const d of delays){
  const sentAt=5000, snap={state:"PLAYING",position:authority(sentAt-sendAgeMs),duration:7200,rate};
  for(const display of [sentAt+d, sentAt+d+1000, sentAt+d+30000, sentAt+d+600000]){
    const shown=projectPosition(snap,sendAgeMs,display-(sentAt+d));
    rows.push([d,display,authority(display)-shown]);
  }
}
console.log(JSON.stringify(rows));
""" % (rate, DELAYS_MS, )
    rows = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True,
                                     text=True, timeout=8).stdout)
    lag_by_delay = {}
    for delay, _display, lag in rows:
        assert -1e-6 <= lag <= delay / 1000 * rate + 1e-6, (delay, lag)  # never ahead
        lag_by_delay.setdefault(delay, set()).add(round(lag, 6))
    # The lag is a constant offset: it does not drift as the clients keep running.
    assert all(len(values) == 1 for values in lag_by_delay.values())
    # Two clients 200 ms and 1000 ms away differ by exactly the delay gap.
    spread = abs(next(iter(lag_by_delay[1000])) - next(iter(lag_by_delay[200])))
    assert spread == pytest.approx(0.8 * rate)


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
@pytest.mark.parametrize("state", ["PAUSED", "BUFFERING", "IDLE", "UNKNOWN", ""])
def test_delayed_non_playing_snapshots_never_interpolate(state):
    script = FUNCTION + """
const out=[];for(const d of %s){for(const since of [0,d,60000,3600000])
  out.push(projectPosition({state:%s,position:42,duration:7200,rate:2},d,since));}
console.log(JSON.stringify(out));""" % (DELAYS_MS, json.dumps(state))
    out = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True,
                                    text=True, timeout=8).stdout)
    assert set(out) == {42}


def _js_function(name: str) -> str:
    html = portal._HTML
    start = html.index(f"function {name}(")
    depth, i = 0, html.index("{", start)
    while True:
        depth += html[i] == "{"
        depth -= html[i] == "}"
        i += 1
        if depth == 0:
            return html[start:i]


@pytest.mark.parametrize("name", ["schedulePlayhead", "paintPlayhead", "trackPlayhead"])
def test_animation_path_creates_no_network_or_command_traffic(name):
    """#336: painting the playhead each frame is pure DOM arithmetic."""
    body = _js_function(name)
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "post(", "EventSource", "command(", "WebSocket"):
        assert forbidden not in body, f"{name} must not call {forbidden}"


def test_playhead_sources_never_probe_media():
    """The host derives source position from its tracker: no ffprobe on the status/playhead path."""
    root = Path(__file__).resolve().parents[1] / "src"
    for name in ("portal.py", "position_tracker.py", "playback_state.py", "progress_model.py"):
        assert "ffprobe" not in (root / name).read_text("utf-8"), name


def test_unknown_length_external_stream_shows_a_moving_marker_not_a_made_up_length():
    import portal
    text = portal._HTML
    assert 'pr.removeAttribute("value")' in text and "length not reported" in text
    assert 'typeof s.length_label==="string"&&s.length_label?s.length_label' in text
    widgets = open("src/cast_widgets.py").read()
    assert "unknown_length" in widgets and "self.position % 60.0" in widgets
    assert "unknown_length=" in open("src/cast_session.py").read()
