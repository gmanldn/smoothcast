"""Headless browser retry reconciliation; no GUI or receiver (issue #568)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "src" / "portal.py").read_text("utf-8")


def _retry_js() -> str:
    start = "async function sendChunk(path,file,offset,end){"
    end = "// Keep only upload metadata."
    assert SOURCE.count(start) == 1
    return start + SOURCE.split(start, 1)[1].split(end, 1)[0]


def test_upload_retry_reconciles_exact_offsets():
    js = _retry_js()
    assert "state.received===end" in js
    assert "state.received!==offset" in js
    assert "statusError.offsetMismatch" in js
    assert "statusError.status===403" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_real_browser_retry_js_handles_committed_uncommitted_and_conflicting_offsets():
    js = """
let cancelUpload=false,pauseRequested=false,csrf="session",requests=[],display=[];
let uploadRequest=async()=>{throw Error("not configured")};
const showError=(...a)=>display.push(a);
""" + _retry_js() + r"""
(async()=>{
 const file={size:100,slice(start,end){return Buffer.alloc(end-start)}};
 const failure=()=>Object.assign(Error("conflict"),{status:409});
 uploadRequest=async(method)=>{
   requests.push(method);
   if(method==="PUT")throw failure();
   return {received:20,complete:false};
 };
 const already=await sendChunk("/api/uploads/id",file,0,20);
 if(already.received!==20||requests.join(",")!=="PUT,GET")
   throw Error("acknowledged chunk should not be resent");
 requests=[];
 uploadRequest=async(method)=>{
   requests.push(method);
   if(method==="PUT")throw failure();
   return {received:10};
 };
 try{
   await sendChunk("/api/uploads/id",file,0,20);
   throw Error("mismatch silently accepted");
 }catch(error){
   if(!error.offsetMismatch)throw error;
 }
 if(requests.join(",")!=="PUT,GET")throw Error("mismatched offset retried");
 requests=[];
 let attempts=0;
 uploadRequest=async(method)=>{
   requests.push(method);
   if(method==="GET")return {received:0};
   if(attempts++===0)throw failure();
   return {received:20};
 };
 const retried=await sendChunk("/api/uploads/id",file,0,20);
 if(retried.received!==20||requests.join(",")!=="PUT,GET,PUT")
   throw Error("uncommitted chunk was not safely retried");
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr


def _upload_validation_js() -> str:
    start = "const MAX_UPLOAD_CHUNK_BYTES=8*1024*1024;"
    end = "async function clearPendingUpload(){"
    assert SOURCE.count(start) == 1
    return start + SOURCE.split(start, 1)[1].split(end, 1)[0]


def test_upload_validation_guards_creation_restore_and_send_paths():
    assert "records.filter(validSavedUpload)" in SOURCE
    assert "validUploadChunkSize(chunkSize)" in SOURCE
    assert "validUploadProgress(state.received,file.size)" in SOURCE


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_actual_upload_validation_js_rejects_nonprogressing_and_corrupt_records():
    js = _upload_validation_js() + r"""
const id="a".repeat(32);
const base={id,name:"film.mkv",chunkSize:8*1024*1024,size:20,received:0};
const reject=[0,-1,1.5,NaN,Infinity,"2",8*1024*1024+1,Number.MAX_SAFE_INTEGER];
for(const chunkSize of reject){
  if(validUploadChunkSize(chunkSize))throw Error("bad chunk accepted: "+chunkSize);
  if(validSavedUpload({...base,chunkSize}))throw Error("corrupt saved chunk accepted");
}
for(const received of [-1,21,Infinity,NaN,0.25,"0"]){
  if(validSavedUpload({...base,received}))throw Error("bad offset accepted");
}
if(!validSavedUpload(base)||!validUploadChunkSize(2*1024*1024))
  throw Error("valid or legacy chunk rejected");
if(!validSavedUpload({...base,received:20}))
  throw Error("completed upload metadata rejected");
if(validSavedUpload({...base,id:"bad"})||validSavedUpload({...base,size:0}))
  throw Error("malformed upload record accepted");
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr


def _complete_js() -> str:
    start = "async function completeUpload(path,queueOnly,headers){"
    end = "// Keep only upload metadata."
    assert SOURCE.count(start) == 1
    return start + SOURCE.split(start, 1)[1].split(end, 1)[0]


def test_final_room_action_is_retried_not_stalled():
    js = _complete_js()
    assert "client_reload_required" in js
    assert "[408,409,429].includes(error.status)" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_actual_complete_js_retries_transient_dispatch_and_stops_on_reload():
    js = """
let cancelUpload=false,pauseRequested=false,csrf="session",events=[],display=[];
let uploadRequest=async()=>{throw Error("not configured")};
const transferEvent=(m)=>events.push(m),showError=(...a)=>display.push(a);
""" + _complete_js() + r"""
(async()=>{
 let calls=0;
 uploadRequest=async()=>{calls++;if(calls===1)throw Object.assign(Error("busy"),{status:503});return {ok:true,queue_only:true}};
 const ok=await completeUpload("/api/uploads/id",false,{});
 if(calls!==2||ok.queue_only!==true)throw Error("transient dispatch was not retried");
 calls=0;
 uploadRequest=async()=>{calls++;throw Object.assign(Error("reload"),{status:409,code:"client_reload_required"})};
 try{await completeUpload("/api/uploads/id",false,{});throw Error("reload stall retried")}
 catch(error){if(error.code!=="client_reload_required")throw error}
 if(calls!==1)throw Error("reload required must not retry");
 calls=0;
 uploadRequest=async()=>{calls++;throw Object.assign(Error("disk"),{status:413,code:"upload.disk_full"})};
 try{await completeUpload("/api/uploads/id",false,{});throw Error("hard error retried")}
 catch(error){if(error.status!==413)throw error}
 if(calls!==1)throw Error("non-transient error must not retry");
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr


def _recovery_order_js() -> str:
    start = '    const records=await uploadStorage("readonly",store=>store.getAll());'
    end = "    for(const record of candidates){"
    assert SOURCE.count(start) == 1 and SOURCE.count(end) == 1
    return start + SOURCE.split(start, 1)[1].split(end, 1)[0]


def test_restoration_filters_before_sorting():
    js = _recovery_order_js()
    assert "records.filter(validSavedUpload)" in js
    assert "candidates.sort((a,b)=>started(b)-started(a))" in js
    assert "Number.isSafeInteger(record.started)" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_actual_restoration_js_skips_corrupt_records_and_sorts_valid_uploads():
    js = _upload_validation_js() + r"""
async function run(storedRecords){
  const uploadStorage=async()=>storedRecords;
""" + _recovery_order_js() + r"""
  return candidates.map(item=>item.id);
}
(async()=>{
  const base={name:"film.mkv",chunkSize:2*1024*1024,size:100,received:0};
  const old={...base,id:"a".repeat(32),started:10};
  const newer={...base,id:"b".repeat(32),started:30};
  const badTime={...base,id:"c".repeat(32),started:"corrupt"};
  const corrupt={...base,id:"d".repeat(32),chunkSize:0,started:999};
  const result=await run([null,corrupt,badTime,old,undefined,newer]);
  if(result.join(",")!==[newer.id,old.id,badTime.id].join(","))
    throw Error("invalid records crash or bias the order");
  if((await run(null)).length!==0||(await run({not:"array"})).length!==0)
    throw Error("malformed storage response should be empty");
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
