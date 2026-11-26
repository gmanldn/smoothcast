"""Ticket 624: the concise Home landing pane and its navigation.

The room dashboard now opens on a single Home pane that summarises the selected
device, the shared queue and who is in the room, and offers the four workflow
actions (upload/transfer, YouTube link, magnet link, find). These are pure
source/DOM checks: no GUI, network or receiver is touched.
"""
from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser

import pytest
import portal


class _Home(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.ids: list[str] = []
        self.parent: dict[str, str] = {}
        self.tags: dict[str, str] = {}
        self.anchors: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
            self.tags[a["id"]] = tag
            self.parent[a["id"]] = self.stack[-1][1].get("id", "") if self.stack else ""
        if tag == "a":
            self.anchors.append(a)
        void = {"meta", "link", "input", "img", "br", "hr", "source", "path"}
        if tag not in void:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _page():
    parser = _Home()
    parser.feed(portal._page().decode("utf-8"))
    return parser


def test_home_is_the_default_dashboard_pane_with_unique_ids():
    page = _page()
    assert len(page.ids) == len(set(page.ids)), "duplicate ids break DOM binding"
    assert page.tags["homePanel"] == "section"
    assert page.parent["homePanel"] == "dashboard"
    assert page.parent["playback"] == "dashboard"
    assert page.tags["homeHeading"] == "h2"
    assert '<a href="#playback">Now Playing</a>' in portal._HTML
    assert 'id="homeHeading" tabindex="-1"' in portal._HTML


def test_home_pane_has_a_nav_entry_and_the_four_workflow_actions():
    page = _page()
    assert any(a.get("href") == "#homePanel" for a in page.anchors), "Home is in the section nav"
    html = portal._HTML
    for action_id in ("homeUpload", "homeYoutube", "homeMagnet", "homeFind"):
        assert f'id="{action_id}"' in html
    assert html.count('class="home-action"') == 4
    # Every action carries a native tooltip explaining the workflow step.
    segment = html[html.index('class="home-actions"'):html.index("</div>\n<div class=\"home-grid\">")]
    assert segment.count("title=") == 4


def test_home_pane_surfaces_device_queue_and_people():
    page = _page()
    for element in ("homeTarget", "homeNowPlaying", "homeQueue", "homeQueueCount", "homePeople"):
        assert element in page.ids, f"home pane must show {element}"
    # The dedicated panes keep their own ids.
    for element in ("queueTarget", "queue", "people", "playback"):
        assert element in page.ids


def test_home_embeds_the_cast_entry_and_drops_the_old_welcome_block():
    page = _page()
    assert page.parent["castEntry"] == "homePanel"
    assert 'class="welcome"' not in portal._HTML


def test_default_view_is_home_and_every_panel_is_a_blade():
    html = portal._HTML
    assert ("#dashboard:not([data-room-blade])>:not(nav):not(#errorDash)"
            ":not(#homePanel){display:none}") in html
    for panel in ("homePanel", "queuePanel", "uploadCard", "peoplePanel",
                  "screensPanel", "meshPanel", "findPanel",
                  "advancedPanel", "localLivePanel"):
        assert f'#dashboard[data-room-blade="{panel}"]' in html
    assert ("#dashboard[data-room-blade]>#homePanel,#dashboard[data-room-blade]>#queuePanel"
            ",#dashboard[data-room-blade]>#uploadCard,#dashboard[data-room-blade]>#peoplePanel"
            ",#dashboard[data-room-blade]>#screensPanel,#dashboard[data-room-blade]>#meshPanel"
            "{grid-column:1/-1}") in html


def test_home_rendering_hooks_wire_the_shared_snapshot():
    html = portal._HTML
    assert "function renderHomeQueue(items){" in html
    assert "function renderHomePeople(room){" in html
    assert "renderHomeQueue(s.queue);" in html
    assert "renderHomePeople(room);" in html
    assert "homeQueueKey" in html and "homePeopleKey" in html


def test_sync_home_blades_and_clears_back_to_home():
    if not shutil.which("node"):
        pytest.skip("Node.js needed for blade navigation checks")
    html = portal._HTML
    router = html[html.index("  function syncRoomBlade("):
                  html.index('  window.addEventListener("hashchange",()=>syncRoomBlade(true));')]
    harness = r"""
const location={hash:""},document={activeElement:null};
const make=(id,blade=null)=>({id,attrs:{},scrolls:0,focuses:0,closest(){return blade||null},contains(x){return x===this||x?.parent===this},scrollIntoView(){this.scrolls++},focus(){this.focuses++;document.activeElement=this},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},getAttribute(k){return this.attrs[k]??null}});
const home=make("homePanel"),queue=make("queuePanel"),upload=make("uploadCard"),people=make("peoplePanel"),mesh=make("meshPanel"),find=make("findPanel");
home.closest=()=>home;queue.closest=()=>queue;upload.closest=()=>upload;people.closest=()=>people;mesh.closest=()=>mesh;find.closest=()=>find;
const playback=make("playback");playback.closest=()=>playback;playback.parent=home;
const homeHeading=make("homeHeading");homeHeading.parent=home;
const elements={homePanel:home,playback,queuePanel:queue,uploadCard:upload,peoplePanel:people,meshPanel:mesh,findPanel:find,homeHeading};
const $=id=>elements[id]||null;
const links=["homePanel","queuePanel","uploadCard","peoplePanel","meshPanel","findPanel"].map(id=>{const a=make(id);a.attrs.href="#"+id;return a});
const dash=make("dashboard");dash.hidden=false;dash.contains=x=>Object.values(elements).includes(x);dash.querySelectorAll=()=>links;
const check=(ok,msg)=>{if(!ok)throw Error(msg)};
"""
    checks = r"""
syncRoomBlade();check(!dash.getAttribute("data-room-blade"),"default shows home via overview");
for(const id of ["homePanel","queuePanel","uploadCard","peoplePanel","meshPanel","findPanel"]){
  location.hash="#"+id;syncRoomBlade(true);
  check(dash.getAttribute("data-room-blade")===id,"blade "+id);
}
location.hash="#playback";syncRoomBlade(true);check(dash.getAttribute("data-room-blade")==="playback","playback blade opens Now Playing");
location.hash="";syncRoomBlade();check(!dash.getAttribute("data-room-blade"),"home clears the blade");
check(links[0].getAttribute("aria-current")==="page","Home selected by default");
"""
    subprocess.run(["node", "-"], input=harness + router + checks,
                   text=True, check=True, timeout=10)
