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
    assert "hashVersion:2,hash:await firstChunkHash(file,chunkSize)" in SOURCE
    assert "upload.hashVersion!==2" in js
    assert "Math.min(file.size,legacy?chunkSize:UPLOAD_FINGERPRINT_BYTES)" in js
    assert "offset+=16*1024" in js
    assert "await new Promise(resolve=>setTimeout(resolve,0))" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_real_portal_javascript_hashes_only_64k_and_resumes_legacy_records():
    js = _js() + r"""
(async()=>{
  const sample=Buffer.alloc(8*1024*1024,0x61);
  let maxRead=0;
  const file={
    size:sample.length,name:"film.mkv",lastModified:123,
    slice(start,end){
      const length=Math.min(end===undefined?sample.length:end,sample.length)-start;
      maxRead=Math.max(maxRead,length);
      return new Blob([sample.subarray(start,start+length)]);
    },
  };
  const newHash=await firstChunkHash(file,8*1024*1024);
  if(maxRead!==64*1024||newHash.length!==16)throw Error("new fingerprint exceeds budget");
  if(await firstChunkHash({...file,size:64*1024},8*1024*1024)!==newHash)
    throw Error("new hash depends on entire transfer chunk");
  if(!await matchesPendingFile(file,{
    name:file.name,size:file.size,lastModified:123,chunkSize:8*1024*1024,
    hashVersion:2,hash:newHash
  }))throw Error("new upload cannot resume");
  const oldFile={...file,size:2048};
  const oldHash=await firstChunkHash(oldFile,2048,true);
  if(!await matchesPendingFile(oldFile,{
    name:file.name,size:2048,lastModified:123,chunkSize:2048,hash:oldHash
  }))throw Error("old upload cannot resume");
  if(await matchesPendingFile(file,{
    name:file.name,size:file.size,lastModified:123,chunkSize:8*1024*1024,
    hashVersion:2,hash:"deadbeef"
  }))throw Error("mismatched upload accepted");
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", js], capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
