"""Guest-first portal UI semantics; pure source checks, no GUI or receiver."""
from __future__ import annotations

from html.parser import HTMLParser

import portal


class RoomHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.ids = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.elements.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#"):
            self.anchors.append(a["href"][1:])


def room_html():
    parser = RoomHTML()
    parser.feed(portal._page().decode("utf-8"))
    return parser


def test_guest_navigation_has_unique_ids_and_real_targets():
    page = room_html()
    assert len(page.ids) == len(set(page.ids)), "Duplicate IDs break DOM event binding"
    assert set(page.anchors) <= set(page.ids)
    assert {"playback", "findPanel", "uploadCard", "queuePanel", "peoplePanel",
            "advancedPanel", "screensPanel"} <= set(page.anchors)


def test_join_explains_shared_controls_and_optional_house_pin():
    page = room_html()
    text = portal._HTML
    assert 'id="joinTitle">Join the house' in text
    assert "You only need a House PIN if one has been set" in text
    assert "Everyone who joins can control playback" in text
    assert "No app, account or cloud" in text
    fields = {a["id"]: a for tag, a in page.elements if tag == "input" and "id" in a}
    assert fields["name"]["aria-describedby"] == "nameHint"
    assert fields["pin"]["aria-describedby"] == "pinHint"
    assert fields["pin"]["pattern"] == "[0-9]{6}"


def test_room_actions_have_touch_help_and_keep_existing_js_contract():
    page = room_html()
    text = portal._HTML
    assert text.count('class="help"') >= 6
    assert text.count("<summary>") >= 5
    assert "audio always goes into up next" in text.lower()
    assert "without stopping the currently playing item" in text
    assert 'id="uploadQueue" type="checkbox" checked' in text
    assert 'id="seek" type="range"' in text
    assert 'id="volume" type="range"' in text
    assert 'button.title=labels[i]' in text
    actions = {a["data-action"] for tag, a in page.elements if "data-action" in a}
    assert {"play_pause", "stop", "previous", "next"} == actions
    for required in ("people", "peers", "networkActivityRows", "activity", "findChips",
                     "findResults", "queue", "uploadButton", "cancelUpload",
                     "shortcutsHelp", "musicAutogain", "lockControls", "keepScreenOn"):
        assert required in page.ids
    assert 'function applyStatus(d)' in text
    assert 'function expireSession()' in text


def test_advanced_settings_are_visible_with_native_help_disclosure():
    page = room_html()
    assert ("section", {"id": "advancedPanel", "aria-labelledby": "roomSettingsHeading"}) in [
        (tag, {k: v for k, v in attrs.items() if k in ("id", "aria-labelledby")})
        for tag, attrs in page.elements if tag == "section" and attrs.get("id") == "advancedPanel"
    ]
    assert not any(tag == "details" and attrs.get("id") == "advancedPanel"
                   for tag, attrs in page.elements)
    text = portal._HTML
    assert text.count('<details class="help"><summary>') >= 5
    assert "@media(min-width:820px)" in text
    assert "@media(max-width:560px)" in text
    assert "[hidden]{display:none!important}" in text
    assert "position:sticky" in text
    assert "prefers-reduced-motion:reduce" in text


def test_portal_stays_local_and_unprivileged():
    page = room_html()
    assert not any(tag == "script" and "src" in attrs for tag, attrs in page.elements)
    assert not any(tag == "link" and attrs.get("rel") in ("stylesheet", "preload")
                   for tag, attrs in page.elements)
    assert 'post("/api/login"' in portal._HTML
    assert 'credentials:"same-origin"' in portal._HTML
    assert '"X-CSRF-Token":csrf' in portal._HTML


def test_upload_picker_has_actionable_disabled_state():
    """No file selected must not offer a button that silently does nothing."""
    text = portal._HTML
    assert 'id="uploadSelectionHint"' in text
    assert 'aria-describedby="uploadSelectionHint" disabled' in text
    assert '$("uploadButton").disabled=uploading||!file||!!invalid;' in text


def test_upload_button_state_transitions_in_headless_browser_js():
    """Exercise the actual browser handler without a GUI, network or file reads."""
    import shutil
    import subprocess
    import pytest

    if not shutil.which("node"):
        pytest.skip("Node.js is required for this browser-control regression")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function updateUploadControls(){")
    end = script.index("function resetUploadBatch(){", start)
    controls = script[start:end]
    harness = r"""
const assert = require("node:assert/strict");
let uploading=false,pendingUpload=null,batchFiles=null,batchIndex=0,cancelUpload=false;
let shortcutState={receiver:"Living room TV"};
const el={
 uploadSelectionSummary:{},transferDestination:{},
 videoFile:{files:[],disabled:false,multiple:true},
 uploadQueue:{checked:true,disabled:false},
 uploadButton:{disabled:false,textContent:""},
 cancelUpload:{hidden:true,disabled:false}
};
const $=id=>el[id];
"""
    scenario = r"""
updateUploadControls();
assert.equal(el.uploadButton.disabled,true,"empty picker must disable upload");
el.videoFile.files=[{name:"video.mp4",size:100}];
updateUploadControls();
assert.equal(el.uploadButton.disabled,false);
assert.equal(el.uploadButton.textContent,"Upload and add");
el.uploadQueue.checked=false;
updateUploadControls();
assert.equal(el.uploadButton.textContent,"Upload and cast","video intent must be clear");
el.videoFile.files=[{name:"audio.mp3",size:100}];
updateUploadControls();
assert.equal(el.uploadQueue.checked,true,"audio always goes into Up Next");
assert.equal(el.uploadQueue.disabled,true);
assert.equal(el.uploadButton.textContent,"Upload and add");
el.videoFile.files=[{name:"audio.mp3",size:100},{name:"video.mp4",size:200}];
updateUploadControls();
assert.equal(el.uploadQueue.disabled,false,"mixed media must permit choosing video playback");
el.uploadQueue.checked=false;
updateUploadControls();
assert.equal(el.uploadButton.textContent,"Upload and cast");
batchFiles=el.videoFile.files;
batchIndex=0;
updateUploadControls();
assert.equal(el.uploadQueue.checked,false,"audio item must not overwrite batch intent");
batchFiles=null;
el.videoFile.files=[{name:"video.mp4",size:0}];
updateUploadControls();
assert.equal(el.uploadButton.disabled,true,"empty file must not start upload");
assert.ok(el.uploadSelectionSummary.textContent.includes("empty"));
el.videoFile.files=[{name:"video.mp4",size:100},{name:"notes.pdf",size:200}];
updateUploadControls();
assert.equal(el.uploadButton.disabled,true,"invalid batch must not partially start");
assert.ok(el.uploadSelectionSummary.textContent.includes("notes.pdf"));
el.videoFile.files=[{name:"movie.MKV",size:100}];
el.uploadQueue.checked=false;
updateUploadControls();
assert.equal(el.uploadButton.disabled,false);
assert.ok(el.uploadSelectionSummary.textContent.includes("Living room TV"));
assert.ok(el.uploadSelectionSummary.textContent.includes("movie.MKV"));
assert.equal(el.transferDestination.textContent,"Living room TV (requested)");
uploading=true;
updateUploadControls();
assert.equal(el.uploadButton.disabled,true,"in-flight upload cannot be started twice");
"""
    subprocess.run(["node", "-"], input=harness + controls + scenario,
                   check=True, text=True, timeout=10)


def test_open_room_login_hides_pin_before_session_request():
    """No transient PIN requirement should be shown to a first-time open-room guest."""
    import shutil
    import subprocess
    import pytest

    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function configureOpenJoin(){")
    end = script.index('$("loginForm").addEventListener("submit",', start)
    setup = script[start:end]
    assert "if(!PIN_REQUIRED)configureOpenJoin();" in setup
    assert start < script.index("restoreSession().then(")
    if not shutil.which("node"):
        pytest.skip("Node.js required for the PIN-free join browser regression")
    harness = r"""
const assert = require("node:assert/strict");
function simulate(pinRequired){
  const PIN_REQUIRED=pinRequired;
  const elements={
    pinRow:{hidden:false},pin:{required:true,value:""},
    loginHint:{textContent:"PIN needed"},loginButton:{textContent:"Join"}
  };
  const $=id=>elements[id],loginButton=elements.loginButton;
"""
    finish = r"""
  return elements;
}
const open=simulate(false),locked=simulate(true);
assert.equal(open.pinRow.hidden,true);
assert.equal(open.pin.required,false);
assert.equal(open.loginButton.textContent,"Join");
assert.equal(locked.pinRow.hidden,false);
assert.equal(locked.pin.required,true);
assert.equal(locked.loginButton.textContent,"Join");
"""
    subprocess.run(["node", "-"], input=harness + setup + finish,
                   check=True, text=True, timeout=10)


def test_room_share_link_never_copies_a_pin_and_recovers_without_clipboard():
    """The guest shares only the local origin, even if URL carries query data."""
    import shutil
    import subprocess
    import pytest

    markup = portal._HTML
    for fragment in ('id="roomLinkText"', 'id="roomLinkCopy"',
                     'id="roomLinkHint"', 'id="roomLinkStatus" role="status"'):
        assert fragment in markup
    script = markup.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index('const roomInviteLink=location.origin+"/";')
    end = script.index("async function post(", start)
    share = script[start:end]
    if not shutil.which("node"):
        pytest.skip("Node.js needed to test clipboard fallback")
    harness = r"""
const assert=require("node:assert/strict");
const location={origin:"http://192.168.1.10:4105",search:"?pin=123456",hash:"#secret"};
let copied=[],clicked;
const navigator={clipboard:{writeText:async value=>copied.push(value)}};
const fields={
 roomLinkText:{value:"",focused:false,selected:false,focus(){this.focused=true},select(){this.selected=true}},
 roomLinkCopy:{addEventListener(event,callback){assert.equal(event,"click");clicked=callback}},
 roomLinkStatus:{textContent:""}
};
const $=id=>fields[id];
"""
    checks = r"""
(async()=>{
  assert.equal(fields.roomLinkText.value,"http://192.168.1.10:4105/");
  await clicked();
  assert.deepEqual(copied,["http://192.168.1.10:4105/"]);
  assert.match(fields.roomLinkStatus.textContent,/copied/i);
  navigator.clipboard=null;
  await clicked();
  assert.equal(fields.roomLinkText.focused,true);
  assert.equal(fields.roomLinkText.selected,true);
  assert.match(fields.roomLinkStatus.textContent,/manually/i);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + share + checks,
                   check=True, text=True, timeout=10)


def test_joined_room_and_open_expiry_return_focus_to_visible_content():
    """Headless browser focus regression for join/rejoin, not a real desktop."""
    import shutil
    import subprocess
    import pytest

    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]

    def _fn(name):
        start = script.index(f"function {name}(")
        depth, i = 0, script.index("{", start)
        while True:
            depth += script[i] == "{"
            depth -= script[i] == "}"
            i += 1
            if depth == 0:
                return script[start:i]

    joined = _fn("showJoinedRoom")
    expired = _fn("expireSession")
    assert 'id="queueHeading" tabindex="-1"' in portal._HTML
    if not shutil.which("node"):
        pytest.skip("Node.js required to test focus transitions")
    harness = r"""
const assert=require("node:assert/strict");
const elements={dashboard:{hidden:true},uploadCard:{hidden:true},
 homeHeading:{focusCount:0,focus(){this.focusCount++}},
 login:{hidden:true},loginButton:{disabled:false},
 pin:{focusCount:0,focus(){this.focusCount++}},
 name:{focusCount:0,focus(){this.focusCount++}},
 errorDash:{textContent:""},error:{textContent:""}};
const $=id=>elements[id];
const loginButton=elements.loginButton;
let csrf="paired",shortcutState={},statusFailures=3,uploading=false,activeUploadController=null;
let playhead=null,playheadTimer=null;
function stopPlayhead(){}
const pendingControls={clear(){}};const roomEvents={stop(){}};
function syncRemoteWakeLock(){}
function resetUploadBatch(){}
function showError(id,msg){$(id).textContent=msg}
"""
    scenario = r"""
showJoinedRoom();
assert.equal(elements.homeHeading.focusCount,1);
assert.equal(elements.dashboard.hidden,false);
showJoinedRoom();
assert.equal(elements.homeHeading.focusCount,1,"polls must not steal focus");
const PIN_REQUIRED=false;
expireSession();
assert.equal(elements.name.focusCount,1);
assert.equal(elements.pin.focusCount,0);
assert.match(elements.error.textContent,/name to rejoin/);
assert.equal(elements.login.hidden,false);
assert.equal(elements.dashboard.hidden,true);
"""
    subprocess.run(["node", "-"], input=harness + joined + expired + scenario,
                   check=True, text=True, timeout=10)


def test_update_notice_focuses_recovery_action():
    """A stale remote must offer a reachable reload button to keyboard users."""
    text = portal._HTML
    start = text.index("function showUpdateNotice(){")
    end = text.index("function matchingBuild(", start)
    notice = text[start:end]
    assert 'document.getElementById("updateNotice").hidden=false' in notice
    assert 'document.getElementById("reloadNow").focus?.({preventScroll:true})' in notice


def test_mesh_panel_uses_shared_semantic_theme_instead_of_dark_literals():
    """Network-status badges remain legible in light/dark/high-contrast themes."""
    import re
    import portal_mesh_panel

    panel = portal_mesh_panel.panel_html()
    css = panel.split("<style>", 1)[1].split("</style>", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    for token in ("--line", "--accent", "--focus", "--muted",
                  "--danger", "--border", "--dim"):
        assert f"var({token})" in css
    assert 'id="meshConn" class="conn" role="status" aria-live="polite"' in panel
    assert 'id="meshTargets" aria-label="Playback targets"' in panel


def test_screen_panel_is_reachable_and_uses_guest_safe_explanations():
    """Assembled room markup includes the screen panel, not only the base HTML."""
    from portal_screen_page import panel_html

    page = room_html()
    assert "screensPanel" in page.ids
    assert "screensPanel" in page.anchors
    assert '#dashboard>#screensPanel' in portal._HTML
    assert '#dashboard>#meshPanel' in portal._HTML
    assert '#dashboard>#castEntry' in portal._HTML

    panel = panel_html()
    assert 'aria-labelledby="screensPanelHeading"' in panel
    assert "House PIN only if one has been set" in panel
    assert "Stop this screen without stopping the host TV" in panel
    assert "command received; checking its state." in panel
    assert 'play.setAttribute("aria-label","Play selected queue item on "+sc.name)' in panel
    assert 'toggle.setAttribute("aria-label",(sc.state==="paused"?"Resume":"Pause")+" playback on "+sc.name)' in panel
    assert 'stop.setAttribute("aria-label","Stop playback on "+sc.name)' in panel


def test_play_pause_button_explains_actual_state_without_replacing_dom():
    """Headless browser test: shared playback action is always unambiguous."""
    import shutil
    import subprocess
    import pytest

    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function playbackToggleCopy(state){")
    end = script.index("function showJoinedRoom(){", start)
    controls = script[start:end]
    assert 'renderPlaybackToggle(s.state)' in script
    if not shutil.which("node"):
        pytest.skip("Node.js required for playback button regression")
    harness = r"""
const assert=require("node:assert/strict");
let labels=[];
const button={
  textContent:"Play / pause",title:"",
  setAttribute(key,value){assert.equal(key,"aria-label");this.ariaLabel=value;labels.push(value)}
};
const document={querySelector(selector){
  assert.equal(selector,'[data-action="play_pause"]');
  return button;
}};
"""
    checks = r"""
renderPlaybackToggle("PLAYING");
assert.equal(button.textContent,"Pause");
assert.match(button.ariaLabel,/Pause playback.*for everyone/);
renderPlaybackToggle("BUFFERING");
assert.equal(button.textContent,"Pause");
renderPlaybackToggle("PAUSED");
assert.equal(button.textContent,"Resume");
assert.match(button.title,/Resume playback.*for everyone/);
renderPlaybackToggle("IDLE");
assert.equal(button.textContent,"Play / pause");
assert.match(button.ariaLabel,/Toggle playback/);
assert.equal(labels.length,4);
"""
    subprocess.run(["node", "-"], input=harness + controls + checks,
                   check=True, text=True, timeout=10)


def test_clear_up_next_requires_confirmation_before_shared_mutation():
    """No destructive queue command on a stray tap or cancelled confirmation."""
    import shutil
    import subprocess
    import pytest

    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function confirmClearQueue(){")
    end = script.index('document.querySelectorAll("[data-action]")', start)
    actions = script[start:end]
    assert 'void act("queue_clear")' in actions
    if not shutil.which("node"):
        pytest.skip("Node.js is required to test the shared queue confirmation")
    harness = r"""
const assert=require("node:assert/strict");
let queueState=[],calls=[],prompts=[],allow=false,click;
const window={confirm(message){prompts.push(message);return allow}};
const $=id=>({
  addEventListener(name,handler){
    assert.equal(id,"clearQueue");
    assert.equal(name,"click");
    click=handler;
  }
});
function act(action){calls.push(action)}
"""
    scenarios = r"""
click();
assert.equal(calls.length,0);
assert.equal(prompts.length,0,"empty queue must never prompt");
queueState=[{id:"one"},{id:"two"}];
click();
assert.equal(calls.length,0,"cancelled dialog must never send a command");
assert.match(prompts.at(-1),/2 waiting items.*for everyone/);
assert.match(prompts.at(-1),/does not stop what is currently playing/);
allow=true;
click();
assert.deepEqual(calls,["queue_clear"]);
"""
    subprocess.run(["node", "-"], input=harness + actions + scenarios,
                   check=True, text=True, timeout=10)


def test_browser_screen_help_and_available_controls_for_touch_guests():
    """Disclose screen-only effects and disable commands with no available target."""
    import shutil
    import subprocess
    import pytest
    from portal_screen_page import panel_html

    panel = panel_html()
    assert "How to use and control browser screens" in panel
    assert "<details class=\"help\"><summary>" in panel
    assert "not the main room TV" in panel
    assert "until it reconnects" in panel
    assert 'toggle.disabled=!sc.item||!sc.ready' in panel
    assert 'stop.disabled=!sc.item||!sc.ready' in panel
    assert 'choice[key]=pick.value;' in panel
    assert 'updateScreenPlayButton(play,pick,!!screenById.get(key)?.ready)' in panel
    assert 'function makeScreenRow(sc)' in panel
    assert 'function updateScreenRow(li,sc)' in panel

    script = panel.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function updateScreenPlayButton(")
    end = script.index("const label=", start)
    fn = script[start:end]
    if not shutil.which("node"):
        pytest.skip("Node.js is required to test browser screen selection")
    harness = r"""
const assert=require("node:assert/strict");
const play={disabled:false},pick={value:""};
updateScreenPlayButton(play,pick,true);
assert.equal(play.disabled,true,"no item selected");
pick.value="queue-1";
updateScreenPlayButton(play,pick,true);
assert.equal(play.disabled,false,"reachable screen with a selected item");
updateScreenPlayButton(play,pick,false);
assert.equal(play.disabled,true,"unreachable screen cannot play");
pick.value="";
updateScreenPlayButton(play,pick,true);
assert.equal(play.disabled,true,"cleared selection cannot play");
"""
    subprocess.run(["node", "-"], input=fn + harness, check=True, text=True, timeout=10)


def test_mesh_network_help_defines_target_states_without_cast_permissions():
    """The read-only mesh panel explains node/receiver meaning on touch and keyboard."""
    from portal_mesh_panel import panel_html

    panel = panel_html()
    assert '<details class="help"><summary>What do the network devices and target states mean?</summary>' in panel
    assert "Devices</strong> are SmoothCast computers" in panel
    assert "Primary</strong> is the node coordinating the mesh" in panel
    assert "Reported ready</strong> means" in panel
    assert "Reported in use</strong> means" in panel
    assert "Can't be reached</strong> means" in panel
    assert "It does not cast, claim receivers or upload files" in panel
    assert 'id="meshConn" class="conn" role="status" aria-live="polite"' in panel


def test_network_navigation_only_appears_when_mesh_is_available():
    """Do not send guests from the sticky menu to a hidden mesh section."""
    import shutil
    import subprocess
    import pytest
    from portal_mesh_panel import panel_html

    page = room_html()
    assert "meshNavLink" in page.ids and "meshPanel" in page.ids
    assert "meshPanel" in page.anchors
    assert '<a id="meshNavLink" href="#meshPanel" hidden>Live mesh</a>' in portal._HTML
    panel = panel_html()
    assert 'panel.hidden=false;showNetworkNavigation(true)' in panel
    assert 'panel.hidden=true;showNetworkNavigation(false)' in panel
    script = panel.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function showNetworkNavigation(visible){")
    end = script.index("const $=id=>", start)
    fn = script[start:end]
    if not shutil.which("node"):
        pytest.skip("Node.js required for conditional navigation test")
    harness = r"""
const assert=require("node:assert/strict");
const queueLink={hidden:true};
const document={getElementById(id){assert.equal(id,"queueMeshLink");return queueLink}};
let navLink={hidden:true};
showNetworkNavigation(true);
assert.equal(navLink.hidden,false);
assert.equal(queueLink.hidden,false);
showNetworkNavigation(false);
assert.equal(navLink.hidden,true);
assert.equal(queueLink.hidden,true);
navLink=null;
assert.doesNotThrow(()=>showNetworkNavigation(true));
"""
    subprocess.run(["node", "-"], input=fn + harness, check=True, text=True, timeout=10)


def test_optional_panels_are_dashboard_children_and_not_login_siblings():
    """The actual served page must place dynamic sections inside the room grid."""
    from html.parser import HTMLParser

    class Parents(HTMLParser):
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "param", "source", "track", "wbr"}

        def __init__(self):
            super().__init__()
            self.stack = []
            self.parents = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            element_id = attrs.get("id")
            if element_id:
                self.parents[element_id] = self.stack[-1][1] if self.stack else None
            if tag not in self.void:
                self.stack.append((tag, element_id))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    document = Parents()
    document.feed(portal._page().decode("utf-8"))
    assert document.parents["screensPanel"] == "dashboard"
    assert document.parents["meshPanel"] == "dashboard"
    assert document.parents["shortcutsHelp"] is None
    assert document.parents["uploadCard"] == "dashboard"
    assert document.parents["login"] is None  # main has no id; login is outside dashboard
    assert '#dashboard>#screensPanel' in portal._HTML
    assert '#dashboard>#meshPanel' in portal._HTML


def test_mesh_retry_timer_is_cancelled_on_room_exit_and_tab_resume():
    """A hidden room must not retain an old 30s backoff for the next guest."""
    import shutil
    import subprocess
    import pytest
    from portal_mesh_panel import panel_html

    panel = panel_html()
    assert "cancelMeshRetry();backoff=3000;close();started=false" in panel
    assert "else{clearTimeout(hiddenTimer);if(!es){cancelMeshRetry();boot()}}" in panel
    script = panel.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("function cancelMeshRetry(){")
    end = script.index("async function boot(){", start)
    functions = script[start:end]
    if not shutil.which("node"):
        pytest.skip("Node.js required for timer lifecycle regression")
    harness = r"""
const assert = require("node:assert/strict");
let retry = null,backoff=3000,tid=0;
const scheduled=new Map(),cancellations=[];
function setTimeout(callback,ms){const id=++tid;scheduled.set(id,{callback,ms});return id}
function clearTimeout(id){cancellations.push(id);scheduled.delete(id)}
function boot(){}
schedule();
const first=retry;
assert.equal(scheduled.get(first).ms,3000);
schedule();
const second=retry;
assert.equal(scheduled.has(first),false);
assert.equal(scheduled.get(second).ms,6000);
cancelMeshRetry();
assert.equal(retry,null);
assert.equal(scheduled.size,0);
assert.equal(cancellations.includes(second),true);
cancelMeshRetry();
assert.equal(scheduled.size,0,"cancelling twice must be harmless");
backoff=3000;
schedule();
assert.equal(scheduled.get(retry).ms,3000,"rejoining starts with short retry delay");
"""
    subprocess.run(["node", "-"], input=functions + harness,
                   check=True, text=True, timeout=10)


def test_open_join_shows_authoritative_identity_and_change_name_link():
    """Joined identity comes from server responses, never unsaved name input."""
    import shutil
    import subprocess
    import pytest

    page = room_html()
    assert "joinedAs" in page.ids
    assert "nameForm" in page.ids and "nameForm" in page.anchors
    assert '<a href="#nameForm">Change name</a>' in portal._HTML
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    assert 'showJoinedName(d.participant.name);' in script
    assert 'showJoinedName(data.participant.name);' in script
    assert 'showJoinedName(d.participant.name);showError("errorDash","Display name updated")' in script
    start = script.index("function showJoinedName(value){")
    end = script.index("function configureOpenJoin(){", start)
    helper = script[start:end]
    if not shutil.which("node"):
        pytest.skip("Node.js required to verify the joined-name rendering")
    harness = r"""
const assert=require("node:assert/strict");
const joinedAs={textContent:"",set innerHTML(_){throw Error("must not inject markup")}};
const $=id=>{assert.equal(id,"joinedAs");return joinedAs};
"""
    scenarios = r"""
showJoinedName("Sam");
assert.equal(joinedAs.textContent,"Joined as Sam");
showJoinedName("  Alice  ");
assert.equal(joinedAs.textContent,"Joined as Alice");
showJoinedName("");
assert.equal(joinedAs.textContent,"Joined as Guest");
showJoinedName("<img src=x onerror=alert(1)>");
assert.equal(joinedAs.textContent,"Joined as <img src=x onerror=alert(1)>");
"""
    subprocess.run(["node", "-"], input=harness + helper + scenarios,
                   check=True, text=True, timeout=10)


def test_invite_and_home_logo_are_outside_login_and_dashboard():
    """#592: the invite (QR + link) and the S home logo are usable before and after joining."""
    from html.parser import HTMLParser

    class Parents(HTMLParser):
        void = {"meta", "input", "img", "br", "link", "source", "path"}

        def __init__(self):
            super().__init__()
            self.stack, self.ancestors, self.attrs = [], {}, {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get("id"):
                self.ancestors[attrs["id"]] = [i for _, i in self.stack if i]
                self.attrs[attrs["id"]] = attrs
            if tag not in self.void:
                self.stack.append((tag, attrs.get("id")))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    html = portal._page().decode("utf-8")
    page = Parents()
    page.feed(html)
    for element in ("roomInvite", "inviteQr", "roomLinkText", "roomLinkCopy", "homeLogo"):
        assert html.count(f'id="{element}"') == 1
        assert "login" not in page.ancestors[element]
        assert "dashboard" not in page.ancestors[element]
    assert "roomInvite" in page.ancestors["roomLinkText"]
    logo = page.attrs["homeLogo"]
    assert logo["href"] == "#roomTop" and logo["aria-label"] == "SmoothCast home"
    assert 'id="roomTop" tabindex="-1"' in html
    assert page.attrs["inviteQr"]["alt"] and "hidden" in page.attrs["inviteQr"]
    assert "src" not in page.attrs["inviteQr"]  # assigned by script after handlers
    assert "same Wi-Fi" in html[html.index('id="inviteHow"'):][:200]


def test_invite_qr_registers_handlers_before_loading_and_falls_back_to_the_link():
    import shutil
    import subprocess
    import pytest

    if not shutil.which("node"):
        pytest.skip("node required")
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("// Ticket 592")
    block = script[start:script.index("})();", start) + 5]
    harness = r"""
const assert=require("node:assert/strict");
function make(){const log=[];const el={hidden:true,handlers:{},log,
  addEventListener(n,f){log.push("on:"+n);this.handlers[n]=f},
  removeAttribute(n){log.push("rm:"+n);delete this._src},
  set src(v){log.push("src");this._src=v},get src(){return this._src}};return el}
for(const outcome of ["load","error"]){
  const img=make(),fallback={hidden:true};
  const $=id=>({inviteQr:img,inviteQrFallback:fallback})[id];
  eval(BLOCK);
  assert.deepEqual(img.log.slice(0,3),["on:load","on:error","src"]);
  assert.equal(img._src,"/join-qr.png");
  img.handlers[outcome]();
  if(outcome==="load"){assert.equal(img.hidden,false);assert.equal(fallback.hidden,true)}
  else{assert.equal(img.hidden,true);assert.equal(fallback.hidden,false);assert.equal(img._src,undefined)}
}
"""
    run = subprocess.run(["node", "-"], input=harness.replace("BLOCK", repr(block)),
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


def test_guest_visible_text_uses_plain_words():
    """#599: everyday guest text says 'TV or speaker', 'SmoothCast computer' and
    'download'. Precise diagnostic terms live only behind Technical details,
    More and the mesh/network panels."""
    import re
    from html.parser import HTMLParser

    exempt = {"transferTech", "advancedPanel", "meshPanel", "networkActivity", "shortcutsHelp"}

    class Visible(HTMLParser):
        void = {"meta", "input", "img", "br", "link", "source", "path", "hr"}

        def __init__(self):
            super().__init__()
            self.stack, self.text, self.skip = [], [], 0

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            skip = attrs.get("id") in exempt or tag in ("script", "style")
            if not self.skip and not skip:
                self.text += [attrs[k] for k in ("title", "aria-label", "placeholder", "alt")
                              if attrs.get(k) and attrs.get("id") != "scVersion"]
            if tag not in self.void:
                self.stack.append(skip)
                self.skip += skip

        def handle_endtag(self, tag):
            if self.stack:
                self.skip -= self.stack.pop()

        def handle_data(self, data):
            if not self.skip and data.strip():
                self.text.append(data.strip())

    page = Visible()
    page.feed(portal._page().decode("utf-8"))
    jargon = re.compile(r"\b(receivers?|hosts?|acquisitions?|acquire|worker|chunk|offset|advertised)\b", re.I)
    offenders = [text for text in page.text if jargon.search(text)]
    assert offenders == []
    html = portal._page().decode("utf-8")
    assert '<details class="tech-details" id="transferTech"><summary>Technical details</summary>' in html
    assert 'id="transferTech" open' not in html  # collapsed by default


def test_mesh_stream_rows_show_total_runtime_even_without_a_position():
    import portal_mesh_panel

    html = portal_mesh_panel.panel_html()
    assert '"Total runtime "+timing(item.duration)' in html
    assert "h?h+" in html  # long films show hours rather than 125:30


def test_mesh_stream_rows_advance_a_playing_position_between_receiver_polls():
    import portal_mesh_panel

    html = portal_mesh_panel.panel_html()
    assert "item.observed_age_ms" in html or "observed_age_ms" in html
    assert 'if(item.state==="PLAYING")' in html and "setInterval" in html


def test_select_controls_meet_the_touch_target_size_used_by_buttons_and_inputs():
    """#558: the activity filter was an 18px sliver; every select now has a 44px target."""
    html = portal._HTML
    assert "select{font:inherit;min-height:44px;" in html
    assert 'id="activityFilter"' in html and html.count("<select") == html.count("</select>")


def test_front_page_contribution_links_reuse_existing_controls():
    page = room_html()
    by_id = {a["id"]: (tag, a) for tag, a in page.elements if "id" in a}
    for entry, target in (("openUploadEntry", "uploadCard"),
                          ("openLinkAcquisition", "linkAcquisition"),
                          ("openFindEntry", "findPanel")):
        assert by_id[entry][0] == "a"
        assert by_id[entry][1]["href"] == "#" + target
    assert page.ids.count("videoFile") == 1
    assert page.ids.count("linkInput") == 1
    assert page.ids.count("findInput") == 1
    assert 'aria-labelledby="contributeHeading"' in portal._HTML
