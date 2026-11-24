"""Headless browser-screen DOM stability and command targeting, no GTK/TV."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal_screen_page


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_status_refresh_preserves_screen_controls_and_uses_latest_state():
    """Polling must not interrupt selection, focus, or receiver-specific commands."""
    panel = portal_screen_page.panel_html()
    script = panel.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r"""
const assert=require("node:assert/strict");
class FakeNode {
  constructor(tag){
    this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.listeners={};
    this.hidden=false;this.value="";this.className="";this.textContent="";
    this.parentElement=null;this.attrs={};
  }
  append(...items){for(const item of items){item.remove();item.parentElement=this;this.children.push(item)}}
  replaceChildren(...items){
    for(const item of this.children)item.parentElement=null;
    this.children=[];this.append(...items);
  }
  insertBefore(node,reference){
    node.remove();
    let index=reference?this.children.indexOf(reference):this.children.length;
    if(index<0)index=this.children.length;
    this.children.splice(index,0,node);node.parentElement=this;
  }
  remove(){
    if(this.parentElement){
      const children=this.parentElement.children,index=children.indexOf(this);
      if(index>=0)children.splice(index,1);
      this.parentElement=null;
    }
  }
  setAttribute(name,value){this.attrs[name]=value}
  addEventListener(name,handler){this.listeners[name]=handler}
  get firstElementChild(){return this.children[0]||null}
  get previousElementSibling(){
    if(!this.parentElement)return null;
    const index=this.parentElement.children.indexOf(this);
    return this.parentElement.children[index-1]||null;
  }
  contains(node){for(let cursor=node;cursor;cursor=cursor.parentElement)if(cursor===this)return true;return false}
  focus(){document.activeElement=this}
  after(node){
    if(!this.parentElement)return;
    const index=this.parentElement.children.indexOf(this);
    this.parentElement.insertBefore(node,this.parentElement.children[index+1]||null);
  }
}
const list=new FakeNode("ul"),panelNode=new FakeNode("section"),heading=new FakeNode("h2");
const queuePanel=new FakeNode("section");queuePanel.after=()=>{};
const elements={
  screensList:list,screensPanel:panelNode,screensCount:new FakeNode("span"),
  screensMsg:new FakeNode("p"),dashboard:new FakeNode("div"),
  queuePanel,screensPanelHeading:heading
};
const document={
  activeElement:null,getElementById:id=>elements[id]||null,
  createElement:tag=>new FakeNode(tag)
};
const window={};let csrf="session-fixture";
const setInterval=()=>{};
const requests=[];
let fetch=async(url,options)=>{
  requests.push({url,body:JSON.parse(options.body)});
  return {ok:true,json:async()=>({})};
};
"""
    scenario = r"""
(async()=>{
const one={id:"screen-1",name:"Kitchen",ready:true,video:false,
  state:"paused",item:"track",title:"First",position:0,duration:60};
window.scRenderScreens({screens:[one],queue:[{id:"track",title:"First"}]});
const row=list.children[0],pick=row.children[1].children[0];
const play=row.children[1].children[1],toggle=row.children[1].children[2];
pick.value="track";pick.listeners.change();pick.focus();
assert.equal(play.disabled,false);
window.scRenderScreens({screens:[{...one,state:"playing",title:"Changed",position:12}],
  queue:[{id:"track",title:"First"}]});
assert.equal(list.children[0],row,"poll must preserve row identity");
assert.equal(row.children[1].children[0],pick,"poll must preserve select identity");
assert.equal(row.children[1].children[1],play,"poll must preserve button identity");
assert.equal(document.activeElement,pick,"poll must not steal keyboard focus");
assert.equal(toggle.textContent,"Pause");
assert.match(row.children[0].children[1].textContent,/Changed/);
window.scRenderScreens({screens:[{...one,ready:false}],queue:[{id:"track",title:"First"}]});
assert.equal(play.disabled,true);
assert.equal(toggle.disabled,true);
assert.equal(document.activeElement,pick);
window.scRenderScreens({screens:[one],queue:[{id:"track",title:"First"}]});
toggle.listeners.click();
assert.equal(requests.at(-1).body.action,"resume","handler must use the latest state");
for(let i=0;i<5;i++)await Promise.resolve();
window.scRenderScreens({screens:[{...one,state:"playing"}],
  queue:[{id:"track",title:"First"}]});
toggle.listeners.click();
assert.equal(requests.at(-1).body.action,"pause","handler must not capture a stale state");
for(let i=0;i<5;i++)await Promise.resolve();
window.scRenderScreens({screens:[{...one,state:"playing"}],queue:[]});
assert.equal(list.children[0],row,"queue changes must retain the screen row");
assert.equal(pick.value,"");
assert.equal(play.disabled,true,"removed queue item must not be playable");
assert.equal(document.activeElement,pick);
const second={...one,id:"screen-2",name:"Study"};
window.scRenderScreens({screens:[one,second],queue:[]});
const secondRow=list.children[1];
const nativeInsert=list.insertBefore.bind(list);
list.insertBefore=(node,reference)=>{
  nativeInsert(node,reference);
  document.activeElement=null; // Simulate browsers that blur controls on node moves.
};
window.scRenderScreens({screens:[second,one],queue:[]});
assert.equal(list.children[0],secondRow);
assert.equal(list.children[1],row);
assert.equal(document.activeElement,pick,"reordering must recover focused control");
list.insertBefore=nativeInsert;
toggle.focus();
window.scRenderScreens({screens:[],queue:[]});
assert.equal(document.activeElement,heading,"disconnected focused screen returns to heading");
assert.equal(list.children[0].textContent,"No screens connected");
window.scRenderScreens({screens:[one],queue:[{id:"track",title:"First"}]});
const liveRow=list.children[0],buttons=liveRow.children[1].children;
const select=buttons[0],livePlay=buttons[1],liveToggle=buttons[2];
select.value="track";select.listeners.change();
const pending=[],before=requests.length;
fetch=(url,options)=>new Promise(resolve=>{
  requests.push({url,body:JSON.parse(options.body)});
  pending.push(resolve);
});
liveToggle.listeners.click();livePlay.listeners.click();liveToggle.listeners.click();
assert.equal(requests.length,before+1,"duplicate taps must be coalesced");
assert.equal(liveRow.attrs["aria-busy"],"true");
assert.equal(livePlay.attrs["aria-disabled"],"true");
window.scRenderScreens({screens:[one],queue:[{id:"track",title:"First"}]});
assert.equal(livePlay.attrs["aria-disabled"],"true","poll must not unlock pending commands");
const other={...one,id:"screen-2",name:"Study"};
window.scRenderScreens({screens:[one,other],queue:[{id:"track",title:"First"}]});
const otherRow=list.children[1],otherToggle=otherRow.children[1].children[2];
otherToggle.listeners.click();
assert.equal(requests.length,before+2,"another screen must not be blocked");
assert.equal(otherRow.attrs["aria-busy"],"true");
pending[0]({ok:true,json:async()=>({})});
for(let i=0;i<5;i++)await Promise.resolve();
assert.equal(liveRow.attrs["aria-busy"],"false");
assert.equal(livePlay.attrs["aria-disabled"],"false");
assert.equal(otherRow.attrs["aria-busy"],"true","other screen still waiting");
otherToggle.listeners.click();
assert.equal(requests.length,before+2,"duplicate on second screen suppressed");
pending[1]({ok:true,json:async()=>({})});
for(let i=0;i<5;i++)await Promise.resolve();
assert.equal(otherRow.attrs["aria-busy"],"false");
liveToggle.listeners.click();
assert.equal(requests.length,before+3);
csrf="replacement";
elements.screensMsg.textContent="New room";
pending[2]({ok:true,json:async()=>({})});
for(let i=0;i<5;i++)await Promise.resolve();
assert.equal(elements.screensMsg.textContent,"New room");
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(
        ["node", "-"], input=harness + script + scenario,
        check=True, text=True, timeout=12,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_screen_start_failure_is_retryable_and_shortcuts_respect_input():
    """Registration failure cannot strand the screen or start polling prematurely."""
    html = portal_screen_page.screen_page().decode()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r"""
const nodes=new Map();
function node(id){
  if(!nodes.has(id))nodes.set(id,{hidden:true,disabled:false,value:"",textContent:"",listeners:{},
    classList:{add(){},remove(){},toggle(){}},style:{},addEventListener(k,fn){this.listeners[k]=fn},
    canPlayType(){return "maybe"}});
  return nodes.get(id);
}
let fullscreens=0,beats=0;
const document={getElementById:node,createElement:node,listeners:{},hidden:false,
  addEventListener(k,fn){this.listeners[k]=fn},
  documentElement:{requestFullscreen(){fullscreens++;return Promise.resolve()}}};
const location={host:"127.0.0.1"};
const navigator={},window={addEventListener(){}};
const localStorage={getItem(){return ""},setItem(){}},sessionStorage=localStorage;
const setInterval=()=>{beats++},setTimeout=()=>1,clearTimeout=()=>{};
const requests=[],pending=[];
const fetch=(url,options)=>new Promise((resolve,reject)=>{
  requests.push({url,options});pending.push({resolve,reject});
});
function check(ok,msg){if(!ok)throw Error(msg)}
const response=(status,data)=>({ok:status<400,status,json:async()=>data});
const event={preventDefault(){}};
"""
    scenario = r"""
(async()=>{
  node("name").value="Office";node("pin").value="123456";
  const login1=login(event),login2=login(event);
  check(requests.length===1,"duplicate join");check(node("loginSubmit").disabled,"join busy");
  pending[0].resolve(response(200,{csrf:"test"}));await Promise.all([login1,login2]);
  check(!node("startView").hidden,"start visible");
  const start1=begin(),start2=begin();
  check(requests.length===2,"duplicate start");check(node("startButton").disabled,"start busy");
  check(!started&&beats===0,"premature start");
  pending[1].reject(Error("network"));await Promise.all([start1,start2]);
  check(!started&&!node("startView").hidden&&node("slate").hidden,"failed start must remain retryable");
  check(!node("startButton").disabled&&node("startError").textContent.includes("try again"),"retry guidance");
  const retry=begin();pending[2].resolve(response(401,{}));await retry;
  check(!node("loginView").hidden&&!started&&beats===0,"expired registration needs login");
  const login3=login(event);pending[3].resolve(response(200,{csrf:"new"}));await login3;
  const success=begin();pending[4].resolve(response(200,{screen:{id:"s",name:"Office",seq:0,play_seq:0}}));await success;
  check(started&&!node("slate").hidden&&beats===1,"successful registration starts heartbeat");
  check(requests.length===6&&requests[5].url.includes("/poll?"),"poll only after success");
  const key=(target,extra={})=>document.listeners.keydown({key:"f",target,preventDefault(){},...extra});
  key({tagName:"INPUT"});key({tagName:"DIV",isContentEditable:true});key({tagName:"DIV"},{ctrlKey:true});key({tagName:"DIV"},{repeat:true});
  check(fullscreens===0,"typing/modified keys must not fullscreen");
  key({tagName:"DIV"});check(fullscreens===1,"fullscreen shortcut remains available");
})()
.catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   check=True, text=True, timeout=12)
