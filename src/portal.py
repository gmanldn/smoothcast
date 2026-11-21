"""Small, PIN-protected LAN dashboard hosted by the GTK application.

The portal uses Python's standard-library HTTP server so SmoothCast adds no
web framework or runtime dependency. GTK callbacks are supplied by the caller
and are dispatched onto the GTK main context by the application layer.
"""
from __future__ import annotations

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import ipaddress
import json
import math
import secrets
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import portal_uploads


PIN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PIN_LENGTH = 6
MAX_BODY = 2048
SESSION_SECONDS = 8 * 60 * 60
ATTEMPT_WINDOW_SECONDS = 60
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
REQUEST_TIMEOUT = 5


class PortalError(RuntimeError):
    """Portal configuration, startup, or dispatch failure."""


class PortalRequestError(Exception):
    """A safe request rejection with an HTTP status and user-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def new_pin(*, choice=secrets.choice) -> str:
    """Return a six-character PIN using a cryptographically secure chooser."""
    return "".join(choice(PIN_ALPHABET) for _ in range(PIN_LENGTH))


def _page() -> bytes:
    return _HTML.encode("utf-8")


class _PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, pin: str, dispatch: Callable, *, clock=time.monotonic,
                 uploads: portal_uploads.UploadManager | None = None) -> None:
        super().__init__(address, _Handler)
        self.pin = pin
        self.dispatch = dispatch
        self.uploads = uploads
        self.clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[str, float]] = {}
        self._attempts: dict[str, deque[float]] = {}
        self._lockouts: dict[str, float] = {}
        self._allowed_hosts = {
            f"{self.server_address[0]}:{self.server_address[1]}".lower(),
            f"127.0.0.1:{self.server_address[1]}",
            f"localhost:{self.server_address[1]}",
        }

    def host_allowed(self, host: str) -> bool:
        return bool(host) and host.lower() in self._allowed_hosts

    def origin_allowed(self, origin: str, host: str) -> bool:
        try:
            parsed = urlsplit(origin)
            return (parsed.scheme == "http" and parsed.netloc.lower() == host.lower()
                    and not parsed.username and not parsed.password
                    and not parsed.path and not parsed.query and not parsed.fragment
                    and self.host_allowed(host))
        except ValueError:
            return False

    @staticmethod
    def _session_key(token: str) -> str:
        return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()

    def create_session(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        with self._lock:
            now = self.clock()
            for key, (_, expiry) in list(self._sessions.items()):
                if expiry <= now:
                    self._sessions.pop(key, None)
            while len(self._sessions) >= 128:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[self._session_key(token)] = (csrf, self.clock() + SESSION_SECONDS)
        return token, csrf

    def session_csrf(self, token: str | None) -> str | None:
        if not token:
            return None
        key = self._session_key(token)
        now = self.clock()
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            csrf, expiry = session
            if expiry <= now:
                self._sessions.pop(key, None)
                return None
            return csrf

    def pin_allowed(self, client: str, pin: str) -> bool:
        now = self.clock()
        with self._lock:
            for address, expiry in list(self._lockouts.items()):
                if expiry <= now:
                    self._lockouts.pop(address, None)
                    self._attempts.pop(address, None)
            if len(self._attempts) > 512:
                for address in list(self._attempts)[:len(self._attempts) - 512]:
                    self._attempts.pop(address, None)
            until = self._lockouts.get(client, 0.0)
            if until > now:
                return False
            attempts = self._attempts.setdefault(client, deque())
            while attempts and now - attempts[0] >= ATTEMPT_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= MAX_ATTEMPTS:
                self._lockouts[client] = now + LOCKOUT_SECONDS
                return False
            if hmac.compare_digest(pin.encode("utf-8"), self.pin.encode("utf-8")):
                attempts.clear()
                self._lockouts.pop(client, None)
                return True
            attempts.append(now)
            return False


class _Handler(BaseHTTPRequestHandler):
    server: _PortalHTTPServer
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT
    server_version = "SmoothCastPortal"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths, cookies, PINs, and remote addresses can contain secrets
        # or private LAN details; the portal deliberately emits no access log.
        return

    def _send(self, status: int, payload: dict | bytes, *, content_type="application/json",
              cookie: str | None = None) -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            return
        self.close_connection = True

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"ok": False, "error": message})

    def _safe_origin(self, *, required: bool) -> bool:
        host = self.headers.get("Host", "")
        if not self.server.host_allowed(host):
            return False
        origin = self.headers.get("Origin", "")
        return self.server.origin_allowed(origin, host) if required else (
            not origin or self.server.origin_allowed(origin, host)
        )

    def _body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise PortalRequestError(400, "Invalid request body") from exc
        if length < 0:
            raise PortalRequestError(400, "Invalid request body")
        if length > MAX_BODY:
            raise PortalRequestError(413, "Request is too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PortalRequestError(400, "Request must be JSON") from exc
        if not isinstance(value, dict):
            raise PortalRequestError(400, "Request must be a JSON object")
        return value

    def _cookie_token(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sc_portal_session":
                return value
        return None

    def _path(self) -> str:
        try:
            return urlsplit(self.path).path
        except ValueError:
            return ""

    def _authenticated(self, *, csrf: bool = False) -> bool:
        if not self._safe_origin(required=csrf):
            return False
        expected = self.server.session_csrf(self._cookie_token())
        if expected is None:
            return False
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if not self._safe_origin(required=False):
            return self._error(400, "Invalid host")
        if path in {"/", "/index.html"}:
            return self._send(200, _page(), content_type="text/html; charset=utf-8")
        if path == "/api/status":
            if not self._authenticated():
                return self._error(401, "Enter the PIN shown in SmoothCast")
            try:
                state = self.server.dispatch("status", {})
            except Exception:
                return self._error(503, "SmoothCast is not ready to report playback state")
            return self._send(200, {"ok": True, "state": state})
        upload_id = self._upload_route(path)
        if upload_id and self._authenticated():
            if self.server.uploads is None:
                return self._error(503, "Upload storage is unavailable")
            try:
                return self._send(200, {"ok": True, **self.server.uploads.status(
                    self._cookie_token() or "", upload_id)})
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
        if upload_id:
            return self._error(401, "Enter the PIN shown in SmoothCast")
        return self._error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        path = self._path()
        if path == "/api/uploads":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            try:
                if self.server.uploads is None:
                    return self._error(503, "Upload storage is unavailable")
                body = self._body()
                created = self.server.uploads.create(
                    self._cookie_token() or "", body.get("name"), body.get("size"))
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
            return self._send(201, {"ok": True, **created})
        upload_id = self._upload_complete_route(path)
        if upload_id:
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            try:
                if self.server.uploads is None:
                    return self._error(503, "Upload storage is unavailable")
                self._body()
                media_path, name, dispatch = self.server.uploads.finalize(
                    self._cookie_token() or "", upload_id)
                if dispatch:
                    try:
                        self.server.dispatch("cast_upload", {
                            "path": str(media_path), "name": name,
                            "upload_id": upload_id,
                        })
                    except PortalRequestError:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise
                    except Exception as exc:
                        self.server.uploads.finish_dispatch(
                            self._cookie_token() or "", upload_id, accepted=False)
                        raise PortalRequestError(503, "SmoothCast could not start this upload") from exc
                return self._send(202, {"ok": True, "message": "Upload received; casting started."})
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            except portal_uploads.UploadError as exc:
                return self._error(exc.status, exc.message)
        if not self._safe_origin(required=True):
            return self._error(403, "Request origin is not allowed")
        try:
            body = self._body()
        except PortalRequestError as exc:
            return self._error(exc.status, exc.message)
        if path == "/api/login":
            pin = body.get("pin")
            if not isinstance(pin, str):
                pin = ""
            client = self.client_address[0]
            if not self.server.pin_allowed(client, pin):
                return self._error(401, "Incorrect PIN or too many attempts")
            token, csrf = self.server.create_session()
            cookie = (f"sc_portal_session={token}; Path=/; HttpOnly; SameSite=Strict; "
                      f"Max-Age={SESSION_SECONDS}")
            return self._send(200, {"ok": True, "csrf": csrf}, cookie=cookie)
        if path == "/api/action":
            if not self._authenticated(csrf=True):
                return self._error(403, "Session expired or request token invalid")
            action = body.get("action")
            if not isinstance(action, str) or action not in {
                    "play_pause", "stop", "seek", "volume"}:
                return self._error(400, "Unsupported action")
            if action == "seek":
                value = body.get("value")
                if isinstance(value, bool) or not isinstance(value, (float, int)):
                    return self._error(400, "Seek position must be a number")
                if not math.isfinite(float(value)) or not 0 <= float(value) <= 24 * 60 * 60:
                    return self._error(400, "Seek position is out of range")
                body["value"] = float(value)
            if action == "volume":
                value = body.get("value")
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                    return self._error(400, "Volume must be from 0 to 100")
            try:
                result = self.server.dispatch(action, body)
            except PortalRequestError as exc:
                return self._error(exc.status, exc.message)
            except Exception:
                return self._error(503, "SmoothCast could not accept that command")
            return self._send(202, {"ok": True, "message": result or "Command accepted"})
        return self._error(404, "Not found")

    @staticmethod
    def _upload_route(path: str) -> str | None:
        prefix = "/api/uploads/"
        if path.startswith(prefix) and "/" not in path[len(prefix):]:
            return path[len(prefix):]
        return None

    @staticmethod
    def _upload_complete_route(path: str) -> str | None:
        prefix, suffix = "/api/uploads/", "/complete"
        if path.startswith(prefix) and path.endswith(suffix):
            upload_id = path[len(prefix):-len(suffix)]
            if upload_id and "/" not in upload_id:
                return upload_id
        return None

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.headers.get("Transfer-Encoding"):
            return self._error(400, "Chunked transfer encoding is not supported")
        raw_length = self.headers.get("Content-Length")
        if self.server.uploads is None:
            return self._error(503, "Upload storage is unavailable")
        try:
            length = int(raw_length or "")
        except ValueError:
            return self._error(400, "Invalid upload chunk length")
        if length <= 0 or length > portal_uploads.CHUNK_SIZE:
            return self._error(413, "Upload chunks must be at most 2 MiB")
        try:
            result = self.server.uploads.append(
                self._cookie_token() or "", upload_id,
                self.headers.get("Content-Range", ""), length, self.rfile)
            return self._send(200, {"ok": True, **result})
        except portal_uploads.UploadError as exc:
            self.close_connection = True
            return self._error(exc.status, exc.message)
        except OSError:
            self.close_connection = True
            return self._error(507, "Could not store this upload chunk")

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authenticated(csrf=True):
            return self._error(403, "Session expired or request token invalid")
        upload_id = self._upload_route(self._path())
        if not upload_id:
            return self._error(404, "Not found")
        if self.server.uploads is None:
            return self._error(503, "Upload storage is unavailable")
        try:
            self.server.uploads.cancel(self._cookie_token() or "", upload_id)
            return self._send(200, {"ok": True})
        except portal_uploads.UploadError as exc:
            return self._error(exc.status, exc.message)

    def _not_allowed(self) -> None:
        self._error(405, "Method not allowed")

    do_PATCH = do_OPTIONS = do_HEAD = _not_allowed  # noqa: N815


class Portal:
    """One-interface LAN portal with a per-run PIN and clean thread shutdown."""

    def __init__(self, bind_ip: str, dispatch: Callable, *, pin: str | None = None,
                 uploads: portal_uploads.UploadManager | None = None) -> None:
        if not isinstance(bind_ip, str):
            raise PortalError("A private IPv4 address is required")
        try:
            address = ipaddress.IPv4Address(bind_ip)
        except ValueError as exc:
            raise PortalError("A private IPv4 address is required") from exc
        private_nets = (ipaddress.ip_network("10.0.0.0/8"),
                        ipaddress.ip_network("172.16.0.0/12"),
                        ipaddress.ip_network("192.168.0.0/16"))
        if not any(address in network for network in private_nets):
            raise PortalError("Refusing to host the LAN portal on a non-private interface")
        self.pin = pin or new_pin()
        if len(self.pin) != PIN_LENGTH or any(char not in PIN_ALPHABET for char in self.pin):
            raise PortalError("PIN must contain six characters from the portal alphabet")
        self.bind_ip = str(address)
        self.uploads = uploads or portal_uploads.UploadManager()
        self.server = _PortalHTTPServer((self.bind_ip, 0), self.pin, dispatch,
                                        uploads=self.uploads)
        self.port = int(self.server.server_address[1])
        self.url = f"http://{self.bind_ip}:{self.port}/"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.1},
                                       name="smoothcast-portal", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()
        if self.server.uploads is not None:
            self.server.uploads.close()


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>SmoothCast</title>
<style>
:root{font:16px system-ui,sans-serif;color-scheme:light dark;--bg:#101722;--card:#1c2735;--accent:#4d9de0;--muted:#b7c3d0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f4f7fb}main{max-width:760px;margin:auto;padding:20px}
h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.05rem;margin:0 0 12px}p{color:var(--muted);margin:.35rem 0}
section{background:var(--card);border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 8px 26px #0002}
label{display:block;margin:12px 0 6px}input,button{font:inherit;min-height:44px;border-radius:10px;border:1px solid #718096;padding:8px 12px}
input{width:100%;color:inherit;background:#121b27}button{background:var(--accent);color:white;border:0;font-weight:650;cursor:pointer}
button.secondary{background:#36475d}button:disabled,input:disabled{opacity:.55;cursor:not-allowed}.actions{display:flex;gap:8px;flex-wrap:wrap}
.actions button{flex:1 1 120px}.muted{color:var(--muted)}.big{font-size:1.35rem;font-weight:700}.row{display:flex;justify-content:space-between;gap:12px}
progress{width:100%;height:10px}ul{padding-left:24px}li{padding:4px 0;overflow-wrap:anywhere}#error{color:#ffb4a9;min-height:1.4em}
:focus-visible{outline:3px solid #ffd166;outline-offset:2px}@media(max-width:480px){main{padding:12px}section{padding:15px}}
</style></head><body><main><header><h1>SmoothCast</h1><p>Local playback dashboard</p></header>
<section id="login"><h2>Connect to SmoothCast</h2><p>Enter the six-character PIN shown on the SmoothCast home screen.</p>
<form id="loginForm"><label for="pin">Access PIN</label><input id="pin" name="pin" minlength="6" maxlength="6" autocomplete="one-time-code" required>
<p id="error" role="alert" aria-live="polite"></p><button type="submit">Connect</button></form></section>
<div id="dashboard" hidden><section><div class="row"><h2>Now Playing</h2><span id="state" class="muted">—</span></div>
<p id="title" class="big">Nothing playing</p><p id="receiver">Receiver: —</p><progress id="progress" max="1" value="0" aria-label="Playback progress"></progress>
<div class="row"><span id="elapsed">0:00</span><span id="duration">—</span></div>
<label for="seek">Seek</label><input id="seek" type="range" min="0" max="1" value="0" disabled>
<div class="actions"><button data-action="play_pause">Play / pause</button><button class="secondary" data-action="stop">Stop</button></div></section>
<section><h2>Volume</h2><label for="volume">Receiver volume</label><input id="volume" type="range" min="0" max="100" value="0" disabled><p id="volumeText">—</p></section>
<section><h2>Queue</h2><ul id="queue"><li>No videos queued</li></ul></section><p id="errorDash" role="status" aria-live="polite"></p></div>
<section id="uploadCard" hidden><h2>Cast a video from this device</h2><p>The selected video is securely copied to SmoothCast before it is cast.</p>
<label for="videoFile">Video file</label><input id="videoFile" type="file" accept="video/*,.mkv,.ts,.wmv">
<progress id="uploadProgress" max="1" value="0" aria-label="Upload progress"></progress><p id="uploadStatus" role="status" aria-live="polite"></p>
<div class="actions"><button id="uploadButton" type="button">Upload and cast</button><button id="cancelUpload" class="secondary" type="button" hidden>Cancel upload</button></div></section></main>
<script>
let csrf="",busy=false,uploading=false,cancelUpload=false;const $=id=>document.getElementById(id),showError=(id,msg)=>$(id).textContent=msg;
async function post(path,body){const r=await fetch(path,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
$("loginForm").addEventListener("submit",async e=>{e.preventDefault();showError("error","");try{const d=await post("/api/login",{pin:$("pin").value.trim().toUpperCase()});csrf=d.csrf;$("login").hidden=true;$("dashboard").hidden=false;$("uploadCard").hidden=false;refresh()}catch(err){showError("error",err.message)}});
function clock(s){if(s==null||!Number.isFinite(s))return "—";s=Math.floor(Math.max(0,s));return `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`}
async function refresh(){if(!csrf||busy)return;try{const r=await fetch("/api/status",{credentials:"same-origin",cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"Connection lost");const s=d.state||{};$("state").textContent=s.state||"—";$("title").textContent=s.title||"Nothing playing";$("receiver").textContent="Receiver: "+(s.receiver||"—");
const duration=Number(s.duration)||0,position=Number(s.position)||0;$("progress").max=duration||1;$("progress").value=Math.min(position,duration||position);$("seek").max=duration||1;$("seek").value=Math.min(position,duration||position);$("seek").disabled=!s.can_seek||!duration;$("elapsed").textContent=clock(position);$("duration").textContent=clock(duration);$("volume").disabled=s.volume==null;$("volume").value=s.volume||0;$("volumeText").textContent=s.volume==null?"Volume unavailable":`${s.volume}%`;
const queue=$("queue");queue.replaceChildren();if(!s.queue||!s.queue.length){const li=document.createElement("li");li.textContent="No videos queued";queue.append(li)}else for(const title of s.queue){const li=document.createElement("li");li.textContent=title;queue.append(li)}
document.querySelectorAll("[data-action]").forEach(b=>b.disabled=!!s.busy||!s.active);showError("errorDash","");}catch(err){showError("errorDash",err.message)}}
async function act(action,value){if(busy)return;busy=true;try{const body={action};if(value!==undefined)body.value=value;const result=await post("/api/action",body);showError("errorDash",result.message||"Command accepted")}catch(err){showError("errorDash",err.message)}finally{busy=false;refresh()}}
document.querySelectorAll("[data-action]").forEach(b=>b.addEventListener("click",()=>act(b.dataset.action)));
$("seek").addEventListener("change",()=>act("seek",Number($("seek").value)));$("volume").addEventListener("change",()=>act("volume",Number($("volume").value)));
async function uploadRequest(method,path,body,headers={}){const r=await fetch(path,{method,credentials:"same-origin",headers:{"X-CSRF-Token":csrf,...headers},body});const d=await r.json();if(!r.ok)throw Error(d.error||"Upload request failed");return d}
$("uploadButton").addEventListener("click",async()=>{const file=$("videoFile").files[0];if(!file||uploading)return;uploading=true;cancelUpload=false;$("uploadButton").disabled=true;$("cancelUpload").hidden=false;showError("uploadStatus","Preparing upload…");$("uploadProgress").value=0;let id="";try{let state=await uploadRequest("POST","/api/uploads",JSON.stringify({name:file.name,size:file.size}),{"Content-Type":"application/json"});id=state.id;const chunk=state.chunk_size;let offset=state.received;while(offset<file.size){if(cancelUpload)throw Error("Upload cancelled");const end=Math.min(offset+chunk,file.size),part=file.slice(offset,end);let accepted=false,lastError;for(let attempt=0;attempt<5&&!accepted;attempt++){try{state=await uploadRequest("PUT","/api/uploads/"+id,part,{"Content-Type":"application/octet-stream","Content-Range":`bytes ${offset}-${end-1}/${file.size}`});accepted=true}catch(err){lastError=err;if(attempt<4){await new Promise(resolve=>setTimeout(resolve,250*Math.pow(2,attempt)));try{state=await fetch("/api/uploads/"+id,{credentials:"same-origin",cache:"no-store"}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error||"Could not resume upload");return d});accepted=state.received>=end}catch(_){}}} }if(!accepted)throw lastError||Error("Upload could not be resumed");offset=state.received;$("uploadProgress").max=file.size;$("uploadProgress").value=offset;showError("uploadStatus",`Uploading ${file.name}: ${Math.floor(offset*100/file.size)}%`)}if(cancelUpload)throw Error("Upload cancelled");const result=await uploadRequest("POST","/api/uploads/"+id+"/complete","{}",{"Content-Type":"application/json"});showError("uploadStatus",result.message||"Upload complete") }catch(err){showError("uploadStatus",err.message);if(id&&cancelUpload){try{await uploadRequest("DELETE","/api/uploads/"+id)}catch(_){}}}finally{uploading=false;$("uploadButton").disabled=false;$("cancelUpload").hidden=true;$("videoFile").disabled=false}});
$("cancelUpload").addEventListener("click",()=>{cancelUpload=true;showError("uploadStatus","Cancelling upload…")});
setInterval(refresh,2000);
</script></body></html>"""
