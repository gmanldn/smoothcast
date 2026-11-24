"""Browser link readiness is source-specific; server still validates links."""
import shutil
import subprocess

import pytest
import portal


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_link_input_availability_is_source_specific():
    html = portal._HTML
    controls = html[html.index("function updateLinkControls("):
                    html.index("function renderLinkJobs(")]
    harness = """
const assert=require("node:assert/strict");
const elements={linkInput:{value:""},linkAuthorised:{checked:true}};
const $=id=>elements[id] ||= {};
let linkCapabilities={youtube:true,magnet:false},linkStorageAvailable=null,linkPosting=false,youtubeSearchBusy=false;
"""
    checks = """
$("linkInput").value="magnet:?xt=urn:btih:"+"a".repeat(40);
assert.equal(updateLinkControls(),false);
assert.equal($("linkInput").disabled,false);
assert($("linkAvailability").textContent.includes("BitTorrent magnets unavailable"));
linkCapabilities={youtube:false,magnet:true};
assert.equal(updateLinkControls(),true);
$("linkInput").value="https://youtu.be/dQw4w9WgXcQ";
assert.equal(updateLinkControls(),false);
assert($("linkAvailability").textContent.includes("YouTube unavailable"));
linkCapabilities.youtube=true;
assert.equal(updateLinkControls(),true);
$("linkInput").value="https://youtube.com.example.org/watch?v=dQw4w9WgXcQ";
assert.equal(updateLinkControls(),false);
$("linkInput").value="https://www.youtube.com/watch?v=dQw4w9WgXcQ";
linkStorageAvailable=false;
assert.equal(updateLinkControls(),false);
linkStorageAvailable=true;
$("linkAuthorised").checked=false;
assert.equal(updateLinkControls(),false);
$("linkAuthorised").checked=true;
for(const [value,expected,hint] of [
  ["https://www.youtube.com/playlist?list=abc",false,"Share link"],
  ["https://youtube.com/watch?v=short",false,"Share link"],
  ["https://youtube.com/watch?v=dQw4w9WgXcQ&v=abcdefghijk",false,"Share link"],
  ["https://youtu.be/dQw4w9WgXcQ?t=42",true,"recognised"],
  ["https://www.youtube.com/shorts/dQw4w9WgXcQ",true,"recognised"],
  ["https://youtube.com:443/watch?v=dQw4w9WgXcQ",true,"recognised"],
  ["magnet:?xt=urn%3Abtih%3A"+"a".repeat(40),true,"recognised"],
  ["magnet:?xt=urn:btih:bad",false,"incomplete"],
  ["https://example.org/video.mp4",false,"not supported"],
  ["http://youtu.be/dQw4w9WgXcQ",false,"HTTPS"],
  ["youtu.be/dQw4w9WgXcQ",false,"complete"],
  ["some movie",false,"Find"],
  ["https://user@youtube.com/watch?v=dQw4w9WgXcQ",false,"not supported"]
]){
  $("linkInput").value=value;
  assert.equal(updateLinkControls(),expected,value);
  assert($("linkAvailability").textContent.includes(hint),value);
}
$("linkInput").value="https://youtu.be/dQw4w9WgXcQ";
linkPosting=true;
assert.equal(updateLinkControls(),false);
assert.equal($("linkInput").disabled,true);
"""
    subprocess.run(["node", "-"], input=harness + controls + checks,
                   text=True, check=True, timeout=10)


def test_submit_reuses_readiness_and_job_displays_source():
    assert "event.preventDefault();if(!updateLinkControls())return;" in portal._HTML
    assert 'job.kind==="youtube"?"YouTube"' in portal._HTML
