"""Read-only target inventory must expose conflicting receiver observations."""
import shutil
import subprocess

import pytest
from portal_mesh_panel import panel_html


def test_targets_precede_host_diagnostics():
    page = panel_html()
    assert page.index('id="meshReceiverInventory"') < page.index('id="meshRoomHeading"')
    assert page.count('id="meshTargets"') == 1
    assert 'queueLink.href="#meshReceiverInventory"' in page


@pytest.mark.skipif(shutil.which("node") is None, reason="requires Node.js")
def test_busy_observation_is_not_masked_by_ready_and_names_are_not_ids():
    script = panel_html().split("<script>", 1)[1].split("</script>", 1)[0]
    model = script[script.index("  function model(){"):script.index("  function sync(")]
    harness = """
const assert=require("node:assert/strict");
const TEXT={ready:"Reported ready",busy:"Reported in use",stale:"Not seen lately",unreachable:"Can't be reached"};
const RANK={ready:0,busy:1,stale:2,unreachable:3};
const plural=(n,w)=>n+" "+w+(n===1?"":"s");
const semver=()=>null,versionCompare=()=>0;
const local="a",primary="a",nodes=new Map();
const target=(id,state,owner="")=>({id,name:"TV",kind:"cast",state,owner});
nodes.set("a",{node_id:"a",name:"Lounge PC",targets:[target("tv1","ready"),target("tv2","ready")]});
nodes.set("b",{node_id:"b",name:"Study PC",targets:[target("tv1","busy","b")]});
"""
    checks = """
const rows=model().trows;
assert.equal(rows.length,2);
const conflicted=rows.find(row=>row.key==="t:tv1");
assert.equal(conflicted.state,"busy");
assert(conflicted.why.includes("Study PC"));
assert(conflicted.why.includes("Conflicting ready and busy"));
assert(conflicted.sub.includes("Lounge PC (Reported ready)"));
assert(conflicted.sub.includes("Study PC (Reported in use)"));
assert.equal(rows.find(row=>row.key==="t:tv2").state,"ready");
nodes.delete("b");
assert.equal(model().trows.find(row=>row.key==="t:tv1").state,"ready");
"""
    result = subprocess.run(["node", "-"], input=harness + model + checks,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
