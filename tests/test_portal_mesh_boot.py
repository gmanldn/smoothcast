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
const window={};  // the panel exports scRenderMeshRoom on window (#386)
const panel={hidden:true,contains:()=>false,previousElementSibling:null};
const nav={hidden:true},dash={hidden:false};
let vis=()=>{},csrf="initial",timeId=0;
const timers=new Map(),intervals=[];
const tick=()=>{for(const fn of intervals)fn()};
const setInterval=fn=>{intervals.push(fn);return intervals.length};
const clearInterval=()=>{};
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
const elements={meshDetails:panel,meshNavLink:nav,dashboard:dash,
  meshNodes:{children:[]},meshTargets:{children:[]},
  meshSum:{textContent:""},meshHint:{textContent:""},
  meshConn:{textContent:""},meshLive:{textContent:""}};
const document={hidden:false,activeElement:null,
  getElementById:id=>elements[id]||null,
  addEventListener:(name,fn)=>{if(name==="visibilitychange")vis=fn}};
const pending=[];
const fetch=(url,opt)=>{
  // The dedicated heartbeat poll is separate from mesh discovery.
  if(String(url).indexOf("/api/mesh/heartbeat")===0){
    return Promise.resolve({ok:true,status:200,json:async()=>({heartbeat:null})});
  }
  return new Promise((resolve,reject)=>{
    pending.push({resolve,signal:opt.signal});
    opt.signal.addEventListener("abort",()=>reject(Error("aborted")));
  });
};
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


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_network_profiles_are_visible_only_singleflight_and_session_fenced():
    script = panel_html().split("<script>", 1)[1].split("</script>", 1)[0]
    methods = script[script.index("  function profilesVisible(){"):script.index("  setInterval(profiles,10000);")]
    harness = r"""
const assert=require("node:assert/strict");
let csrf="one",blade="homePanel",started=true;
const document={hidden:false},panel={hidden:false};
const dash={hidden:false,getAttribute:()=>blade};
let profileRequest=null,profileSession=null,profileSignature=null,profileVisible=false,diagramGeneration=0;
const list={children:[],replaceChildren(){this.children=[]}};
let paints=0;
const decodes=[];
const img={hidden:true,set src(v){paints++;this.url=v},removeAttribute(){delete this.url},
  decode(){return new Promise((resolve,reject)=>decodes.push({resolve,reject}))}};
const status={textContent:""};
const $=id=>({meshProfiles:list,meshDiagram:img,meshDiagramStatus:status})[id];
const put=(id,value)=>{$(id).textContent=value};
document.getElementById=$;
const pending=[];
const fetch=(url,opt)=>new Promise(resolve=>pending.push({resolve,signal:opt.signal}));
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
const response=()=>({ok:true,json:async()=>({nodes:[]})});
"""
    scenario = r"""(async()=>{
  syncProfiles();await profiles();assert.equal(pending.length,0);
  blade="meshPanel";syncProfiles();syncProfiles();await profiles();
  assert.equal(pending.length,1);
  pending[0].resolve(response());await flush();assert.equal(paints,1);
  assert.equal(img.hidden,true);
  decodes[0].reject(Error("network"));await flush();
  assert.equal(img.hidden,true);assert.equal(profileSignature,null);
  assert.match(status.textContent,/will retry/);
  const again=profiles();pending[1].resolve(response());await again;assert.equal(paints,2);
  decodes[1].resolve();await flush();assert.equal(img.hidden,false);assert.equal(status.textContent,"");
  const unchanged=profiles();pending[2].resolve(response());await unchanged;assert.equal(paints,2);
  const stale=profiles();blade="homePanel";syncProfiles();
  assert.equal(pending[3].signal.aborted,true);
  pending[3].resolve(response());await stale;assert.equal(paints,2);
  blade="meshPanel";syncProfiles();const old=pending[4];
  csrf="two";syncProfiles();assert.equal(old.signal.aborted,true);
  assert.equal(img.hidden,true);
  old.resolve(response());await flush();assert.equal(paints,2);
  pending[5].resolve(response());await flush();assert.equal(paints,3);
  // A successful decode from a signed-out room must not show its diagram.
  dash.hidden=true;syncProfiles();decodes[2].resolve();await flush();
  assert.equal(img.hidden,true);
  assert.match(status.textContent,/Waiting/);
  assert.equal(list.children.length,0);
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result = subprocess.run(["node", "-"], input=harness + methods + scenario,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_mesh_heartbeat_and_events_are_fenced_to_current_room():
    script = panel_html().split("<script>", 1)[1].split("</script>", 1)[0]
    methods = script[script.index("  async function heartbeat(){"):script.index("  function cancelMeshRetry()")]
    harness = r"""
const assert=require("node:assert/strict");
let csrf="one",meshSession="one",visible=true,beatRequest=null,beatTimer=null,es=null,backoff=3000;
const dash={hidden:false};
const profilesVisible=()=>visible&&!dash.hidden;
const labels=[],messages=[],applied=[],pending=[],streams=[];
let scheduled=0,timerId=0;
const put=(id,value)=>labels.push([id,value]),markMesh=value=>messages.push(value),conn=()=>{};
const heartbeatText=b=>b?.name||"unavailable",apply=value=>applied.push(value),schedule=()=>scheduled++;
const setInterval=()=>++timerId,clearInterval=()=>{};
const fetch=(url,opt)=>new Promise(resolve=>pending.push({resolve,signal:opt.signal}));
class EventSource{
  constructor(){streams.push(this)}
  addEventListener(_,fn){this.event=fn}
  close(){this.closed=true}
}
"""
    scenario = r"""
(async()=>{
  syncHeartbeat();syncHeartbeat();
  assert.equal(pending.length,1);
  visible=false;syncHeartbeat();
  assert.equal(pending[0].signal.aborted,true);
  pending[0].resolve({ok:true,json:async()=>({heartbeat:{name:"obsolete"}})});
  await Promise.resolve();await Promise.resolve();
  assert.equal(labels.length,0);
  visible=true;syncHeartbeat();
  const old=pending[1];
  csrf="two";meshSession="two";stopHeartbeat();syncHeartbeat();
  old.resolve({ok:true,json:async()=>({heartbeat:{name:"old"}})});
  pending[2].resolve({ok:true,json:async()=>({heartbeat:{name:"current"}})});
  for(let i=0;i<6;i++)await Promise.resolve();
  assert.deepEqual(labels,[["meshHeartbeat","current"]]);
  open();const first=streams[0];
  first.event({data:'{"type":"snapshot"}'});
  assert.equal(applied.length,1);
  open();const second=streams[1];
  assert.equal(first.closed,true);
  first.event({data:'{"type":"delta"}'});
  first.readyState=2;first.onerror();
  assert.equal(applied.length,1);assert.equal(scheduled,0);
  second.event({data:'{"type":"delta"}'});
  assert.equal(applied.length,2);
  csrf="three";
  second.event({data:'{"type":"delta"}'});
  second.readyState=2;second.onerror();
  assert.equal(applied.length,2);assert.equal(scheduled,0);
  dash.hidden=true;close();syncHeartbeat();
  assert.equal(second.closed,true);
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result = subprocess.run(["node", "-"], input=harness + methods + scenario,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
