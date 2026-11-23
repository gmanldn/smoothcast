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
    parser.feed(portal._HTML)
    return parser


def test_guest_navigation_has_unique_ids_and_real_targets():
    page = room_html()
    assert len(page.ids) == len(set(page.ids)), "Duplicate IDs break DOM event binding"
    assert set(page.anchors) <= set(page.ids)
    assert {"playback", "findPanel", "uploadCard", "queuePanel", "peoplePanel",
            "advancedPanel"} <= set(page.anchors)


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
