"""LAN dashboard HTTP behavior using only a private loopback test listener."""
from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
import shutil
import subprocess
from types import MethodType, SimpleNamespace
import sys
import threading
import json
import time
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal


PIN = "234567"


class PortalRig:
    def __init__(self, uploads=None, clock=None, queue=None):
        self.calls = []
        self.queue = list(queue or [])

        def dispatch(action, payload):
            self.calls.append((action, payload))
            if action == "status":
                return {"title": "sample.mp4", "state": "PLAYING", "queue": self.queue}
            return "accepted"

        self.server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, dispatch,
                                                uploads=uploads, clock=clock or time.monotonic)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def request(self, method, path, body=None, *, cookie=None, csrf=None, origin=None, host=None,
                content_type=None, extra_headers=None):
        headers = {"Host": host or self.host}
        if origin is not None:
            headers["Origin"] = origin
        if cookie:
            headers["Cookie"] = cookie
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if body is not None:
            if isinstance(body, dict):
                headers["Content-Type"] = "application/json"
                body = json.dumps(body).encode()
            elif content_type:
                headers["Content-Type"] = content_type
        headers.update(extra_headers or {})
        conn = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


@pytest.fixture
def rig():
    value = PortalRig()
    yield value
    value.close()


def decode(body):
    import json
    return json.loads(body)


def test_pin_is_six_securely_selected_digits():
    assert len(portal.new_pin()) == portal.PIN_LENGTH
    assert set(portal.new_pin()).issubset(set(portal.PIN_DIGITS))
    choices = iter("123456")
    assert portal.new_pin(choice=lambda _alphabet: next(choices)) == "123456"


def test_friendly_name_is_short_lowercase_and_stable():
    assert portal.friendly_name("Living-Room Laptop") == "smoothcast-living-room-laptop"
    assert portal.friendly_name("smoothcast") == "smoothcast"
    assert portal.friendly_name("  --  ") == "smoothcast"
    assert portal.friendly_name("A" * 80) == "smoothcast-" + "a" * 21
    assert portal.valid_friendly_name("smoothcast-lounge")
    assert not portal.valid_friendly_name("SmoothCast")
    assert not portal.valid_friendly_name("bad name")
    assert not portal.valid_friendly_name("")


def test_portal_rejects_non_rfc1918_addresses():
    for address in ("0.0.0.0", "127.0.0.1", "169.254.1.2", "203.0.113.10", "8.8.8.8"):
        with pytest.raises(portal.PortalError):
            portal.Portal(address, lambda *_args: {})


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_up_next_render_preserves_focus_and_labels_queue_actions():
    source = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    script = source[source.index("let queueRenderKey=null,queuePressed="):source.index("let statusRequest=null")]
    harness = r"""
const assert = require("node:assert/strict");
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.listeners={};this.parentElement=null;this.className="";this.textContent="";this.classList={add:name=>{this.className+=(this.className?" ":"")+name}}}
  append(...items){for(const item of items){if(item.parentElement){const siblings=item.parentElement.children;const i=siblings.indexOf(item);if(i>=0)siblings.splice(i,1)}item.parentElement=this;this.children.push(item)}}
  replaceChildren(...items){this.children=[];this.append(...items)}
  addEventListener(name,handler){this.listeners[name]=handler}
  setAttribute(name,value){this.attributes[name]=String(value)}
  getAttribute(name){return this.attributes[name]??null}
  closest(selector){const field=selector==="[data-queue-id]"?"queueId":selector==="[data-queue-action]"?"queueAction":null;if(!field)return null;for(let node=this;node;node=node.parentElement)if(node.dataset[field])return node;return null}
  contains(node){for(let current=node;current;current=current.parentElement)if(current===this)return true;return false}
  focus(){document.activeElement=this}
}
const queue=new Element("ul");queue.focus=()=>{document.activeElement=queue};
const document={activeElement:null,createElement:tag=>new Element(tag),addEventListener(){}};
const elements={queue};function $(id){return elements[id]}
const calls=[];function act(...args){calls.push(args)}
"""
    scenario = r"""
const initial=[{id:"a",title:"Alpha",votes:2},{id:"b",title:"Beta",voted:true}];
renderQueue(initial);
const originalRow=queue.children[0];
assert.equal(queue.children[0].getAttribute("aria-posinset"),"1");
assert.equal(queue.children[1].getAttribute("aria-setsize"),"2");
const buttons=queue.children[0].children[1].children;
assert.deepEqual(buttons.map(button=>button.getAttribute("aria-label")),[
  "Vote for Alpha","Play Alpha now","Move Alpha earlier in Up Next","Move Alpha later in Up Next","Play Alpha next","Remove Alpha from Up Next"]);
assert.equal(buttons[2].disabled,true,"the first item cannot move earlier");
assert.equal(buttons[3].disabled,false,"the first item can move later");
queue.listeners.click({target:buttons[3]});
assert.deepEqual(calls[0], ["queue_move",undefined,{id:"a",position:1}]);
const betaRow=queue.children[1], betaNext=betaRow.children[1].children[4];
betaNext.focus();
renderQueue(initial.map(item=>({...item})));
assert.equal(queue.children[0],originalRow,"unchanged polling must retain the existing DOM row");
renderQueue([initial[1],initial[0]]);
const reorderedBetaNext=queue.children[0].children[1].children.find(button=>button.dataset.queueAction==="next");
assert.equal(document.activeElement,reorderedBetaNext,"reordering must restore focus to the same item and action");
assert.equal(reorderedBetaNext,betaNext,"reordering must not replace a pressed control");
queue.listeners.pointerdown({target:reorderedBetaNext});
renderQueue([initial[0]]);
assert.equal(queue.children[0].dataset.queueId,"b","a pressed row stays until click");
queue.listeners.click({target:reorderedBetaNext});
assert.deepEqual(calls.at(-1),["queue_next",undefined,{id:"b"}],"pressed button acts on original item");
releaseQueuePointer();
assert.equal(queue.children[0].dataset.queueId,"a");
assert.equal(document.activeElement,queue,"when the focused row disappears, focus returns to the queue");
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   text=True, check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_browser_status_poll_handles_timeout_visibility_and_expired_session():
    script = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = """
const assert = require("node:assert/strict");
const listeners = new Map(), timers = new Map();
const elements = new Map();
function element(id) {
  if(!elements.has(id)){
    elements.set(id, {files: [], addEventListener(){}, focus(){this.focused=true},
                      querySelector(){return element("loginButton")}});
  }
  return elements.get(id);
}
const document = {
  hidden: false,
  addEventListener(name, handler){listeners.set(name, handler)},
  getElementById: element,
  querySelectorAll(){return []},
};
const window = {addEventListener(){}};
const location = {origin:"http://127.0.0.1:4321"}; // Browser origin for room-share controls.
let timerId = 0, requests = 0, respond;
const setTimeout = (callback, delay) => {
  timers.set(++timerId, {callback, delay});
  return timerId;
};
const clearTimeout = id => timers.delete(id);
const fetch = (_url, {signal}) => {
  if(_url==="/api/session")return Promise.resolve({status:401,ok:false,
    json:async()=>({ok:false,error:"Session expired"})});
  requests++;
  return new Promise((resolve, reject) => {
    respond = resolve;
    signal.addEventListener("abort", () => reject(signal.reason), {once:true});
  });
};
"""
    scenario = """
(async()=>{
  csrf = "paired";
  const first = refresh();
  await refresh();
  assert.equal(requests, 1);
  assert.equal(timers.size, 1);
  const deadline = [...timers.values()][0];
  assert.equal(deadline.delay, 5000);
  deadline.callback();
  await first;
  assert.match(element("errorDash").textContent, /timed out/);
  assert.equal(timers.size, 1);
  const retry = [...timers.values()][0];
  assert.ok(retry.delay >= 4000 && retry.delay <= 4500);
  document.hidden = true;
  listeners.get("visibilitychange")();
  assert.equal(timers.size, 0);
  document.hidden = false;
  listeners.get("visibilitychange")();
  assert.equal(requests, 2);
  pendingUpload = {path:"/api/uploads/stale"};
  uploading = true;
  activeUploadController = new AbortController();
  document.getElementById("videoFile").value = "stale.wav";
  respond({status:401, ok:false, json:async()=>({error:"Session expired"})});
  for(let index=0;index<3;index++)await Promise.resolve();
  assert.equal(csrf, "");
  assert.equal(timers.size, 0);
  assert.equal(element("dashboard").hidden, true);
  assert.equal(element("uploadCard").hidden, true);
  assert.equal(element("login").hidden, false);
  assert.equal(element("pin").focused, true);
  assert.match(element("error").textContent, /current PIN/);
  assert.equal(activeUploadController.signal.aborted, true);
  assert.equal(element("loginButton").disabled, true);
  await assert.rejects(uploadRequest("GET", pendingUpload.path), {status:401});
  assert.equal(requests, 2);
  finishUpload();
  assert.equal(element("loginButton").disabled, false);
  assert.equal(pendingUpload, null);
  assert.equal(element("videoFile").value, "");
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   text=True, check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_remote_wake_lock_persists_and_reacquires_only_while_visible():
    start = portal._HTML.index('const keepScreenOn=')
    end = portal._HTML.index('const PIN_REQUIRED=', start)
    script = portal._HTML[start:end]
    harness = """
const assert = require("node:assert/strict");
const storage = new Map([["sc_keep_screen_on", "1"]]);
const localStorage = {getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)};
const checkbox = {checked:false,addEventListener(_event,handler){this.change=handler}};
const hint = {hidden:true};
const $ = id => id==="keepScreenOn"?checkbox:hint;
const document = {hidden:false};
const navigator = {wakeLock:{request}};
let csrf="",stalePage=false,requests=0,releases=0;
function request(type){
  assert.equal(type,"screen");
  requests++;
  return Promise.resolve({
    released:false,
    addEventListener(event,handler){assert.equal(event,"release");this.onrelease=handler},
    async release(){this.released=true;releases++;this.onrelease?.()},
  });
}
"""
    scenario = """
(async()=>{
  assert.equal(checkbox.checked,true);
  await syncRemoteWakeLock();
  assert.equal(requests,0,"a saved preference does not acquire before authentication");
  csrf="paired";
  await Promise.all([syncRemoteWakeLock(),syncRemoteWakeLock()]);
  assert.equal(requests,1,"only one request is in flight");
  document.hidden=true;
  await syncRemoteWakeLock();
  assert.equal(releases,1);
  document.hidden=false;
  await syncRemoteWakeLock();
  assert.equal(requests,2,"a visible tab reacquires the lock");
  checkbox.checked=false;
  await checkbox.change();
  assert.equal(storage.get("sc_keep_screen_on"),"0");
  assert.equal(releases,2);
  delete navigator.wakeLock;
  checkbox.checked=true;
  await checkbox.change();
  assert.equal(storage.get("sc_keep_screen_on"),"1");
  assert.equal(hint.hidden,false,"unsupported browsers show the dim hint");
  checkbox.checked=false;
  await checkbox.change();
  checkbox.checked=true;
  await checkbox.change();
  assert.equal(hint.hidden,true,"the hint is shown only once");
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   text=True, check=True, timeout=10)


def test_dashboard_html_is_local_and_contains_no_pin_or_status_data(rig):
    status, body, headers = rig.request("GET", "/")
    assert status == 200
    page = body.decode()
    assert "fetch(\"/api/status\"" in page
    assert "https://" not in page and "http://" not in page
    assert PIN not in page
    assert 'id="keepScreenOn" type="checkbox"' in page
    assert "Keep screen on" in page
    assert "Your browser may dim the screen. Use Guided Access/kiosk mode" in page
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "setTimeout(()=>{timedOut=true;controller.abort();},60000)" in page
    assert 'if(timedOut)error=Object.assign(Error("Host did not respond within 60 seconds"),{status:408})' in page
    assert "clearTimeout(deadline);clearInterval(tick)" in page
    assert 'if(activeUploadController)activeUploadController.abort()' in page
    assert "Select Resume to retry" in page
    assert "Audio always goes into Up Next" in page
    assert "compatible video may start playing" in page
    assert 'accept="audio/*,video/*,.mkv,.ts,.wmv" multiple' in page
    assert "while(batchIndex<batchFiles.length" in page
    assert "six-digit House PIN" in page
    assert 'inputmode="numeric"' in page
    assert 'pattern="[0-9]{6}"' in page
    assert page.index('div id="dashboard" hidden') < page.index('id="networkActivity"')
    assert 'li.children[0].children[0].textContent=itemTitle' in page
    assert 'detail.textContent=' in page
    assert 'id="musicAutogain"' in page
    assert 'id="name"' in page and 'id="people"' in page and 'id="activity"' in page
    assert 'id="peers"' in page and "renderPeers(s.peers" in page
    assert 'id="queue" aria-label="Shared Up Next queue" tabindex="-1"' in page
    assert "function renderQueue(items)" in page and "renderQueue(s.queue)" in page
    assert 'button.setAttribute("aria-label",labels[i])' in page
    assert ".slice(0,6)" in page
    assert "queue_vote" in page and "queue_play" in page
    assert 'id="clearQueue"' in page and "act(\"queue_clear\")" in page
    assert "queue_revision=queueRevision" in page and "body.queue_command_id=" in page
    assert "Add to Up Next" in page


def test_status_requires_a_pin_and_rejects_host_rebinding(rig):
    status, body, _ = rig.request("GET", "/api/status")
    assert status == 401 and decode(body)["ok"] is False
    status, _, _ = rig.request("GET", "/api/status", host="evil.example")
    assert status == 400
    assert rig.calls == []


def login(rig, pin=PIN, name="Guest"):
    status, body, headers = rig.request("POST", "/api/login", {"pin": pin, "name": name},
                                        origin=f"http://{rig.host}")
    return status, decode(body), headers.get("Set-Cookie", "").split(";", 1)[0]


def test_session_reload_recovers_same_participant_ten_times_and_login_reuses_it(rig):
    status, data, cookie = login(rig, name="Sam")
    assert status == 200
    participant_id = data["participant"]["id"]
    csrf = data["csrf"]
    for _ in range(10):
        status, body, _ = rig.request("GET", "/api/session", cookie=cookie)
        assert status == 200
        restored = decode(body)
        assert restored["csrf"] == csrf
        assert restored["participant"]["id"] == participant_id
    status, body, headers = rig.request(
        "POST", "/api/login", {"pin": "", "name": "Sam"}, cookie=cookie,
        origin=f"http://{rig.host}")
    assert status == 200
    assert headers["Set-Cookie"].split(";", 1)[0] == cookie
    assert decode(body)["participant"]["id"] == participant_id
    assert len(rig.server.room.participants) == 1


def test_session_recovery_rejects_expired_cookie(rig):
    _status, _data, cookie = login(rig, name="Sam")
    token = cookie.partition("=")[2]
    key = rig.server._session_key(token)
    rig.server._sessions[key].expiry = rig.server.clock() - 1
    status, body, _ = rig.request("GET", "/api/session", cookie=cookie)
    assert status == 401
    assert decode(body)["ok"] is False


def test_restarted_room_can_publish_recovered_queue_but_rejects_old_cookie(tmp_path):
    import room_checkpoint

    media = tmp_path / "film.mkv"
    media.write_bytes(b"synthetic movie")
    checkpoint = tmp_path / "room.json"
    original = PortalRig()
    try:
        status, _, old_cookie = login(original, name="Sam")
        assert status == 200
        room_checkpoint.write_checkpoint(checkpoint, [str(media)])
        assert original.request("GET", "/api/session", cookie=old_cookie)[0] == 200
    finally:
        original.close()

    saved = room_checkpoint.load_checkpoint(checkpoint)
    assert saved.items == (str(media),)
    new_room = PortalRig(queue=[{"id": "recovered", "title": Path(saved.items[0]).name}])
    try:
        assert new_room.request("GET", "/api/session", cookie=old_cookie)[0] == 401
        assert not new_room.server.room.participants
        status, _, new_cookie = login(new_room, name="Sam")
        assert status == 200 and new_cookie != old_cookie
        status, body, _ = new_room.request("GET", "/api/status", cookie=new_cookie)
        assert status == 200
        assert decode(body)["state"]["queue"] == [
            {"id": "recovered", "title": "film.mkv", "votes": 0, "voted": False},
        ]
    finally:
        new_room.close()


def test_session_recovery_checks_host_and_origin(rig):
    _status, _data, cookie = login(rig, name="Sam")
    assert rig.request("GET", "/api/session", cookie=cookie,
                       host="evil.example")[0] == 400
    assert rig.request("GET", "/api/session", cookie=cookie,
                       origin="http://evil.example")[0] == 400


def test_join_reclaims_offline_room_slot_before_refusing(rig):
    # Presence expiry is monotonic, independent of wall-clock corrections.
    now = rig.server.clock()
    stale = rig.server.room.join("Offline", now=now - portal.portal_room.ONLINE_SECONDS - 1)
    for index in range(portal.portal_room.MAX_PARTICIPANTS - 1):
        rig.server.room.join(f"Guest {index}", now=now)
    assert len(rig.server.room.participants) == portal.portal_room.MAX_PARTICIPANTS
    _token, _csrf, joined = rig.server.create_session("New guest")
    assert joined.id in rig.server.room.participants
    assert stale.id in rig.server.room._dormant


def test_session_capacity_evicts_least_recently_used(monkeypatch, rig):
    monkeypatch.setattr(portal, "MAX_SESSIONS", 3)
    tokens = [rig.server.create_session(f"Guest {index}")[0] for index in range(3)]
    assert rig.server.session_participant(tokens[0]) is not None
    newest = rig.server.create_session("Guest 3")[0]
    assert rig.server.session_participant(tokens[0]) is not None
    assert rig.server.session_participant(tokens[1]) is None
    assert rig.server.session_participant(tokens[2]) is not None
    assert rig.server.session_participant(newest) is not None


def test_revocation_cancels_private_guest_upload_without_touching_playback(tmp_path):
    import portal_uploads
    manager = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads=manager)
    try:
        _, participant, cookie = login(rig, PIN, "Uploader")
        token = cookie.partition("=")[2]
        created = manager.create(token, "example.mp4", 1024)
        upload_id = created["id"]
        path = manager.root / f"{upload_id}.partial"
        assert path.exists()
        assert rig.server.revoke_participant(participant["participant"]["id"]) == 1
        assert not path.exists()
        assert manager.snapshot() == []
        status, _body, _headers = rig.request(
            "POST", "/api/uploads", {"name": "next.mp4", "size": 1024},
            cookie=cookie, csrf=participant["csrf"], origin=f"http://{rig.host}")
        assert status == 403
        assert all(name not in {"stop", "seek", "queue_remove"} for name, _ in rig.calls)
    finally:
        rig.close()
        manager.close()


def test_desktop_wires_host_only_revoke_and_confirmed_end_access():
    from gui_source import main_window_methods
    methods = main_window_methods()
    assert "portal_guest_dropdown" in methods["_build_portal_card"]
    assert "portal_end_access_button" in methods["_build_portal_card"]
    assert "revoke_guest" in methods["_portal_revoke_selected"]
    assert "Adw.MessageDialog" in methods["_portal_confirm_end_access"]
    assert "current.end_guest_access()" in methods["_portal_end_guest_access"]


def test_host_can_revoke_one_guest_without_stopping_playback_or_others(rig):
    status, first, cookie_a = login(rig, PIN, "Alice")
    assert status == 200
    status, second, cookie_b = login(rig, PIN, "Bob")
    assert status == 200
    participant = first["participant"]["id"]
    assert rig.server.revoke_participant(participant) == 1
    assert rig.server.revoke_participant(participant) == 0
    assert rig.request("GET", "/api/status", cookie=cookie_a)[0] == 401
    assert rig.request("GET", "/api/status", cookie=cookie_b)[0] == 200
    status, _data, _headers = rig.request(
        "POST", "/api/action", {"action": "seek", "value": 30},
        cookie=cookie_a, csrf=first["csrf"], origin=f"http://{rig.host}")
    assert status == 403
    assert all(name not in {"seek", "stop"} for name, _ in rig.calls)
    assert {p["name"] for p in rig.server.room.snapshot()["participants"]} == {"Bob"}
    assert second["participant"]["id"] in rig.server.room.participants


def test_host_rotates_pin_and_signs_out_all_without_touching_receiver(rig):
    _, alice, cookie_a = login(rig, PIN, "Alice")
    _, bob, cookie_b = login(rig, PIN, "Bob")
    old_fence = rig.server.fence.snapshot()
    new_access_pin = rig.server.revoke_all()
    assert new_access_pin.isdigit() and len(new_access_pin) == portal.PIN_LENGTH
    assert new_access_pin != PIN
    assert rig.server.fence.snapshot()[:2] != old_fence[:2]
    assert rig.request("GET", "/api/status", cookie=cookie_a)[0] == 401
    assert rig.request("GET", "/api/status", cookie=cookie_b)[0] == 401
    assert login(rig, PIN, "Old PIN")[0] == 401
    status, guest, cookie_c = login(rig, new_access_pin, "New Guest")
    assert status == 200 and guest["participant"]["name"] == "New Guest"
    assert rig.request("GET", "/api/status", cookie=cookie_c)[0] == 200
    assert len(rig.server.room.snapshot()["participants"]) == 1
    assert all(name not in {"seek", "stop", "next", "previous"} for name, _ in rig.calls)
    assert alice["participant"]["id"] != bob["participant"]["id"]


def test_authorised_guest_payloads_are_fenced_at_gtk_dispatch_boundary(rig):
    _, guest, cookie = login(rig, PIN)
    key = rig.server._session_key(cookie.partition("=")[2])
    assert rig.server.session_key_active(key)
    rig.server.revoke_all()
    assert not rig.server.session_key_active(key)
    status, _body, _headers = rig.request(
        "POST", "/api/action", {"action": "next"},
        cookie=cookie, csrf=guest["csrf"], origin=f"http://{rig.host}")
    assert status == 403
    from gui_source import main_window_methods
    source = main_window_methods()["_portal_handle"]
    assert "session_key_active(session_key)" in source
    assert '"_portal_auth_key"' in source


def test_public_http_has_no_guest_revocation_or_pin_rotation_api(rig):
    _status, guest, cookie = login(rig, PIN)
    for path in ("/api/revoke", "/api/rotate-pin", "/api/revoke-all"):
        status, _body, _headers = rig.request(
            "POST", path, {}, cookie=cookie, csrf=guest["csrf"],
            origin=f"http://{rig.host}")
        assert status == 404


def test_login_is_serialised_with_host_rotation(rig, monkeypatch):
    # A concurrent PIN rotation cannot intervene after the PIN check but
    # before the cookie is entered in the session table.
    entered = threading.Event()
    proceed = threading.Event()
    original = rig.server.create_session
    def delayed_create(name):
        entered.set()
        assert proceed.wait(2)
        return original(name)
    monkeypatch.setattr(rig.server, "create_session", delayed_create)
    login_result = {}
    def run_login():
        login_result["value"] = login(rig, PIN, "Alice")
    thread = threading.Thread(target=run_login)
    thread.start()
    assert entered.wait(2)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(rig.server.revoke_all)
        assert not future.done()
        proceed.set()
        thread.join(3)
        new_access_pin = future.result(timeout=3)
    assert login_result["value"][0] == 200
    _status, _body, old_cookie = login_result["value"]
    assert rig.request("GET", "/api/status", cookie=old_cookie)[0] == 401
    assert login(rig, new_access_pin)[0] == 200


def test_pin_login_sets_http_only_session_and_dashboard_reads_main_state(rig):
    status, raw, headers = rig.request("POST", "/api/login", {"pin": PIN},
                                      origin=f"http://{rig.host}")
    result = decode(raw)
    set_cookie = headers.get("Set-Cookie", "")
    cookie = set_cookie.split(";", 1)[0]
    assert status == 200 and result["ok"]
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie
    status, body, headers = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200 and decode(body)["state"]["title"] == "sample.mp4"
    assert headers["Cache-Control"] == "no-store"
    assert rig.calls == [("status", {})]


def test_authenticated_status_exposes_only_the_peer_directory_snapshot(rig):
    _, _result, cookie = login(rig)
    rig.server.peer_directory = SimpleNamespace(snapshot=lambda: [{
        "id": "a" * 32, "name": "smoothcast-lounge", "version": 1,
        "compatible": True, "capabilities": ["room"],
        "url": "http://192.168.1.25:8765/",
    }])
    status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200
    state = decode(body)["state"]
    assert state["peer_discovery_available"] is True
    assert state["peers"][0]["name"] == "smoothcast-lounge"
    assert state["peers"][0]["url"] == "http://192.168.1.25:8765/"
    assert state["peers"][0]["compatible"] is True


def test_named_sessions_share_presence_and_votes(rig):
    first_status, first, cookie = login(rig, PIN, "Sam")
    assert first_status == 200 and first["participant"]["name"] == "Sam"
    second_status, second, _ = login(rig, PIN, "Sam")
    assert second_status == 200
    assert second["participant"]["name"] == "Sam (2)"
    status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200
    room = decode(body)["state"]["room"]
    assert {person["name"] for person in room["participants"]} == {"Sam", "Sam (2)"}
    assert room["me"]["name"] == "Sam"


def test_profile_edit_only_changes_the_authenticated_participant(rig):
    _, first, cookie = login(rig, PIN, "Sam")
    _, second, other_cookie = login(rig, PIN, "Alex")
    origin = f"http://{rig.host}"
    hostile = '<img src=x onerror="alert(1)">'
    status, body, _ = rig.request(
        "POST", "/api/profile",
        {"name": hostile, "participant_id": second["participant"]["id"], "role": "host"},
        cookie=cookie, csrf=first["csrf"], origin=origin,
    )
    assert status == 200 and decode(body)["participant"]["name"] == hostile
    status, body, _ = rig.request("GET", "/api/status", cookie=other_cookie)
    assert status == 200
    people = {person["id"]: person["name"]
              for person in decode(body)["state"]["room"]["participants"]}
    assert people == {first["participant"]["id"]: hostile,
                      second["participant"]["id"]: "Alex"}
    assert "textContent=person.name" in portal._HTML
    assert "innerHTML" not in portal._HTML


def test_queue_votes_are_per_person_and_require_a_live_item():
    queue = [{"id": "abc123", "title": "film.mkv", "duration": 90}]
    rig = PortalRig(queue=queue)
    try:
        _, first, cookie = login(rig, PIN)
        origin = f"http://{rig.host}"
        status, body, _ = rig.request("POST", "/api/action",
                                      {"action": "queue_vote", "id": "abc123", "value": True},
                                      cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 404  # queue has not been observed yet
        rig.request("GET", "/api/status", cookie=cookie)
        status, body, _ = rig.request("POST", "/api/action",
                                      {"action": "queue_vote", "id": "abc123", "value": True},
                                      cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 202
        status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
        item = decode(body)["state"]["queue"][0]
        assert item["votes"] == 1 and item["voted"] is True
        status, _, _ = rig.request("POST", "/api/action",
                                   {"action": "queue_vote", "id": "missing", "value": True},
                                   cookie=cookie, csrf=first["csrf"], origin=origin)
        assert status == 404
    finally:
        rig.close()


def test_queue_actions_are_forwarded_to_the_gui(rig):
    rig.queue = [{"id": "one", "title": "one.mkv", "duration": 0}]
    _, result, cookie = login(rig)
    rig.request("GET", "/api/status", cookie=cookie)
    origin = f"http://{rig.host}"
    for index, (action, extra) in enumerate((
            ("next", {}), ("previous", {}),
            ("queue_play", {"id": "one"}),
            ("queue_remove", {"id": "one"}),
            ("queue_move", {"id": "one", "position": 0}),
            ("queue_clear", {}))):
        payload = {"action": action, **extra}
        if action in {"queue_remove", "queue_move", "queue_clear"}:
            payload.update(queue_command_id=f"test-{index}", queue_revision=0)
        status, body, _ = rig.request("POST", "/api/action", payload, cookie=cookie,
                                      csrf=result["csrf"], origin=origin)
        assert status == 202, (action, body)


def test_queue_command_id_replays_and_rejects_altered_payload(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    command = {"action": "queue_clear", "queue_revision": 0,
               "queue_command_id": "clear-once"}

    first_status, first_body, _ = rig.request(
        "POST", "/api/action", command, cookie=cookie,
        csrf=result["csrf"], origin=origin)
    replay_status, replay_body, _ = rig.request(
        "POST", "/api/action", command, cookie=cookie,
        csrf=result["csrf"], origin=origin)
    altered_status, _, _ = rig.request(
        "POST", "/api/action", {**command, "queue_revision": 1}, cookie=cookie,
        csrf=result["csrf"], origin=origin)

    assert first_status == replay_status == 202
    assert decode(first_body) == decode(replay_body)
    assert altered_status == 409
    assert [action for action, _ in rig.calls].count("queue_clear") == 1


def test_bad_pin_is_rate_limited_per_client(rig):
    for _ in range(portal.MAX_ATTEMPTS):
        assert login(rig, "Z")[0] == 401
    assert login(rig)[0] == 401


def test_actions_require_same_origin_session_and_csrf(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    status, _, _ = rig.request("POST", "/api/action", {"action": "stop"},
                               cookie=cookie, origin=origin)
    assert status == 403
    status, _, _ = rig.request("POST", "/api/action", {"action": "stop"},
                               cookie=cookie, csrf=result["csrf"], origin="http://evil.example")
    assert status == 403
    status, body, _ = rig.request("POST", "/api/action", {"action": "stop"},
                                  cookie=cookie, csrf=result["csrf"], origin=origin)
    assert status == 202 and decode(body)["ok"]
    assert rig.calls == [("stop", {"action": "stop"})]


def test_phone_autogain_toggle_is_authenticated_and_requires_a_boolean(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    status, _, _ = rig.request(
        "POST", "/api/action", {"action": "music_autogain", "value": "true"},
        cookie=cookie, csrf=result["csrf"], origin=origin,
    )
    assert status == 400
    assert rig.calls == []
    status, body, _ = rig.request(
        "POST", "/api/action", {"action": "music_autogain", "value": True},
        cookie=cookie, csrf=result["csrf"], origin=origin,
    )
    assert status == 202 and decode(body)["ok"]
    assert rig.calls == [("music_autogain", {"action": "music_autogain", "value": True})]


@pytest.mark.parametrize("payload", [
    {"action": "cast", "file": "/etc/passwd"},
    {"action": ["stop"]},
    {"action": "seek", "value": float("nan")},
    {"action": "seek", "value": -1},
    {"action": "volume", "value": True},
    {"action": "volume", "value": 101},
])
def test_invalid_actions_are_rejected_before_dispatch(rig, payload):
    _, result, cookie = login(rig)
    status, _, _ = rig.request("POST", "/api/action", payload, cookie=cookie,
                               csrf=result["csrf"], origin=f"http://{rig.host}")
    assert status == 400
    assert rig.calls == []


def _envelope(rig, *, command_id="cmd-1", action="stop", payload=None):
    session_id, revision, _ = rig.server.fence.snapshot()
    return {
        "client_id": "phone-1", "command_id": command_id,
        "expected_session_id": session_id, "expected_revision": revision,
        "action": action, "payload": payload or {},
    }


def test_action_envelope_is_idempotent_and_fenced(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    envelope = _envelope(rig)
    status, body, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 202
    receipt = decode(body)
    assert receipt["ok"] and receipt["command_id"] == "cmd-1"
    assert rig.calls == [("stop", {"action": "stop"})]
    status, body, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 202 and decode(body) == receipt
    assert len(rig.calls) == 1


def test_altered_replay_and_stale_generation_are_rejected(rig):
    _, result, cookie = login(rig)
    origin = f"http://{rig.host}"
    envelope = _envelope(rig, action="seek", payload={"value": 1})
    status, _, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                               csrf=result["csrf"], origin=origin)
    assert status == 202
    altered = {**envelope, "payload": {"value": 2}}
    status, body, _ = rig.request("POST", "/api/action", altered, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 409 and decode(body)["conflict"] is True
    assert "revision" in decode(body)
    stale = {**_envelope(rig, command_id="cmd-2"),
             "expected_session_id": envelope["expected_session_id"],
             "expected_revision": envelope["expected_revision"]}
    status, body, _ = rig.request("POST", "/api/action", stale, cookie=cookie,
                                  csrf=result["csrf"], origin=origin)
    assert status == 409
    assert decode(body)["revision"] == rig.server.fence.snapshot()[1]
    assert len(rig.calls) == 1


@pytest.mark.parametrize("patch", [
    {"command_id": ""},
    {"command_id": "x" * 200},
    {"client_id": "bad id"},
    {"expected_session_id": "not-a-session"},
    {"expected_revision": -1},
    {"expected_revision": True},
    {"action": "cast"},
    {"payload": {"value": 1}},
])
def test_action_envelope_rejects_invalid_fields_before_dispatch(rig, patch):
    _, result, cookie = login(rig)
    envelope = _envelope(rig)
    envelope.update(patch)
    status, _, _ = rig.request("POST", "/api/action", envelope, cookie=cookie,
                               csrf=result["csrf"], origin=f"http://{rig.host}")
    assert status == 400
    assert rig.calls == []


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_expired_session_is_rejected_before_dispatch():
    clock = _Clock()
    rig = PortalRig(clock=clock)
    try:
        _, result, cookie = login(rig)
        clock.now = portal.SESSION_SECONDS + 1
        status, _, _ = rig.request("POST", "/api/action", _envelope(rig), cookie=cookie,
                                   csrf=result["csrf"], origin=f"http://{rig.host}")
        assert status == 403
        assert rig.calls == []
    finally:
        rig.close()


def test_invalid_origin_and_unknown_paths_fail_closed(rig):
    status, _, _ = rig.request("POST", "/api/login", {"pin": PIN},
                               origin="https://127.0.0.1")
    assert status == 403
    status, _, _ = rig.request("GET", "/private/file")
    assert status == 404


def test_pin_is_not_written_to_request_logs(rig, capsys):
    status, _, _ = rig.request("POST", "/api/login", {"pin": "BADPIN"},
                               origin=f"http://{rig.host}")
    assert status == 401
    output = capsys.readouterr()
    assert "BADPIN" not in output.out + output.err


def test_ephemeral_port_and_clean_shutdown():
    server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, lambda *_args: {})
    assert server.server_address[1] > 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.shutdown()
    thread.join(2)
    assert not thread.is_alive()
    server.server_close()


def test_friendly_hostname_is_allowed_when_configured():
    server = portal._PortalHTTPServer(("127.0.0.1", 0), PIN, lambda *_args: {},
                                      hostname="smoothcast-lounge")
    try:
        port = server.server_address[1]
        assert server.host_allowed(f"smoothcast-lounge.local:{port}")
        assert server.host_allowed("smoothcast-lounge.local")
        assert not server.host_allowed("evil.example")
    finally:
        server.server_close()


def test_copy_room_link_uses_only_the_current_listener_url():
    from textwrap import dedent

    from gui_source import main_window_methods

    namespace = {}
    exec("from __future__ import annotations\n"
         + dedent(main_window_methods()["_copy_portal_link"]), namespace)
    copy = namespace["_copy_portal_link"]
    clipboard = []
    window = SimpleNamespace(
        _portal=None, get_clipboard=lambda: SimpleNamespace(set=clipboard.append),
        toast=lambda _message: None,
    )
    copy(window, None)
    for url in ("http://192.168.1.20:8765/", "http://192.168.1.21:8766/"):
        window._portal = SimpleNamespace(url=url, pin=PIN)
        copy(window, None)
    window._portal = None
    copy(window, None)
    assert clipboard == ["http://192.168.1.20:8765/", "http://192.168.1.21:8766/"]


def test_application_wires_portal_into_home_screen_and_closes_it():
    from gui_source import main_window_methods
    methods = main_window_methods()
    assert "_build_portal_card" in methods
    card = methods["_build_portal_card"]
    assert "portal_status_label" in card and "portal_url_label" in card
    assert "portal_pin_label" in card and "portal_activity_label" in card
    assert "portal_peers_box" in card
    assert "local network" in card
    assert "GLib.idle_add(run)" in methods["_portal_dispatch"]
    assert "self._refresh_portal()" in methods["_start_window_timers"]
    assert "self._refresh_portal()" not in methods["__init__"]
    assert 'plan.run("portal", self._stop_portal)' in methods["_on_close"]
    assert "_sync_portal_activity_timer" in methods["_refresh_portal"]
    assert "room.snapshot()" in methods["_refresh_portal_activity"]
    assert "In room:" in methods["_refresh_portal_activity"]
    assert "peer_discovery_available" in methods["_refresh_portal_activity"]
    assert "peer_discovery_ui.refresh_peer_links" in methods["_refresh_portal_activity"]
    peer_ui = Path(__file__).resolve().parents[1] / "src" / "peer_discovery_ui.py"
    assert "peer['id'][:6]" in peer_ui.read_text(encoding="utf-8")
    assert "mark_early_cast" in methods["_reconcile_portal_casts"]
    queue_actions = methods["_portal_queue_action"]
    for operation in ("queue_add", "queue_remove", "queue_move", "queue_play",
                      "queue_clear", "next", "previous"):
        assert operation in queue_actions
    assert "self.clear_queue()" in queue_actions
    assert "queue_revision" in queue_actions
    assert "_portal_observe_queue()" in methods["_portal_handle"]
    assert "portal_queue_id" in methods["_portal_queue_status"]
    assert "queue_durations" in methods["_portal_queue_status"]


def test_queue_ids_are_stable_without_leaking_paths():
    from cast_portal_queue import portal_queue_id
    first = portal_queue_id("/media/Films/One.mkv")
    assert first == portal_queue_id("/media/Films/One.mkv")
    assert first != portal_queue_id("/media/Films/Two.mkv")
    assert "media" not in first and "/" not in first


def test_upload_http_flow_authenticates_chunks_resumes_and_dispatches_staged_path(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        status, _, _ = rig.request("POST", "/api/uploads", {"name": "clip.mp4", "size": 6},
                                   origin=f"http://{rig.host}")
        assert status == 403
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "../clip.mp4", "size": 5, "queue": False},
                                     cookie=cookie, csrf=login_result["csrf"], origin=origin)
        assert status == 201
        created = decode(raw)
        upload_id = created["id"]
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"ab", cookie=cookie,
            extra_headers={"Content-Range": "bytes 0-1/5"},
            content_type="application/octet-stream")
        assert status == 403  # unauthenticated chunks never reach the store
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"ab", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 0-1/5"},
            content_type="application/octet-stream")
        assert status == 200 and decode(raw)["received"] == 2
        # Reopen the portal with the original cookie, as a reloaded browser does.
        status, raw, _ = rig.request("GET", "/api/session", cookie=cookie)
        assert status == 200
        resumed = decode(raw)
        assert resumed["participant"]["id"] == login_result["participant"]["id"]
        status, raw, _ = rig.request(
            "GET", f"/api/uploads/{upload_id}", cookie=cookie)
        assert status == 200 and decode(raw)["received"] == 2
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"cde", cookie=cookie,
            csrf=resumed["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 2-4/5"},
            content_type="application/octet-stream")
        assert status == 200 and decode(raw)["complete"]
        status, raw, _ = rig.request("POST", f"/api/uploads/{upload_id}/complete", {},
                                     cookie=cookie, csrf=resumed["csrf"], origin=origin)
        assert status == 202 and decode(raw)["ok"]
        action, payload = rig.calls[-1]
        assert action == "cast_upload"
        assert Path(payload["path"]).read_bytes() == b"abcde"
        assert Path(payload["path"]).parent == uploads.root
    finally:
        rig.close()
        uploads.close()


def test_queue_only_upload_dispatches_queue_add_by_default(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        status, raw, _ = rig.request(
            "POST", "/api/uploads", {"name": "clip.mkv", "size": 6, "queue": True},
            cookie=cookie, csrf=login_result["csrf"], origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abcdef", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 0-5/6"},
            content_type="application/octet-stream")
        assert status == 200
        valid_video = SimpleNamespace(
            has_video=True, audio_streams=[], is_audio_only=False, duration=1.0,
        )
        with mock.patch("streamer.ffprobe", return_value=valid_video) as probe:
            status, raw, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
                csrf=login_result["csrf"], origin=origin)
            assert status == 202
            dispatch_count = len(rig.calls)
            status, _, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
                csrf=login_result["csrf"], origin=origin)
            assert status == 202
            assert len(rig.calls) == dispatch_count
            assert probe.call_count == 1
        assert decode(raw)["message"] == "Added to the shared queue."
        assert rig.calls[-1][0] == "queue_add"
        assert Path(rig.calls[-1][1]["path"]).read_bytes() == b"abcdef"
    finally:
        rig.close()
        uploads.close()


def test_queue_only_upload_rejects_invalid_media_without_dispatch(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        status, raw, _ = rig.request(
            "POST", "/api/uploads", {"name": "broken.mkv", "size": 6, "queue": True},
            cookie=cookie, csrf=login_result["csrf"], origin=origin,
        )
        assert status == 201
        upload_id = decode(raw)["id"]
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"broken", cookie=cookie,
            csrf=login_result["csrf"], origin=origin,
            extra_headers={"Content-Range": "bytes 0-5/6"},
            content_type="application/octet-stream",
        )
        assert status == 200
        with mock.patch("streamer.ffprobe", side_effect=RuntimeError("bad media")):
            status, body, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
                csrf=login_result["csrf"], origin=origin,
            )
        assert status == 422
        assert decode(body)["error"] == "The uploaded file is not readable media"
        assert rig.calls == []
        assert not (uploads.root / f"{upload_id}.mkv").exists()
    finally:
        rig.close()
        uploads.close()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required")
def test_phone_audio_upload_is_validated_and_forced_into_shared_queue(tmp_path):
    import portal_uploads

    audio = tmp_path / "guest-track.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.5", "-c:a", "libmp3lame", "-y", str(audio)],
        check=True, capture_output=True, timeout=20,
    )
    data = audio.read_bytes()
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request(
            "POST", "/api/uploads",
            {"name": audio.name, "size": len(data), "queue": False},
            cookie=cookie, csrf=csrf, origin=origin,
        )
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", data, cookie=cookie,
            csrf=csrf, origin=origin,
            extra_headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
            content_type="application/octet-stream",
        )
        assert status == 200 and decode(raw)["ready_to_cast"] is False
        status, raw, _ = rig.request(
            "POST", f"/api/uploads/{upload_id}/complete", {"queue": False},
            cookie=cookie, csrf=csrf, origin=origin,
        )
        assert status == 202 and decode(raw)["message"] == "Added to the shared queue."
        action, payload = rig.calls[-1]
        assert action == "queue_add"
        assert Path(payload["path"]).read_bytes() == data
    finally:
        rig.close()
        uploads.close()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required")
def test_three_phone_audio_uploads_join_shared_queue_once_each(tmp_path):
    import portal_uploads
    import cast_portal_queue

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    queue = []
    host = SimpleNamespace(
        _portal=SimpleNamespace(server=SimpleNamespace(uploads=uploads)),
        busy=False,
        queue=queue,
        queue_durations={},
        now_playing=None,
        session=None,
        selected_index=None,
        _enqueue=lambda paths: queue.extend(paths),
        _remove_queue=lambda index: queue.pop(index),
    )
    host._portal_upload_path = MethodType(
        cast_portal_queue.PortalQueueMixin._portal_upload_path, host,
    )
    host._portal_observe_queue = MethodType(
        cast_portal_queue.PortalQueueMixin._portal_observe_queue, host,
    )
    host._portal_check_queue_revision = MethodType(
        cast_portal_queue.PortalQueueMixin._portal_check_queue_revision, host,
    )
    host._portal_queue_index = MethodType(
        cast_portal_queue.PortalQueueMixin._portal_queue_index, host,
    )
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        finalized = []
        for index, frequency in enumerate((330, 440, 550), start=1):
            audio = tmp_path / f"guest-track-{index}.mp3"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", f"sine=frequency={frequency}:duration=0.25", "-c:a",
                 "libmp3lame", "-y", str(audio)],
                check=True, capture_output=True, timeout=20,
            )
            data = audio.read_bytes()
            status, raw, _ = rig.request(
                "POST", "/api/uploads",
                {"name": audio.name, "size": len(data), "queue": False},
                cookie=cookie, csrf=csrf, origin=origin,
            )
            assert status == 201
            upload_id = decode(raw)["id"]
            status, raw, _ = rig.request(
                "PUT", f"/api/uploads/{upload_id}", data, cookie=cookie,
                csrf=csrf, origin=origin,
                extra_headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
                content_type="application/octet-stream",
            )
            assert status == 200 and decode(raw)["ready_to_cast"] is False
            status, raw, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {"queue": False},
                cookie=cookie, csrf=csrf, origin=origin,
            )
            assert status == 202 and decode(raw)["message"] == "Added to the shared queue."
            action, payload = rig.calls[-1]
            assert action == "queue_add"
            assert payload["early"] is False
            cast_portal_queue.PortalQueueMixin._portal_queue_action(
                host, "queue_add", payload,
            )
            finalized.append((upload_id, payload))

            # Retrying completion is accepted but never dispatches the same item again.
            call_count = len(rig.calls)
            status, _, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {"queue": False},
                cookie=cookie, csrf=csrf, origin=origin,
            )
            assert status == 202 and len(rig.calls) == call_count

        assert len(queue) == 3
        rows = cast_portal_queue.PortalQueueMixin._portal_queue_status(host)
        assert {row["title"] for row in rows} == {
            f"guest-track-{index}.mp3" for index in range(1, 4)
        }
        assert len({upload_id for upload_id, _payload in finalized}) == 3
        assert all(Path(payload["path"]).is_file() for _upload_id, payload in finalized)
        assert all(action != "cast_upload" for action, _payload in rig.calls)
        active_path = queue[0]
        active_session = SimpleNamespace(state=object())
        host.now_playing = active_path
        host.session = active_session
        host.selected_index = 0
        cast_portal_queue.PortalQueueMixin._portal_queue_action(host, "queue_remove", {
            "id": rows[0]["id"], "queue_revision": host._portal_queue_revision,
        })
        assert active_path not in queue
        assert host.now_playing == active_path and host.session is active_session
        assert Path(active_path).is_file()
        cast_portal_queue.PortalQueueMixin._portal_queue_status(host)
        queue.clear()
        assert cast_portal_queue.PortalQueueMixin._portal_queue_status(host) == []
        assert host._portal_queue_display_names == {}
    finally:
        rig.close()
        uploads.close()


def test_upload_defaults_to_queue_when_intent_is_omitted(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads", early_cast_min_bytes=1)
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "clip.mkv", "size": 6},
                                     cookie=cookie, csrf=csrf, origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        body = decode(raw)
        assert status == 200 and body["ready_to_cast"] is False
        assert rig.calls == []
        status, _, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"def", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 3-5/6"},
            content_type="application/octet-stream")
        assert status == 200
        valid_video = SimpleNamespace(
            has_video=True, audio_streams=[], is_audio_only=False, duration=1.0,
        )
        with mock.patch("streamer.ffprobe", return_value=valid_video):
            status, _, _ = rig.request(
                "POST", f"/api/uploads/{upload_id}/complete", {}, cookie=cookie,
                csrf=csrf, origin=origin)
        assert status == 202
        assert rig.calls[-1][0] == "queue_add"
        assert Path(rig.calls[-1][1]["path"]).read_bytes() == b"abcdef"
    finally:
        rig.close()
        uploads.close()


def test_streamable_upload_starts_casting_before_it_finishes(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads", early_cast_min_bytes=1)
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        origin = f"http://{rig.host}"
        csrf = login_result["csrf"]
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "clip.mkv", "size": 6, "queue": False},
                                     cookie=cookie, csrf=csrf, origin=origin)
        assert status == 201
        upload_id = decode(raw)["id"]
        status, raw, _ = rig.request(
            "PUT", f"/api/uploads/{upload_id}", b"abc", cookie=cookie, csrf=csrf,
            origin=origin, extra_headers={"Content-Range": "bytes 0-2/6"},
            content_type="application/octet-stream")
        body = decode(raw)
        assert status == 200 and body["ready_to_cast"] is True
        assert body["early_cast_accepted"] is True
        assert "cast_path" not in body  # host-only staged path must stay private
        action, payload = rig.calls[-1]
        assert action == "cast_upload" and payload["early"] is True
        assert payload["upload_id"] == upload_id
        assert uploads.by_id(upload_id)["phase"] == "casting"
        # Finalize still dispatches; the GUI dedupes by upload id.
        rig.request("PUT", f"/api/uploads/{upload_id}", b"def", cookie=cookie, csrf=csrf,
                    origin=origin, extra_headers={"Content-Range": "bytes 3-5/6"},
                    content_type="application/octet-stream")
        rig.request("POST", f"/api/uploads/{upload_id}/complete", {},
                    cookie=cookie, csrf=csrf, origin=origin)
        action, payload = rig.calls[-1]
        assert action == "cast_upload" and payload["early"] is False
    finally:
        rig.close()
        uploads.close()


def test_page_build_is_embedded_and_status_session_expose_schema(rig):
    html = portal._page().decode("utf-8")
    assert portal.page_build() in html
    assert "__SC_BUILD__" not in html
    assert "__SC_SCHEMA__" not in html
    assert 'id="updateNotice"' in html
    assert 'id="reloadNow"' in html
    assert '"X-SmoothCast-Client-Build":PAGE_BUILD' in html
    status, session, cookie = login(rig)
    assert status == 200
    assert session["build"] == portal.page_build()
    assert session["client_schema"] == portal.CLIENT_SCHEMA
    status, body, _ = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 200
    assert decode(body)["build"] == portal.page_build()
    status, body, _ = rig.request("GET", "/api/session", cookie=cookie)
    assert status == 200
    assert decode(body)["client_schema"] == portal.CLIENT_SCHEMA


def test_stale_browser_mutations_fail_before_dispatch(rig):
    origin = f"http://{rig.host}"
    stale = {
        "X-SmoothCast-Client-Schema": "0",
        "X-SmoothCast-Client-Build": "old-build",
    }
    status, body, _ = rig.request(
        "POST", "/api/login", {"name": "Sam", "pin": PIN},
        origin=origin, extra_headers=stale,
    )
    assert status == 409
    assert decode(body)["code"] == "client_reload_required"
    assert not rig.server.room.participants
    status, body, _ = rig.request(
        "POST", "/api/login", {"name": "Sam", "pin": PIN},
        origin=origin, extra_headers={"Sec-Fetch-Mode": "cors"},
    )
    assert status == 409
    assert decode(body)["code"] == "client_reload_required"
    status, data, cookie = login(rig)
    assert status == 200
    status, body, _ = rig.request(
        "POST", "/api/action", {"action": "play_pause"},
        cookie=cookie, csrf=data["csrf"], origin=origin, extra_headers=stale,
    )
    assert status == 409
    assert decode(body)["code"] == "client_reload_required"
    assert rig.calls == []
    status, body, _ = rig.request(
        "POST", "/api/action", {"action": "play_pause"},
        cookie=cookie, csrf=data["csrf"], origin=origin,
        extra_headers={
            "X-SmoothCast-Client-Schema": str(portal.CLIENT_SCHEMA),
            "X-SmoothCast-Client-Build": portal.page_build(),
        },
    )
    assert status == 202
    assert len(rig.calls) == 1


def test_authenticated_guest_flood_gets_429_and_other_guest_stays_responsive(rig):
    _status, first, first_cookie = login(rig, name="Noisy")
    _status, second, second_cookie = login(rig, name="Quiet")
    origin = f"http://{rig.host}"
    statuses = []
    for _ in range(40):
        status, data, headers = rig.request(
            "POST", "/api/action", {"action": "stop"}, cookie=first_cookie,
            csrf=first["csrf"], origin=origin,
        )
        statuses.append(status)
        if status == 429:
            assert int(headers["Retry-After"]) >= 1
            assert decode(data)["ok"] is False
    assert 202 in statuses and 429 in statuses
    before = len(rig.calls)
    status, data, _ = rig.request(
        "POST", "/api/action", {"action": "stop"}, cookie=second_cookie,
        csrf=second["csrf"], origin=origin,
    )
    assert status == 202 and decode(data)["ok"]
    assert len(rig.calls) == before + 1


def test_authenticated_read_rate_limit_does_not_block_room_recovery(rig):
    _status, data, cookie = login(rig, name="Reader")
    statuses = [rig.request("GET", "/api/status", cookie=cookie)[0] for _ in range(30)]
    assert 200 in statuses and 429 in statuses
    status, body, headers = rig.request("GET", "/api/status", cookie=cookie)
    assert status == 429
    assert int(headers["Retry-After"]) >= 1
    # Existing cookie and PIN remain valid. Another participant can read.
    _, other, other_cookie = login(rig, name="Other")
    assert rig.request("GET", "/api/status", cookie=other_cookie)[0] == 200
    assert other["csrf"]


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_phone_volume_changes_coalesce_and_preserve_pending_edit():
    source = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    script = source[source.index('for(const id of ["seek","volume"])'):
                    source.index('$("nameForm").addEventListener', source.index('for(const id of ["seek","volume"])'))]
    harness = r"""
const assert = require("node:assert/strict");
const elements=new Map();
function $(id){
  if(!elements.has(id))elements.set(id,{value:0,textContent:"",listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn}});
  return elements.get(id);
}
const editingControls=new Set(),calls=[],timers=[];
const act=(...args)=>calls.push(args);
let now=1000;
Date.now=()=>now;
const setTimeout=(fn,delay)=>{timers.push({fn,delay});return timers.length};
"""
    scenario = r"""
$("volume").value=33;
$("volume").listeners.pointerdown();
$("volume").listeners.input();
assert.equal(editingControls.has("volume"),true);
$("volume").value=48;
$("volume").listeners.input();
assert.equal(timers.length,1,"rapid drag is one scheduled request");
timers.shift().fn();
assert.deepEqual(calls,[["volume",48]]);
assert.equal($("volumeText").textContent,"48%");
now+=60;
$("volume").value=62;
$("volume").listeners.input();
$("volume").value=64;
$("volume").listeners.change();
assert.equal(editingControls.has("volume"),false);
assert.equal(timers.length,1);
assert.equal(timers[0].delay,90,"last write is sent no sooner than 150 ms");
timers.shift().fn();
assert.deepEqual(calls,[["volume",48],["volume",64]]);
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   text=True, check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node.js")
def test_phone_inflight_controls_keep_latest_intent_visible():
    source = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    script = source[source.index("async function act(action,value,extra={})"):
                    source.index('$("clearQueue").addEventListener', source.index("async function act(action,value,extra={})"))]
    harness = r"""
const assert=require("node:assert/strict");
const pendingControls=new Map(),messages=[],requests=[];
const showError=(id,value)=>messages.push(value);
let busy=false,csrf="session",stalePage=false,rateDelayUntil=0,queueRevision=0,queueCommandSeq=0;
let statusRequest=null;
let release=null,refreshes=0;
const refresh=()=>refreshes++;
const post=async (url,body)=>{requests.push(body);return await new Promise(resolve=>{release=resolve})};
"""
    scenario = r"""
(async()=>{
  const first=act("stop");
  await act("seek",10);
  await act("seek",20);
  assert.equal(requests.length,1);
  assert.equal(pendingControls.size,1,"latest seek replaces earlier unsent seek");
  assert.match(messages.at(-1),/waiting/i);
  release({message:"Stopped"});
  await first;
  assert.equal(requests.length,2);
  assert.deepEqual(requests[1],{action:"seek",value:20});
  release({message:"Seeked"});
  for(let i=0;i<5;i++)await Promise.resolve();
  assert.equal(pendingControls.size,0);
  assert.equal(refreshes,1);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   text=True, check=True, timeout=10)


def test_status_refresh_does_not_overwrite_an_active_slider():
    source = portal._HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    assert 'if(!editingControls.has("seek")){' in source
    assert 'if(!editingControls.has("volume")){' in source
    assert 'queueElement.addEventListener("click",event=>' in source


@pytest.mark.parametrize(
    ("method", "stage", "expected_status", "expected_text"),
    [
        ("POST", "prepare", 507, "Not enough space"),
        ("PUT", "store", 408, "Resume from the saved position"),
        ("POST", "finalise", 503, "Host could not finalise"),
    ],
)
def test_upload_storage_failure_is_actionable_and_preserves_resume(
    tmp_path, method, stage, expected_status, expected_text
):
    import errno
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    rig = PortalRig(uploads)
    try:
        _, login_result, cookie = login(rig)
        auth = {"cookie": cookie, "csrf": login_result["csrf"], "origin": f"http://{rig.host}"}
        metadata = {"name": "clip.mp4", "size": 3, "queue": False}
        if stage == "prepare":
            with mock.patch.object(uploads, "create", side_effect=OSError(errno.ENOSPC, "private path")):
                status, raw, _ = rig.request(method, "/api/uploads", metadata, **auth)
            assert decode(raw)["code"] == "upload.disk_full"
        else:
            status, raw, _ = rig.request("POST", "/api/uploads", metadata, **auth)
            assert status == 201
            path = "/api/uploads/" + decode(raw)["id"]
            chunk = {"extra_headers": {"Content-Range": "bytes 0-2/3"},
                     "content_type": "application/octet-stream"}
            if stage == "store":
                with mock.patch.object(uploads, "append", side_effect=TimeoutError("slow connection")):
                    status, raw, _ = rig.request(method, path, b"abc", **auth, **chunk)
                assert decode(rig.request("GET", path, cookie=cookie)[1])["received"] == 0
            else:
                assert rig.request("PUT", path, b"abc", **auth, **chunk)[0] == 200
                with mock.patch.object(uploads, "finalize", side_effect=OSError(errno.EIO, "private path")):
                    status, raw, _ = rig.request(method, path + "/complete", {}, **auth)
                assert decode(rig.request("GET", path, cookie=cookie)[1])["received"] == 3
            assert not any(action == "cast_upload" for action, _ in rig.calls)
        assert status == expected_status
        assert expected_text in decode(raw)["error"]
        assert "private path" not in decode(raw)["error"]
    finally:
        rig.close()
        uploads.close()


def test_cast_upload_submission_failure_can_retry_same_upload_id(tmp_path):
    """A synchronous cast failure must not become an accepted upload."""
    from textwrap import dedent

    from gui_source import main_window_methods

    namespace = {"portal": portal, "time": time}
    exec(dedent(main_window_methods()["_portal_handle"]), namespace)
    handle = namespace["_portal_handle"]
    path = tmp_path / "clip.mkv"
    path.write_bytes(b"test")
    cast = mock.Mock(side_effect=[RuntimeError("submission failed"), None])
    host = SimpleNamespace(
        _closing=False, busy=False, _portal_queue_action=lambda *_: None,
        _portal_upload_path=lambda _: path, set_selection=mock.Mock(),
        _cast_path=cast,
    )
    payload = {"upload_id": "retry-me", "early": True}
    with pytest.raises(RuntimeError, match="submission failed"):
        handle(host, "cast_upload", payload)
    assert "retry-me" not in host._portal_accepted_uploads
    assert "retry-me" not in host._portal_cast_uploads
    assert host._portal_early is False

    payload["early"] = False
    handle(host, "cast_upload", payload)
    assert "retry-me" in host._portal_accepted_uploads
    handle(host, "cast_upload", payload)
    assert cast.call_count == 2


def test_upload_receipt_reports_declined_early_cast_without_leaking_path(tmp_path):
    import portal_uploads

    uploads = portal_uploads.UploadManager(tmp_path / "uploads", early_cast_min_bytes=1)
    rig = PortalRig(uploads)
    try:
        _, guest, cookie = login(rig)
        auth = {"cookie": cookie, "csrf": guest["csrf"], "origin": f"http://{rig.host}"}
        status, raw, _ = rig.request("POST", "/api/uploads",
                                     {"name": "clip.mkv", "size": 6, "queue": False}, **auth)
        assert status == 201
        path = "/api/uploads/" + decode(raw)["id"]
        with mock.patch.object(rig.server, "dispatch", side_effect=portal.PortalRequestError(409, "Busy")):
            status, raw, _ = rig.request(
                "PUT", path, b"abc", **auth,
                extra_headers={"Content-Range": "bytes 0-2/6"},
                content_type="application/octet-stream")
        receipt = decode(raw)
        assert status == 200 and receipt["received"] == 3
        assert receipt["early_cast_accepted"] is False
        assert "cast_path" not in receipt
        assert uploads.by_id(receipt["id"])["phase"] == "receiving"
        status, raw, _ = rig.request("PUT", path, b"def", **auth,
                                     extra_headers={"Content-Range": "bytes 3-5/6"},
                                     content_type="application/octet-stream")
        assert status == 200 and decode(raw)["received"] == 6
        assert rig.request("POST", path + "/complete", {}, **auth)[0] == 202
        assert rig.calls[-1][0] == "cast_upload"
    finally:
        rig.close()
        uploads.close()
