"""Guest queue keeps idle acquisition UI compact without relaxing worker permissions."""
import shutil
import subprocess

import pytest
import portal


def test_idle_transfer_panels_start_hidden_and_link_disclosure_is_present():
    page = portal._HTML
    assert 'id="libraryCopiesPanel" aria-labelledby="libraryCopiesHeading" hidden' in page
    assert 'id="linkJobPanel" aria-labelledby="linkJobsHeading" hidden' in page
    assert '<details id="linkAcquisition">' in page
    assert 'aria-describedby="linkAvailability"' in page
    assert 'panel.hidden=!rows?.length' in page
    assert 'panel.hidden=!jobs.length' in page


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_source_readiness_distinguishes_disabled_owner_and_missing_worker():
    page = portal._HTML
    controls = page[page.index("function updateLinkControls("):
                    page.index("function renderLinkJobs(")]
    harness = """
const assert=require("node:assert/strict");
const elements={linkInput:{value:"https://youtu.be/dQw4w9WgXcQ"},linkAuthorised:{checked:true}};const $=id=>elements[id]||= {};let linkCapabilities={},linkOwnerEnabled={youtube:false},linkStorageAvailable=null,linkPosting=false,youtubeSearchBusy=false;
"""
    checks = """
assert.equal(updateLinkControls(),false);assert($("linkAvailability").textContent.includes("enable guest downloads"));assert.equal($("linkInput").disabled,false);linkOwnerEnabled.youtube=true;updateLinkControls();assert($("linkAvailability").textContent.includes("check the acquisition worker"));linkCapabilities.youtube=true;assert.equal(updateLinkControls(),true);linkStorageAvailable=false;assert.equal(updateLinkControls(),false);
"""
    subprocess.run(["node", "-"], input=harness + controls + checks,
                   text=True, check=True, timeout=10)


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_download_progress_preserves_pending_cancel_control():
    page = portal._HTML
    render = page[page.index("function renderLinkJobs("):
                  page.index("if(linkForm&&", page.index("function renderLinkJobs("))]
    harness = r"""
class Node{
  constructor(){this.children=[];this.dataset={};this.attrs={};this.listeners={};this.textContent="";this.hidden=false;this.disabled=false}
  append(...items){for(const item of items)this.insertBefore(item,null)}
  insertBefore(item,before){if(item.parent)item.remove();const i=before?this.children.indexOf(before):this.children.length;this.children.splice(i,0,item);item.parent=this}
  remove(){if(this.parent){const p=this.parent;p.children.splice(p.children.indexOf(this),1);this.parent=null}}
  replaceChildren(...items){for(const item of [...this.children])item.remove();this.append(...items)}
  addEventListener(name,fn){this.listeners[name]=fn}
  setAttribute(k,v){this.attrs[k]=String(v)}
  getAttribute(k){return this.attrs[k]??null}
  hasAttribute(k){return k in this.attrs}
  removeAttribute(k){delete this.attrs[k]}
  set value(v){this.setAttribute("value",v)}
  get value(){return Number(this.attrs.value||0)}
}
const elements={linkJobs:new Node(),linkJobPanel:new Node()};
const $=id=>elements[id];
const document={createElement:()=>new Node()};
let linkCapabilities={},linkOwnerEnabled=null,linkLocalPrerequisites=null,linkStorageAvailable=null,linkSignature="";
const updateLinkControls=()=>{},openLinkAcquisition=()=>{},showError=()=>{},refresh=()=>{};
const fileUnits=String,clock=String;
let requests=[],resolvePost;
const post=(url,body)=>{requests.push([url,body]);return new Promise(resolve=>{resolvePost=resolve})};
"""
    checks = r"""
(async()=>{
const assert=(ok,message)=>{if(!ok)throw Error(message)};
const job={id:"a",kind:"youtube",title:"Film",stage:"downloading",received:10,total:100,can_cancel:true};
const render=()=>renderLinkJobs({link_jobs:[job]});
render();
const row=$("linkJobs").children[0];
const cancel=row.children.find(n=>n.textContent==="Cancel download");
assert(cancel,"cancel missing");
const pending=cancel.listeners.click();
job.received=20;render();
assert($("linkJobs").children[0]===row,"progress replaced row");
assert(row.children.find(n=>n.textContent==="Cancel download")===cancel,"progress replaced cancel");
assert(cancel.disabled,"pending cancel was re-enabled");
await cancel.listeners.click();
assert(requests.length===1,"duplicate cancel posted");
assert(row.children[2].value===20,"progress did not update");
job.total=null;render();
assert(!row.children[2].hasAttribute("value"),"unknown total must be indeterminate");
resolvePost({message:"Cancellation requested"});await pending;
job.stage="cancelled";job.can_cancel=false;job.can_retry=true;render();
assert(cancel.hidden&&!cancel.disabled,"cancel must be unavailable after cancellation");
const retry=row.children.find(n=>n.textContent==="Retry download");
assert(retry&&!retry.hidden,"retry missing");
renderLinkJobs({link_jobs:[]});assert($("linkJobs").children.length===0,"stale row remains");
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + render + checks,
                   text=True, check=True, timeout=10)
