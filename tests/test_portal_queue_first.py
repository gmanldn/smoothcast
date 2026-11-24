"""Queue-first portal layout and truthful target/link state (headless)."""
from html.parser import HTMLParser
import shutil
import subprocess

import pytest
import portal


class Layout(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids
            self.ids[attrs["id"]] = attrs


def test_queue_is_first_and_links_remain_discoverable():
    html = portal._HTML
    page = Layout()
    page.feed(html)
    ids = list(page.ids)
    assert ids.index("queuePanel") < ids.index("playback")
    assert ids.index("queuePanel") < ids.index("findPanel")
    assert ids.index("queue") < ids.index("linkAcquisition")
    assert page.ids["queueHeading"]["tabindex"] == "-1"
    assert "disabled" not in page.ids["linkInput"]
    assert "disabled" in page.ids["linkSubmit"]
    assert "#queuePanel{grid-column:1/-1}" in html


def test_destination_and_link_controls_without_receiver_or_provider():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for headless browser checks")
    html = portal._HTML
    target = html[html.index("function renderQueueDestination("):
                  html.index("function applyStatus(")]
    links = html[html.index("function updateLinkControls("):
                 html.index("function renderLinkJobs(")]
    harness = """
const assert=require("node:assert/strict");
const elements={linkInput:{value:"magnet:?xt=urn:btih:example"},
  linkAuthorised:{checked:true},meshNavLink:{hidden:true}};
const $=id=>elements[id] ||= {};
let linkCapabilities={},linkStorageAvailable=null,linkPosting=false,
    youtubeSearchBusy=false;
"""
    checks = """
renderQueueDestination({});
assert.equal($("queueTarget").textContent,"No casting target selected");
assert.equal($("queueNowPlaying").textContent,"Playback state unavailable");
renderQueueDestination({receiver:"Lounge TV",state_label:"Idle",title:"Old",active:false});
assert.equal($("queueTarget").textContent,"Lounge TV");
assert.equal($("queueNowPlaying").textContent,"Idle");
renderQueueDestination({receiver:"Lounge TV",state_label:"Playing",title:"Film",active:true});
assert.equal($("queueNowPlaying").textContent,"Playing · Film");
updateLinkControls();
assert.equal($("linkInput").disabled,false);
assert.equal($("linkSubmit").disabled,true);
linkCapabilities={magnet:true};
updateLinkControls();
assert.equal($("linkSubmit").disabled,false);
linkPosting=true;
updateLinkControls();
assert.equal($("linkInput").disabled,true);
assert.equal($("linkSubmit").disabled,true);
"""
    subprocess.run(["node", "-"], input=harness + target + links + checks,
                   text=True, check=True, timeout=10)
