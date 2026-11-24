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
