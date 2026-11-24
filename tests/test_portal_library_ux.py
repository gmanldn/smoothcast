"""Shared library browser contract: stale searches and premature queue confirmation."""
import shutil
import subprocess

import pytest
import portal


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_obsolete_search_cannot_replace_new_results_or_close_new_stream():
    html = portal._HTML
    code = html[html.index("  function stop(){searchGeneration"):
                html.index('  let kind="",availableOnly=false;')]
    harness = """
const assert=require("node:assert/strict");
let timer=null,source=null,controller=null,searchGeneration=0,csrf="session",kind="";
const input={value:"old"},out={replaceChildren(){}},status={};
const streams=[],rendered=[];
function render(data){rendered.push(data)}
class EventSource{
  constructor(url){this.url=url;this.events={};streams.push(this)}
  addEventListener(name,fn){this.events[name]=fn}
  close(){this.closed=true}
}
function clearTimeout(){}
"""
    checks = """
run();
const first=streams[0];
input.value="new";run();
const second=streams[1];
assert.equal(first.closed,true);
first.events.results({data:'{"old":true}'});
first.events.done();
assert.equal(second.closed,undefined);
second.events.results({data:'{"new":true}'});
assert.equal(rendered.length,1);
assert.equal(rendered[0].new,true);
csrf="next session";
second.events.more({data:'{"stale":true}'});
assert.equal(rendered.length,1);
"""
    subprocess.run(["node", "-"], input=harness + code + checks,
                   text=True, check=True, timeout=10)


def test_library_feedback_distinguishes_copy_from_accepted_queue():
    page = portal._HTML
    assert 'id="libRefresh"' in page
    assert 'id="libStatus"' in page
    assert 'add.textContent=d.message==="Added to the queue."?"Added":"Requested"' in page
    assert "if(cursor&&libraryBusy)return;" in page
    assert "generation===libraryGeneration&&csrf===session" in page
