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
    assert '<a id="roomRenameLink" href="#roomNameForm" hidden>Rename</a>' in html
    assert 'id="roomNameForm" hidden' in html and 'id="roomNameInput" maxlength="40"' in html
    assert 'id="homeChooseScreen"' in html
    assert 'class="primary-action"' in html and "Choose a file to cast" in html
    assert "No screen selected. Choose one before casting, or add your file to Up Next instead." in html
    assert 'class="settings-scope-list"' in html
    for scope in ("Your profile", "This browser", "Everyone in this room", "Room host only"):
        assert scope in html
    assert "managed on the computer running SmoothCast" in html
    for host_only in ("House PIN", "Library folders"):
        assert host_only in html


def test_room_heading_and_rename_controls_follow_host_permission():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for headless browser checks")
    html = portal._HTML
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    identity = script[script.index("function renderRoomIdentity(room){"):
                      script.index("function renderRoom(room){")]
    harness = r"""
const assert=require("node:assert/strict");
const elements={roomRenameLink:{hidden:true},roomNameForm:{hidden:true},roomNameInput:{value:""},
  homeHeading:{textContent:"Your room"},joinTitle:{textContent:"Join the house"}};
const document={activeElement:null};
const $=id=>elements[id];
"""
    scenario = r"""
renderRoomIdentity({name:"Lounge",can_rename:true});
assert.equal(elements.homeHeading.textContent,"Lounge");
assert.equal(elements.joinTitle.textContent,"Join Lounge");
assert.equal(elements.roomRenameLink.hidden,false);
assert.equal(elements.roomNameForm.hidden,false);
assert.equal(elements.roomNameInput.value,"Lounge");
renderRoomIdentity({name:"Studio",can_rename:false});
assert.equal(elements.homeHeading.textContent,"Studio");
assert.equal(elements.roomRenameLink.hidden,true);
assert.equal(elements.roomNameForm.hidden,true);
"""
    subprocess.run(["node", "-"], input=harness + identity + scenario,
                   text=True, check=True, timeout=10)


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
  linkAuthorised:{checked:true},meshNavLink:{hidden:true},meshDetails:{hidden:true}};
const $=id=>elements[id] ||= {};
let linkCapabilities={},linkStorageAvailable=null,linkPosting=false,
    youtubeSearchBusy=false;
"""
    checks = """
renderQueueDestination({});
assert.equal($("quickCastStatus").textContent,"No screen selected. Choose one before casting, or add your file to Up Next instead.");
assert.equal($("liveRoomTarget").textContent,"No casting target selected");
assert.equal($("liveRoomPlayback").textContent,"Playback state unavailable");
renderQueueDestination({receiver:"Lounge TV",state_label:"Idle",title:"Old",active:false});
assert.equal($("quickCastStatus").textContent,"Selected screen: Lounge TV. SmoothCast checks availability before sending any file.");
assert.equal($("liveRoomTarget").textContent,"Lounge TV");
assert.equal($("liveRoomPlayback").textContent,"Idle");
renderQueueDestination({receiver:"Lounge TV",state_label:"Playing",title:"Film",active:true});
assert.equal($("liveRoomPlayback").textContent,"Playing · Film");
renderQueueDestination({receiver:"Lounge TV",state_label:"State unavailable",cast_feedback:{receiver:"Lounge TV",state:"failed",message:"Receiver did not return status."}});
assert.equal($("liveRoomPlayback").textContent,"Cast failed: Receiver did not return status.");
renderQueueDestination({receiver:"Bedroom TV",state_label:"Idle",cast_feedback:{receiver:"Lounge TV",state:"failed",message:"Old failure"}});
assert.equal($("liveRoomPlayback").textContent,"Idle");
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
    for blade in ("homePanel", "peoplePanel", "screensPanel", "meshPanel",
                  "findPanel", "advancedPanel"):
        assert (f'#dashboard[data-room-blade="{blade}"]>:not(nav):not(#errorDash):not(#{blade})'
                in html), blade
    assert ('#dashboard:not([data-room-blade])>:not(nav):not(#errorDash):not(#homePanel)'
            '{display:none}') in html
    assert ('#dashboard[data-room-blade]>#findPanel,#dashboard[data-room-blade]>#advancedPanel'
            '{grid-column:1/-1}') in html
    assert ('#dashboard[data-room-blade]>#homePanel,#dashboard[data-room-blade]>#peoplePanel,'
            '#dashboard[data-room-blade]>#screensPanel,#dashboard[data-room-blade]>#meshPanel'
            '{grid-column:1/-1}') in html
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
const make=id=>({id,attrs:{},scrolls:0,focuses:0,parent:null,closest(){return null},
  contains(x){return x===this||x?.parent===this},scrollIntoView(){this.scrolls++},
  focus(){this.focuses++;document.activeElement=this},setAttribute(k,v){this.attrs[k]=v},
  removeAttribute(k){delete this.attrs[k]},getAttribute(k){return this.attrs[k]??null}});
const panels=["homePanel","findPanel","peoplePanel","screensPanel","meshPanel","advancedPanel"];
const elements={};
for(const id of [...panels,"queuePanel","playback","localLivePanel","uploadCard","findInput"])elements[id]=make(id);
for(const id of panels)elements[id].closest=()=>elements[id];
elements.findInput.parent=elements.findPanel;elements.findInput.closest=()=>elements.findPanel;
for(const [head,parent] of Object.entries({queueHeading:"queuePanel",uploadHeading:"uploadCard",
  playbackHeading:"playback",homeHeading:"homePanel",findHeading:"findPanel",peopleHeading:"peoplePanel",
  screensPanelHeading:"screensPanel",meshTitle:"meshPanel",roomSettingsHeading:"advancedPanel",
  localLiveHeading:"localLivePanel"})){elements[head]=make(head);elements[head].parent=elements[parent];}
const links=panels.map(id=>{const a=make(id);a.attrs.href="#"+id;return a});
const dash=make("dashboard");dash.hidden=false;
dash.contains=x=>Object.values(elements).includes(x);dash.querySelectorAll=()=>links;
const $=id=>elements[id]||null;
const check=(ok,msg)=>{if(!ok)throw Error(msg)};
const current=()=>links.filter(a=>a.getAttribute("aria-current")==="page").map(a=>a.id).join(",");
"""
    checks = r"""
syncRoomBlade();
check(!dash.getAttribute("data-room-blade"),"no blade at rest");
check(current()==="homePanel","home link is current when no blade is selected");
location.hash="#findPanel";syncRoomBlade(true);
check(dash.getAttribute("data-room-blade")==="findPanel"&&current()==="findPanel"
  &&elements.findHeading.focuses===1,"find blade");
location.hash="#advancedPanel";syncRoomBlade(true);
check(dash.getAttribute("data-room-blade")==="advancedPanel"&&current()==="advancedPanel"
  &&elements.roomSettingsHeading.focuses===1,"settings blade");
location.hash="#queuePanel";syncRoomBlade(true);
check(!dash.getAttribute("data-room-blade")&&elements.queuePanel.scrolls===1
  &&elements.queueHeading.focuses===1,"queue scrolls and focuses its heading");
location.hash="#playback";syncRoomBlade(true);
check(!dash.getAttribute("data-room-blade")&&elements.playback.scrolls===0
  &&elements.playbackHeading.focuses===0,
  "playback from the overview does not move focus (no blade selected yet)");
document.activeElement=elements.findInput;location.hash="#findInput";syncRoomBlade(true);
check(dash.getAttribute("data-room-blade")==="findPanel"&&elements.findInput.scrolls===1
  &&elements.findHeading.focuses===1,"a deep link keeps the focused input");
location.hash="#localLivePanel";syncRoomBlade(true);
check(!dash.getAttribute("data-room-blade"),"the live panel lives inside the mesh blade");
location.hash="#homePanel";dash.hidden=true;syncRoomBlade(true);
check(elements.homeHeading.focuses===0,"a signed-out page does not steal focus");
dash.hidden=false;syncRoomBlade(true);
check(elements.homeHeading.focuses===1,"focus returns after joining");
location.hash="";syncRoomBlade(true);
check(!dash.getAttribute("data-room-blade")&&current()==="homePanel","home clears the blade");
"""
    subprocess.run(["node", "-"], input=harness + router + checks,
                   text=True, check=True, timeout=10)
