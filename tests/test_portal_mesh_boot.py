"""Mesh discovery must not reopen an expired guest session (headless Node.js)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from portal_mesh_panel import panel_html


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_mesh_boot_singleflight_and_stale_session_rejection():
    script = panel_html().split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r"""
const assert=require("node:assert/strict");
const panel={hidden:true,contains:()=>false,previousElementSibling:null};
const nav={hidden:true},dash={hidden:false};
let tick=()=>{},vis=()=>{},csrf="initial",timeId=0;
const timers=new Map();
const setInterval=fn=>{tick=fn};
const setTimeout=(fn,ms)=>{const id=++timeId;timers.set(id,{fn,ms});return id};
const clearTimeout=id=>timers.delete(id);
class AbortController{
  constructor(){
    this.callbacks=[];
    this.signal={aborted:false,addEventListener:(name,fn)=>{
      if(name==="abort")this.callbacks.push(fn);
    }};
  }
  abort(){
    if(this.signal.aborted)return;
    this.signal.aborted=true;
    for(const fn of this.callbacks)fn();
  }
}
const elements={meshPanel:panel,meshNavLink:nav,dashboard:dash,
  meshNodes:{children:[]},meshTargets:{children:[]},
  meshSum:{textContent:""},meshHint:{textContent:""},
  meshConn:{textContent:""},meshLive:{textContent:""}};
const document={hidden:false,activeElement:null,
  getElementById:id=>elements[id]||null,
  addEventListener:(name,fn)=>{if(name==="visibilitychange")vis=fn}};
const pending=[];
const fetch=(_url,opt)=>new Promise((resolve,reject)=>{
  pending.push({resolve,signal:opt.signal});
  opt.signal.addEventListener("abort",()=>reject(Error("aborted")));
});
const events=[];
class EventSource{
  constructor(url){this.url=url;events.push(this)}
  addEventListener(){}
  close(){this.closed=true}
}
"""
    scenario = r"""
(async()=>{
  tick();tick();tick();
  assert.equal(pending.length,1,"inflight discovery must not overlap");
  dash.hidden=true;tick();
  assert.equal(pending[0].signal.aborted,true,"logout aborts discovery");
  assert.equal(panel.hidden,true);
  await Promise.resolve();await Promise.resolve();
  dash.hidden=false;csrf="new";tick();
  assert.equal(pending.length,2);
  pending[1].resolve({ok:true,status:200,
    json:async()=>({mesh:{nodes:[],local:"self",primary:"self"}})});
  for(let i=0;i<6;i++)await Promise.resolve();
  assert.equal(panel.hidden,false,"current session can show mesh");
  assert.equal(nav.hidden,false);
  assert.equal(events.length,1,"only one SSE for current session");
  dash.hidden=true;tick();
  dash.hidden=false;csrf="third";tick();
  assert.equal(pending.length,3);
  let finishJSON;
  pending[2].resolve({ok:true,status:200,
    json:()=>new Promise(resolve=>{finishJSON=resolve})});
  for(let i=0;i<3;i++)await Promise.resolve();
  assert.equal(typeof finishJSON,"function");
  csrf="fourth";
  finishJSON({mesh:{nodes:[],local:"stale",primary:"stale"}});
  for(let i=0;i<5;i++)await Promise.resolve();
  assert.equal(events.length,1,"stale response must not reopen SSE");
  assert.equal(panel.hidden,true,"stale response must not reopen panel");
  tick();assert.equal(pending.length,4,"new session can retry");
  document.hidden=true;vis();
  assert.equal(pending[3].signal.aborted,true,"tab hide aborts discovery");
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-"], input=harness + script + scenario,
        capture_output=True, text=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr
