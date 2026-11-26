"""Browser-only transfer-stage and queue control contracts (no GUI or receiver)."""
from __future__ import annotations

from html.parser import HTMLParser
import shutil
import subprocess
import pytest
import portal


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            assert data["id"] not in self.ids
            self.ids[data["id"]] = data


def test_upload_journey_and_queue_accessibility():
    page = Elements()
    page.feed(portal._HTML)
    for name in ("transferSteps", "transferStage", "transferBytes", "transferRate",
                 "transferEta", "transferDestination", "transferPercent",
                 "pauseUpload", "cancelUpload", "uploadProgress", "queueFeedback",
                 "transferLiveHeading", "transferFileName", "transferOperation",
                 "transferElapsed", "transferInFlight", "transferResponse",
                 "transferDelivery", "transferAck", "transferEvents", "transferRoomState"):
        assert name in page.ids
    assert page.ids["queueFeedback"]["aria-live"] == "polite"
    assert page.ids["uploadProgress"]["aria-label"] == "File transfer bytes received"
    assert portal._HTML.count('data-stage="') == 5
    assert "Cross-node routing will appear only when" in portal._HTML
    assert 'if(pauseRequested)throw Error("Transfer paused")' in portal._HTML
    assert 'state=await uploadRequest("GET","/api/uploads/"+pendingUpload.id)' in portal._HTML
    assert 'queue_revision:queueRevision' in portal._HTML
    assert 'body.queue_command_id=' in portal._HTML
    assert "Queue action was not applied:" in portal._HTML
    assert "Play requested; waiting for the TV or speaker to start." in portal._HTML


def test_real_browser_progress_code_reports_only_acknowledged_bytes():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for the headless JS contract")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    helper = script[script.index("const TRANSFER_STAGES="):
                    script.index("const MAX_UPLOAD_CHUNK_BYTES=")]
    harness = """
const assert=require("node:assert/strict");
let now=0;const performance={now:()=>now};
const steps=["choose","prepare","transfer","verify","deliver"].map(stage=>({
  dataset:{stage},classList:{v:new Set(),toggle(k,v){if(v)this.v.add(k);else this.v.delete(k)},
    contains(k){return this.v.has(k)}},attrs:{},
  setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]}}));
const el={transferSteps:{children:steps},uploadQueue:{checked:true},
  transferDestination:{},transferPercent:{},transferBytes:{},transferRate:{},
  transferEta:{},transferStage:{},uploadProgress:{max:1,value:0}};
const $=id=>el[id];
"""
    checks = """
transferView("choose");
assert.equal(el.uploadProgress.value,0);
transferView("prepare",0,10485760);
assert(steps[1].classList.contains("active"));
transferView("transfer",0,10485760);
now=1500;transferView("transfer",2097152,10485760);
assert.equal(el.transferPercent.textContent,"20%");
assert.equal(el.uploadProgress.value,2097152);
assert(el.transferRate.textContent.includes("MiB/s"));
assert(el.transferEta.textContent.includes("remaining"));
assert.equal(el.transferDestination.textContent,"Up Next");
el.uploadQueue.checked=false;
transferView("verify",10485760,10485760);
assert.equal(el.transferPercent.textContent,"100%");
assert(steps[3].classList.contains("active"));
assert.equal(steps[3].attrs["aria-current"],"step");
assert.equal(el.transferDestination.textContent,"TV or speaker (pending)");
transferView("deliver",10485760,10485760);
assert(steps[4].classList.contains("active"));
transferView("transfer",10485761,10485760);
assert.equal(el.uploadProgress.value,0,"invalid byte count must never be displayed");
"""
    subprocess.run(["node", "-"], input=harness+helper+checks,
                   check=True, timeout=10, text=True)

def test_pause_aborts_chunk_retry_without_implicit_resend():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for the headless JS contract")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    segment = script[script.index("async function sendChunk("):
                     script.index("// Keep only upload metadata.", script.index("async function sendChunk("))]
    harness = """
const assert=require("node:assert/strict");
let pauseRequested=false,cancelUpload=false,csrf="session";
let calls=0;
const file={size:12,slice:(a,b)=>({start:a,end:b})};
async function uploadRequest(){
  calls++;
  if(calls===1){pauseRequested=true;throw Error("aborted by user");}
  return {received:12};
}
function showError(){throw Error("Retry should not run after pause")}
"""
    checks = """
(async()=>{
 await assert.rejects(sendChunk("/api/uploads/example",file,0,12),/Transfer paused/);
 assert.equal(calls,1,"must not retry a paused chunk");
 pauseRequested=false;
 const state=await sendChunk("/api/uploads/example",file,0,12);
 assert.equal(state.received,12);
 assert.equal(calls,2);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness+segment+checks,
                   check=True, timeout=10, text=True)


def test_upload_stage_reset_gracefully_handles_minimal_status_dom():
    """Expiring a session cannot crash when a test/partial DOM omits stage children."""
    if not shutil.which("node"):
        pytest.skip("Node.js needed for headless browser contract")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    helper = script[script.index("const TRANSFER_STAGES="):
                    script.index("const MAX_UPLOAD_CHUNK_BYTES=")]
    harness = """
const assert = require("node:assert/strict");
const performance = {now:()=>0};
const elements = {};
const $ = id => elements[id] ||= {textContent:"",value:0,checked:true};
"""
    checks = """
transferView("choose");
assert.equal($("transferStage").textContent,"Choose media");
assert.equal($("uploadProgress").value,0);
assert.equal($("transferPercent").textContent,"—");
transferView("transfer",2,4);
assert.equal($("transferPercent").textContent,"50%");
assert.equal($("uploadProgress").value,2);
"""
    subprocess.run(["node", "-"], input=harness + helper + checks,
                   check=True, timeout=10, text=True)


def test_live_monitor_separates_sender_progress_from_host_ack_and_records_failure():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for headless browser contract")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    monitor = script[script.index("let transferEvents=[];"):
                     script.index("async function sendChunk(")]
    formatter = script[script.index("function fileUnits("):
                       script.index("function transferView(")]
    validator = script[script.index("function validUploadProgress("):
                       script.index("function validSavedUpload(")]
    harness = """
const assert=require("node:assert/strict");
const elements={};
const $=id=>elements[id] ||= {textContent:""};
let stalePage=false,csrf="secret",clientHeaders={"X-SmoothCast-Client-Build":"build"};
let activeUploadController=null,abortCalls=0,request=null;
const showUpdateNotice=()=>{};
class XMLHttpRequest {
  constructor(){this.upload={};this.headers={};request=this;}
  open(method,path){this.method=method;this.path=path;}
  setRequestHeader(name,value){this.headers[name]=value;}
  getResponseHeader(){return null;}
  send(body){this.upload.onprogress({lengthComputable:true,loaded:body.size,total:body.size});}
  abort(){abortCalls++;this.onabort();}
}
const fetch=async()=>({status:503,ok:false,headers:{get:()=>null},
  json:async()=>({ok:false,error:"Host storage unavailable",code:"upload.disk_full"})});
"""
    checks = """
(async()=>{
  resetTransferMonitor();
  const pending=uploadRequest("PUT","/api/uploads/private-id",{size:4096},
    {"Content-Range":"bytes 0-4095/8192"});
  assert.equal(request.headers["X-CSRF-Token"],"secret");
  assert.equal(request.headers["X-SmoothCast-Client-Build"],"build");
  assert($("transferInFlight").textContent.includes("not yet confirmed"));
  assert.equal($("transferAck").textContent,"—");
  assert($("transferOperation").textContent.includes("waiting for host storage"));
  request.status=200;
  request.responseText=JSON.stringify({ok:true,received:4096,size:8192});
  request.onload();
  await pending;
  assert.equal($("transferAck").textContent,"4.0 KiB");
  assert.equal($("transferInFlight").textContent,"Chunk acknowledged by host");
  assert.equal(activeUploadController,null);
  const malformed=uploadRequest("PUT","/api/uploads/private-id",{size:4096});
  request.status=200;
  request.responseText=JSON.stringify({ok:true,received:9000,size:8192});
  request.onload();
  await assert.rejects(malformed,/unexpected reply/);
  assert.equal($("transferAck").textContent,"4.0 KiB");
  assert.notEqual($("transferInFlight").textContent,"Chunk acknowledged by host");
  const interrupted=uploadRequest("PUT","/api/uploads/private-id",{size:4096});
  activeUploadController.abort();
  await assert.rejects(interrupted,/interrupted/);
  assert.equal(abortCalls,1);
  await assert.rejects(uploadRequest("POST","/api/uploads/private-id/complete","{}"),
    {status:503,code:"upload.disk_full"});
  assert($("transferResponse").textContent.includes("HTTP 503"));
  assert($("transferEvents").textContent.includes("Host storage unavailable"));
  assert(!$("transferEvents").textContent.includes("private-id"));
  assert(!$("transferEvents").textContent.includes("secret"));
  for(let n=0;n<40;n++)transferEvent("event "+n);
  assert.equal(transferEvents.length,24);
  assert($("transferEvents").textContent.split("\\n")[0].includes("event 39"));
  resetTransferMonitor();
  assert.equal(transferEvents.length,0);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness+formatter+validator+monitor+checks,
                   check=True, timeout=10, text=True)
