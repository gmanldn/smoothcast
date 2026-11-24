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
                 "pauseUpload", "cancelUpload", "uploadProgress", "queueFeedback"):
        assert name in page.ids
    assert page.ids["queueFeedback"]["aria-live"] == "polite"
    assert page.ids["uploadProgress"]["aria-label"] == "File transfer bytes received"
    assert portal._HTML.count('data-stage="') == 5
    assert "Cross-node routing will appear only when" in portal._HTML
    assert 'if(pauseRequested)throw Error("Transfer paused")' in portal._HTML
    assert 'state=await uploadRequest("GET","/api/uploads/"+pendingUpload.id)' in portal._HTML
    assert 'body.queue_revision=queueRevision' in portal._HTML
    assert 'body.queue_command_id=' in portal._HTML
    assert "Queue action was not applied:" in portal._HTML
    assert "Playback requested; receiver confirmation is separate." in portal._HTML


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
assert.equal(el.transferDestination.textContent,"Room receiver (pending)");
transferView("deliver",10485760,10485760);
assert(steps[4].classList.contains("active"));
transferView("transfer",10485761,10485760);
assert.equal(el.uploadProgress.value,0,"invalid byte count must never be displayed");
"""
    subprocess.run(["node", "-"], input=harness+helper+checks,
                   check=True, timeout=10, text=True)
