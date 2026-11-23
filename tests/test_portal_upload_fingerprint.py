"""Headless browser-upload fingerprint regression (issue #568)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "src" / "portal.py").read_text("utf-8")


def _js() -> str:
    marker = "const UPLOAD_FINGERPRINT_BYTES=64*1024;"
    assert SOURCE.count(marker) == 1
    return marker + SOURCE.split(marker, 1)[1].split(
        "async function clearPendingUpload()", 1,
    )[0]


def test_new_fingerprints_are_bounded_and_old_records_remain_supported():
    js = _js()
    assert "hashVersion:3,hash:await firstChunkHash(file,chunkSize)" in SOURCE
    assert "upload.hashVersion||1" in js
    assert "new Set(offsets)" in js
    assert "offset+=16*1024" in js
    assert "Math.min(file.size,chunkSize,8*1024*1024)" in js
    assert "await new Promise(resolve=>setTimeout(resolve,0))" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_real_js_samples_first_middle_last_and_accepts_existing_v1_v2():
    js = _js() + r"""
(async()=>{
  const data=Buffer.alloc(8*1024*1024,0x61);
  let read=0,maxRead=0;
  const makeFile=(content)=>({
    size:content.length,name:"film.mkv",lastModified:123,
    slice(start,end){
      const span=content.subarray(start,end);
      read+=span.length;
      maxRead=Math.max(maxRead,span.length);
      return new Blob([span]);
    },
  });
  const file=makeFile(data);
  const v3=await firstChunkHash(file,8*1024*1024);
  if(read>3*64*1024||maxRead>64*1024||v3.length!==16)
    throw Error("v3 fingerprint exceeded main-thread read budget");
  const record={name:file.name,size:file.size,lastModified:123,
                chunkSize:8*1024*1024,hashVersion:3,hash:v3};
  if(!await matchesPendingFile(file,record))throw Error("v3 upload does not resume");
  const replaced=Buffer.from(data);
  replaced[4*1024*1024]=0x62;    // Preserve first 64 KiB and lastModified.
  const changed=makeFile(replaced);
  if(await matchesPendingFile(changed,record))
    throw Error("same-size file changed in the middle was accepted");
  replaced[4*1024*1024]=0x61;
  replaced[replaced.length-1]=0x62;
  if(await matchesPendingFile(changed,record))
    throw Error("same-size file changed at the end was accepted");
  const oldV2=await firstChunkHash(file,8*1024*1024,2);
  if(!await matchesPendingFile(file,{...record,hashVersion:2,hash:oldV2}))
    throw Error("v2 saved upload cannot resume");
  const small=makeFile(Buffer.alloc(2048,0x61));
  const oldV1=await firstChunkHash(small,2048,1);
  if(!await matchesPendingFile(small,{name:small.name,size:small.size,
      lastModified:123,chunkSize:2048,hash:oldV1}))
    throw Error("v1 saved upload cannot resume");
  if(await matchesPendingFile(file,{...record,hash:"deadbeef"}))
    throw Error("wrong fingerprint accepted");
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
