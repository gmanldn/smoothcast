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
linkPosting=true;
assert.equal(updateLinkControls(),false);
assert.equal($("linkInput").disabled,true);
"""
    subprocess.run(["node", "-"], input=harness + controls + checks,
                   text=True, check=True, timeout=10)


def test_submit_reuses_readiness_and_job_displays_source():
    assert "event.preventDefault();if(!updateLinkControls())return;" in portal._HTML
    assert 'job.kind==="youtube"?"YouTube"' in portal._HTML
