"""#430: lock-screen controls via the Media Session API on the web remote."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
from test_room_conformance import RoomHarness

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def media_code() -> str:
    html = portal._page().decode("utf-8")
    start = html.index("const MEDIA=")
    end = html.index('(()=>{\n  const box=$("lockControls")')
    # Media Session reuses the already-tested source-second projection helper.
    projection = next(line for line in html.splitlines()
                      if line.startswith("function projectPosition("))
    return projection + "\n" + html[start:end]


HARNESS = """
const calls=[],handlers={},store={};
let shortcutState={state:"PAUSED",position:50};
const act=(a,v)=>calls.push([a,v]);
global.localStorage={getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=v}};
global.MediaMetadata=function(o){Object.assign(this,o)};
const played=[];
global.Audio=function(src){this.src=src;this.paused=true;this.setAttribute=()=>{};
  this.play=()=>{this.paused=false;played.push(src);return Promise.resolve()};this.pause=()=>{this.paused=true}};
// Node 22+ has a read-only built-in global.navigator accessor; replace it
// explicitly rather than relying on an ignored assignment.
Object.defineProperty(global,"navigator",{configurable:true,value:{mediaSession:{
  playbackState:"none",metadata:null,position:null,
  setActionHandler:(n,f)=>{handlers[n]=f},setPositionState:p=>{navigator.mediaSession.position=p}
}}});
%s
%s
"""


def run(body: str) -> dict:
    script = HARNESS % (media_code(), body + "\nconsole.log(JSON.stringify(out));")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_playing_sets_metadata_position_state_and_silent_audio():
    out = run("""
syncMediaSession({state:"PLAYING",title:"Paddington 2",receiver:"Lounge TV",duration:5400,position:120,rate:1.5});
const ms=navigator.mediaSession;
const out={title:ms.metadata.title,album:ms.metadata.album,state:ms.playbackState,pos:ms.position,
 played, vol:MEDIA.audio.volume, loop:MEDIA.audio.loop, names:Object.keys(handlers).sort()};
""")
    assert out["title"] == "Paddington 2" and out["album"] == "SmoothCast - Lounge TV"
    assert out["state"] == "playing"
    assert out["pos"] == {"duration": 5400, "position": 120, "playbackRate": 1.5}
    assert out["played"] == ["/silence.wav"] and out["loop"] is True and out["vol"] < 0.001
    assert out["names"] == ["nexttrack", "pause", "play", "previoustrack",
                            "seekbackward", "seekforward", "seekto"]


def test_lock_screen_source_rate_age_and_buffering_are_truthful():
    out = run("""
syncMediaSession({state:"PLAYING",title:"Film",duration:100,position:40,
                  rate:2,speed:0.5,snapshot_age_ms:750});
const playing={state:navigator.mediaSession.playbackState,
               position:{...navigator.mediaSession.position}};
syncMediaSession({state:"BUFFERING",title:"Film",duration:100,position:41,
                  rate:2,snapshot_age_ms:2500});
const buffering={state:navigator.mediaSession.playbackState,
                 position:{...navigator.mediaSession.position}};
syncMediaSession({state:"PAUSED",title:"Film",duration:100,position:20,
                  rate:0.5,snapshot_age_ms:2500});
const paused={state:navigator.mediaSession.playbackState,
              position:{...navigator.mediaSession.position}};
syncMediaSession({state:"PLAYING",title:"Film",duration:100,position:10,
                  rate:"3",snapshot_age_ms:1000});
const malformed=navigator.mediaSession.position;
const out={playing,buffering,paused,malformed};
""")
    assert out["playing"] == {
        "state": "playing",
        "position": {"duration": 100, "position": 41.5, "playbackRate": 2},
    }
    assert out["buffering"] == {
        "state": "paused",
        "position": {"duration": 100, "position": 41, "playbackRate": 2},
    }
    assert out["paused"] == {
        "state": "paused",
        "position": {"duration": 100, "position": 20, "playbackRate": 0.5},
    }
    assert out["malformed"] == {"duration": 100, "position": 11, "playbackRate": 1}


def test_handlers_call_existing_actions_with_source_seconds():
    out = run("""
syncMediaSession({state:"PAUSED",title:"T",duration:100,position:50});
shortcutState={state:"PAUSED",position:50};
handlers.play();handlers.pause();                // pause is a no-op while paused
shortcutState={state:"PLAYING",position:50};
handlers.play();handlers.pause();                // play is a no-op while playing
handlers.nexttrack();handlers.previoustrack();
handlers.seekto({seekTime:30});handlers.seekto({seekTime:-5});handlers.seekto({});
handlers.seekbackward({});handlers.seekforward({seekOffset:20});
const out={calls};
""")
    assert out["calls"] == [["play_pause", None], ["play_pause", None], ["next", None],
                            ["previous", None], ["seek", 30], ["seek", 0],
                            ["seek", 40], ["seek", 70]]


def test_idle_or_disabled_clears_the_session_and_stops_the_audio():
    out = run("""
syncMediaSession({state:"PLAYING",title:"T",duration:10,position:1});
syncMediaSession({state:"IDLE",title:""});
const idle={state:navigator.mediaSession.playbackState,paused:MEDIA.audio.paused};
syncMediaSession({state:"PLAYING",title:"T",duration:10,position:1});
store.sc_lockscreen="0";
navigator.mediaSession.playbackState="x";
syncMediaSession({state:"PAUSED",title:"T2"});
const out={idle,disabledUntouched:navigator.mediaSession.playbackState,title:navigator.mediaSession.metadata.title};
""")
    assert out["idle"] == {"state": "none", "paused": True}
    assert out["disabledUntouched"] == "x" and out["title"] == "T"    # opt-out touches nothing


def test_unsupported_browser_is_a_silent_noop():
    script = HARNESS % (
        media_code().replace('typeof navigator!=="undefined"', "false"),
        "syncMediaSession({state:'PLAYING',title:'T'});console.log(JSON.stringify({ok:true}));")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_page_wires_status_updates_the_toggle_and_the_silent_audio_route():
    html = portal._page().decode("utf-8")
    assert "shortcutState=s;" in html and "syncMediaSession(s)" in html
    assert 'id="lockControls"' in html and "Lock-screen controls" in html
    harness = RoomHarness(count=1)
    try:
        from http.client import HTTPConnection
        port = harness.server.server_address[1]
        conn = HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/silence.wav", headers={"Host": harness.host})
        reply = conn.getresponse()
        data = reply.read()
        assert reply.status == 200 and reply.getheader("Content-Type") == "audio/wav"
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
        assert struct.unpack("<I", data[40:44])[0] == len(data) - 44 == 8000
        assert set(data[44:]) == {128}
    finally:
        harness.close()
