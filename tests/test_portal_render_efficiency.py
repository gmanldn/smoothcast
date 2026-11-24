"""Portal avoids idle animation and redundant snapshot DOM rebuilding."""
import shutil
import subprocess

import pytest
import portal


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_playhead_scheduler_stops_on_idle_hidden_end_and_expiry():
    html = portal._HTML
    code = html[html.index("function clock(s){"):html.index("let queueRenderKey=")]
    harness = """
const assert=require("node:assert/strict");
let csrf="session",stalePage=false;
const document={hidden:false};
let now=0,serial=0;
const timers=new Map();
const performance={now:()=>now};
const setTimeout=(f,ms)=>{timers.set(++serial,f);return serial};
const clearTimeout=id=>timers.delete(id);
const fields={progress:{},elapsed:{},seek:{}};
const $=id=>fields[id];
const editingControls=new Set();
const tick=(ms)=>{now+=ms;const callbacks=[...timers.values()];timers.clear();for(const f of callbacks)f()};
"""
    checks = """
assert.equal(timers.size,0);
trackPlayhead({state:"PAUSED",position:3,duration:10});
assert.equal(timers.size,0);
trackPlayhead({state:"PLAYING",position:3,duration:10});
assert.equal(timers.size,1);
tick(200);
assert.equal(timers.size,1);
trackPlayhead({state:"PLAYING",position:9.95,duration:10});
tick(200);
assert.equal(fields.progress.value,10);
assert.equal(timers.size,0);
trackPlayhead({state:"PLAYING",position:1,duration:10});
document.hidden=true;stopPlayhead();
assert.equal(timers.size,0);
document.hidden=false;schedulePlayhead();
assert.equal(timers.size,1);
csrf="";tick(200);
assert.equal(timers.size,0);
"""
    subprocess.run(["node", "-"], input=harness + code + checks,
                   text=True, check=True, timeout=10)


def test_snapshot_renderers_guard_unchanged_content():
    html = portal._HTML
    assert "if(signature===networkActivityKey)return;" in html
    assert "if(signature!==participantRenderKey)" in html
    assert "requestAnimationFrame(playheadFrame)" not in html
