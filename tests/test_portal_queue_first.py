"""Portal room layout and truthful target/link state (headless)."""
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
    # Home pane leads (now playing), then Up Next, then Find (#324).
    assert ids.index("homePanel") < ids.index("playback") < ids.index("queuePanel")
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
    target = html[html.index("function playbackFeedback("):
                  html.index("function applyStatus(")]
    links = html[html.index("function updateLinkControls("):
                 html.index("function renderLinkJobs(")]
    harness = """
const assert=require("node:assert/strict");
const elements={linkInput:{value:"magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"},
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
renderQueueDestination({receiver:"Lounge TV",state_label:"State unavailable",cast_feedback:{receiver:"Lounge TV",state:"failed",message:"Receiver did not return status."}});
assert.equal($("queueNowPlaying").textContent,"Cast failed: Receiver did not return status.");
renderQueueDestination({receiver:"Bedroom TV",state_label:"Idle",cast_feedback:{receiver:"Lounge TV",state:"failed",message:"Old failure"}});
assert.equal($("queueNowPlaying").textContent,"Idle");
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


def test_find_and_now_playing_have_exclusive_full_width_blades():
    html = portal._HTML
    assert '#dashboard[data-room-blade="playback"]>:not(nav):not(#errorDash):not(#playback)' in html
    assert '#dashboard[data-room-blade="findPanel"]>:not(nav):not(#errorDash):not(#findPanel)' in html
    assert '#dashboard[data-room-blade="advancedPanel"]>:not(nav):not(#errorDash):not(#advancedPanel)' in html
    assert '#dashboard[data-room-blade="localLivePanel"]>:not(nav):not(#errorDash):not(#localLivePanel){display:none}' in html
    assert '#dashboard[data-room-blade]>#playback,#dashboard[data-room-blade]>#findPanel,#dashboard[data-room-blade]>#advancedPanel,#dashboard[data-room-blade]>#localLivePanel{grid-column:1/-1}' in html
    assert 'id="findHeading" tabindex="-1"' in html
    assert 'id="roomSettingsHeading" tabindex="-1"' in html
    assert 'id="localLiveHeading" tabindex="-1"' in html
    assert 'syncRoomBlade();\n    window.scrollTo' in html
    if not shutil.which("node"):
        pytest.skip("Node.js needed for blade navigation checks")
    router = html[html.index("  function syncRoomBlade("):
                  html.index('  window.addEventListener("hashchange",()=>syncRoomBlade(true));')]
    harness = r"""
const location={hash:""},document={activeElement:null};
const make=(id,blade=null)=>({id,attrs:{},scrolls:0,focuses:0,closest(){return blade||null},contains(x){return x===this||x?.parent===this},scrollIntoView(){this.scrolls++},focus(){this.focuses++;document.activeElement=this},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},getAttribute(k){return this.attrs[k]??null}});
const playback=make("playback"),find=make("findPanel"),queue=make("queuePanel"),settings=make("advancedPanel"),live=make("localLivePanel"),input=make("findInput",find),findHeading=make("findHeading"),playbackHeading=make("playbackHeading"),settingsHeading=make("roomSettingsHeading"),liveHeading=make("localLiveHeading");
playback.closest=()=>playback;find.closest=()=>find;settings.closest=()=>settings;live.closest=()=>live;input.parent=find;findHeading.parent=find;playbackHeading.parent=playback;settingsHeading.parent=settings;liveHeading.parent=live;
const elements={playback,findPanel:find,queuePanel:queue,advancedPanel:settings,localLivePanel:live,findInput:input,findHeading,playbackHeading,roomSettingsHeading:settingsHeading,localLiveHeading:liveHeading};
const $=id=>elements[id]||null;
const links=["playback","findPanel","queuePanel","advancedPanel","localLivePanel"].map(id=>{const a=make(id);a.attrs.href="#"+id;return a});
const dash=make("dashboard");dash.hidden=false;dash.contains=x=>Object.values(elements).includes(x);dash.querySelectorAll=()=>links;
const check=(ok,msg)=>{if(!ok)throw Error(msg)};
"""
    checks = r"""
syncRoomBlade();check(!dash.getAttribute("data-room-blade"),"overview");
location.hash="#findPanel";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="findPanel"&&links[1].getAttribute("aria-current")==="page"&&findHeading.focuses===1,"find");
location.hash="#playback";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="playback"&&!links[1].getAttribute("aria-current")&&links[0].getAttribute("aria-current")==="page"&&playbackHeading.focuses===1,"playback");
location.hash="#advancedPanel";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="advancedPanel"&&links[3].getAttribute("aria-current")==="page"&&settingsHeading.focuses===1,"settings");
location.hash="#localLivePanel";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="localLivePanel"&&links[4].getAttribute("aria-current")==="page"&&liveHeading.focuses===1,"live");
location.hash="#findPanel";document.activeElement=input;syncRoomBlade(true);check(findHeading.focuses===1,"preserve focused search input");
location.hash="#findInput";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="findPanel"&&input.scrolls===1,"nested deep link");
location.hash="#queuePanel";syncRoomBlade(true);check(!dash.getAttribute("data-room-blade")&&queue.scrolls===1,"leave blade");
location.hash="#playback";dash.hidden=true;syncRoomBlade(true);check(playbackHeading.focuses===1,"no focus while signed out");
dash.hidden=false;syncRoomBlade(true);check(playbackHeading.focuses===2,"restore after join");
location.hash="";syncRoomBlade();check(!dash.getAttribute("data-room-blade")&&!links[0].getAttribute("aria-current"),"home clears view");
"""
    subprocess.run(["node", "-"], input=harness + router + checks,
                   text=True, check=True, timeout=10)
