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
const window={},csrf="session-fixture";
const setInterval=()=>{};
const requests=[];
const fetch=async(url,options)=>{
  requests.push({url,body:JSON.parse(options.body)});
  return {ok:true,json:async()=>({})};
};
"""
    scenario = r"""
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
window.scRenderScreens({screens:[{...one,state:"playing"}],
  queue:[{id:"track",title:"First"}]});
toggle.listeners.click();
assert.equal(requests.at(-1).body.action,"pause","handler must not capture a stale state");
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
"""
    subprocess.run(
        ["node", "-"], input=harness + script + scenario,
        check=True, text=True, timeout=12,
    )
