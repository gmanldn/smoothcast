"""Guest diagnostics distinguish missing local prerequisites from mesh availability."""
import shutil
import subprocess

import pytest
import portal


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_link_prerequisites_explain_unavailable_worker_without_blocking_remote():
    page = portal._HTML
    controls = page[page.index("function updateLinkControls("):
                    page.index("function renderLinkJobs(")]
    harness = """
const assert=require("node:assert/strict");
const elements={linkInput:{value:"https://youtu.be/dQw4w9WgXcQ"},linkAuthorised:{checked:true}};const $=id=>elements[id]||= {};let linkCapabilities={},linkOwnerEnabled={youtube:true,magnet:true},linkLocalPrerequisites={youtube:{engine:false,probe:true,isolation:false},magnet:{engine:false,probe:false,isolation:true}},linkStorageAvailable=null,linkPosting=false,youtubeSearchBusy=false;
"""
    checks = """
assert.equal(updateLinkControls(),false);assert($("linkAvailability").textContent.includes("yt-dlp, isolated worker launcher"));linkCapabilities.youtube=true;assert.equal(updateLinkControls(),true);assert(!$("linkAvailability").textContent.includes("missing"));linkOwnerEnabled.youtube=false;linkCapabilities.youtube=false;updateLinkControls();assert($("linkAvailability").textContent.includes("enable guest downloads"));$("linkInput").value="magnet:?xt=urn:btih:"+"a".repeat(40);updateLinkControls();assert($("linkAvailability").textContent.includes("aria2c, FFprobe"));linkStorageAvailable=false;updateLinkControls();assert($("linkAvailability").textContent.includes("storage"));
"""
    subprocess.run(["node", "-"], input=harness + controls + checks,
                   text=True, check=True, timeout=10)
