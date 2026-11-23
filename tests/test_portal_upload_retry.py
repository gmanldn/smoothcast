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
let cancelUpload=false,csrf="session",requests=[],display=[];
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
    assert "if(!validSavedUpload(record))continue;" in SOURCE
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
