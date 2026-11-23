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
    assert 'id="joinTitle">Join the room' in text
    assert "only if the host has enabled one" in text
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


def test_advanced_controls_use_native_progressive_disclosure():
    page = room_html()
    assert ("details", {"id": "advancedPanel"}) in [
        (tag, {k: v for k, v in attrs.items() if k == "id"})
        for tag, attrs in page.elements if tag == "details" and attrs.get("id") == "advancedPanel"
    ]
    text = portal._HTML
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
    assert '$("uploadButton").disabled=uploading||!file;' in text


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
const el={
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
    loginHint:{textContent:"PIN needed"},loginButton:{textContent:"Join room"}
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
assert.equal(locked.loginButton.textContent,"Join room");
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
    start = script.index("function showJoinedRoom(){")
    end = script.index("function applyStatus(d){", start)
    joined = script[start:end]
    start = script.index("function expireSession(){")
    end = script.index("function clock(s){", start)
    expired = script[start:end]
    assert 'id="playbackHeading" tabindex="-1"' in portal._HTML
    if not shutil.which("node"):
        pytest.skip("Node.js required to test focus transitions")
    harness = r"""
const assert=require("node:assert/strict");
const elements={dashboard:{hidden:true},uploadCard:{hidden:true},
 playbackHeading:{focusCount:0,focus(){this.focusCount++}},
 login:{hidden:true},loginButton:{disabled:false},
 pin:{focusCount:0,focus(){this.focusCount++}},
 name:{focusCount:0,focus(){this.focusCount++}},
 errorDash:{textContent:""},error:{textContent:""}};
const $=id=>elements[id];
const loginButton=elements.loginButton;
let csrf="paired",shortcutState={},statusFailures=3,uploading=false,activeUploadController=null;
const pendingControls={clear(){}};const roomEvents={stop(){}};
function syncRemoteWakeLock(){}
function resetUploadBatch(){}
function showError(id,msg){$(id).textContent=msg}
"""
    scenario = r"""
showJoinedRoom();
assert.equal(elements.playbackHeading.focusCount,1);
assert.equal(elements.dashboard.hidden,false);
showJoinedRoom();
assert.equal(elements.playbackHeading.focusCount,1,"polls must not steal focus");
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
    assert "House PIN only if the host requires it" in panel
    assert "Stop this screen without stopping the host TV" in panel
    assert "Screen command received; checking its state." in panel


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
