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
