"""In-process fake Cast and DLNA receivers (issue #278).

Test the playback state machine without a TV. Two fakes, each speaking the
*same boundary the production code uses*, so no production code is mocked:

``FakeDlnaRenderer``
    A real HTTP server that answers UPnP SOAP (AVTransport and
    RenderingControl) and serves a device description. ``dlna.play`` /
    ``pause`` / ``seek`` / ``info`` / ``volume`` and ``dlna.Session`` run
    unmodified against it over loopback.

``FakeCast``
    A stand-in ``catt`` executable. ``castctl`` (and everything built on it:
    ``cli_control``, ``streamer.Session.start_direct``) shells out to
    ``catt``, so the fake replaces ``castctl.CATT`` with a script that reads
    and writes a JSON state file. POSIX only (it is a shebang script).

Both are deterministic: playback position advances only when the test calls
``advance(seconds)``; nothing sleeps for real unless a *delay* is scripted.

Scripted behaviour (both fakes): fail the next N calls of an action with a
chosen error, delay an action, go offline, inspect every call made.

    with FakeDlnaRenderer() as tv:                  # starts a real server
        renderer = tv.renderer()
        with allow_loopback():
            dlna.set_uri(renderer, "http://10.0.0.2/m", "Film"); dlna.play(renderer)
        tv.fail("Pause", upnp_code=701)
        tv.advance(30)

    with FakeCast(tmpdir) as cast:                  # patches castctl.CATT
        cast.add_device("Living Room")
        cast.fail("pause", message="Failed to connect", times=1)
        castctl.pause("Living Room")                # -> (False, "Failed to connect")
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

if __name__ == "__main__":
    # Allow the documented standalone command to work outside an installed app.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import castctl
import dlna

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
CM = "urn:schemas-upnp-org:service:ConnectionManager:1"
AV = "urn:schemas-upnp-org:service:AVTransport:1"
RC = "urn:schemas-upnp-org:service:RenderingControl:1"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


@contextmanager
def allow_loopback():
    """The DLNA client only talks to private LAN hosts; let it reach 127.0.0.1."""
    real = dlna._private_host
    with mock.patch.object(
            dlna, "_private_host",
            side_effect=lambda host: host == "127.0.0.1" or real(host)):
        yield


# --------------------------------------------------------------------------- DLNA


class _Fault:
    def __init__(self, kind: str, times: int, **details) -> None:
        self.kind, self.times, self.details = kind, times, details


class FakeDlnaRenderer:
    """A UPnP MediaRenderer on 127.0.0.1 with a controllable transport state.

    Profiles are intentionally small receiver quirks, not new SmoothCast
    settings. ``fetch_media`` lets tests exercise the real DLNA media server
    from the receiver side without making requests to a real LAN device.
    """

    PROFILES = {
        "default": frozenset(),
        "strict-mime": frozenset({"strict-mime"}),
        "refuses-head": frozenset({"refuses-head"}),
        "no-range": frozenset({"no-range"}),
        "requires-dlna-headers": frozenset({"requires-dlna-headers"}),
        "closes-after-first-range": frozenset({"closes-after-first-range"}),
        "nonstandard-position": frozenset({"nonstandard-position"}),
    }

    def __init__(self, *, name: str = "Fake TV", model: str = "FakeDMR",
                 rendering_control: bool = True, duration: float = 3600.0,
                 buffer_on_play: bool = False, profile: str = "default") -> None:
        if profile not in self.PROFILES:
            raise ValueError(f"Unknown fake DLNA profile: {profile}")
        self.name, self.model = name, model
        self.profile = profile
        self.quirks = self.PROFILES[profile]
        self.rendering_control = rendering_control
        self.duration = float(duration)
        self.buffer_on_play = buffer_on_play    # Play -> TRANSITIONING until settle()
        self.state = "NO_MEDIA_PRESENT"
        self.position = 0.0
        self.uri = ""
        self.metadata = ""
        self.volume = 30
        self.muted = False
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.media_requests: list[tuple[str, str | None]] = []
        self._range_requests = 0
        self._faults: dict[str, list[_Fault]] = {}
        self._delays: dict[str, float] = {}
        self._lock = threading.RLock()
        self._ssdp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ssdp_socket.bind(("127.0.0.1", 0))
        self._ssdp_socket.settimeout(0.1)
        self._ssdp_stop = threading.Event()
        self._ssdp_thread = threading.Thread(target=self._serve_ssdp, daemon=True)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:     # keep test output quiet
                pass

            def do_GET(self) -> None:
                if self.path == "/desc.xml":
                    body = fake.description_xml()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/xml")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                fake._serve_soap(self, self.rfile.read(length))

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    # -- lifecycle
    def start(self) -> "FakeDlnaRenderer":
        # This is a test-only server; shorten BaseServer's default 500 ms
        # shutdown polling delay so suites with many profiles finish faster.
        self._thread = threading.Thread(
            target=lambda: self._httpd.serve_forever(poll_interval=0.05), daemon=True)
        self._thread.start()
        self._ssdp_thread.start()
        return self

    def stop(self) -> None:
        self._ssdp_stop.set()
        self._ssdp_socket.close()
        self._ssdp_thread.join(1)
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5)

    def __enter__(self) -> "FakeDlnaRenderer":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def location(self) -> str:
        return f"http://127.0.0.1:{self.port}/desc.xml"

    @property
    def ssdp_port(self) -> int:
        return self._ssdp_socket.getsockname()[1]

    def _serve_ssdp(self) -> None:
        while not self._ssdp_stop.is_set():
            try:
                payload, address = self._ssdp_socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            request = payload.decode("iso-8859-1", "replace").upper()
            if not request.startswith("M-SEARCH * HTTP/1.1"):
                continue
            if f"ST: {dlna.DEVICE_TYPE.upper()}" not in request and "ST: SSDP:ALL" not in request:
                continue
            response = (
                "HTTP/1.1 200 OK\r\n"
                "CACHE-CONTROL: max-age=120\r\n"
                "EXT:\r\n"
                f"LOCATION: {self.location}\r\n"
                "SERVER: SmoothCast-Test/1.0 UPnP/1.1 FakeDMR/1.0\r\n"
                f"ST: {dlna.DEVICE_TYPE}\r\n"
                f"USN: uuid:fake-{self.model}::{dlna.DEVICE_TYPE}\r\n\r\n"
            ).encode("ascii")
            try:
                self._ssdp_socket.sendto(response, address)
            except OSError:
                return

    def notify(self, destination: tuple[str, int], *, alive: bool = True) -> None:
        """Send one SSDP alive/byebye notification to an explicit test listener."""
        nts = "ssdp:alive" if alive else "ssdp:byebye"
        payload = (
            "NOTIFY * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            f"NT: {dlna.DEVICE_TYPE}\r\n"
            f"NTS: {nts}\r\n"
            f"LOCATION: {self.location}\r\n"
            f"USN: uuid:fake-{self.model}::{dlna.DEVICE_TYPE}\r\n\r\n"
        ).encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(payload, destination)

    def renderer(self) -> dlna.Renderer:
        """The client-side Renderer for this fake (use inside ``allow_loopback``)."""
        base = f"http://127.0.0.1:{self.port}"
        return dlna.Renderer(
            name=self.name, host="127.0.0.1", location=self.location,
            transport_url=f"{base}/upnp/control/av", transport_service=AV,
            rendering_url=f"{base}/upnp/control/render" if self.rendering_control else "",
            rendering_service=RC if self.rendering_control else "", model=self.model,
            connection_url=f"{base}/upnp/control/connection", connection_service=CM)

    def description_xml(self) -> bytes:
        rendering = (
            f"<service><serviceType>{RC}</serviceType>"
            "<controlURL>/upnp/control/render</controlURL></service>"
            if self.rendering_control else "")
        return (
            '<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
            "<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>"
            f"<friendlyName>{escape(self.name)}</friendlyName><modelName>{escape(self.model)}</modelName>"
            f"<serviceList><service><serviceType>{AV}</serviceType>"
            f"<controlURL>/upnp/control/av</controlURL></service>{rendering}"
            f"<service><serviceType>{CM}</serviceType>"
            "<controlURL>/upnp/control/connection</controlURL></service></serviceList>"
            "</device></root>").encode()

    # -- scripting
    def fail(self, action: str, *, http_status: int = 500, upnp_code: int | None = 501,
             description: str = "Action Failed", times: int = 1) -> None:
        """Make the next *times* calls of *action* return a UPnP fault."""
        self._faults.setdefault(action, []).append(
            _Fault("fault", times, status=http_status, code=upnp_code, description=description))

    def drop(self, action: str, times: int = 1) -> None:
        """Close the connection without answering (a crashed or rebooting TV)."""
        self._faults.setdefault(action, []).append(_Fault("drop", times))

    def delay(self, action: str, seconds: float) -> None:
        self._delays[action] = seconds

    def advance(self, seconds: float) -> None:
        """Move the fake clock: playing media progresses and may reach its end."""
        with self._lock:
            if self.state == "TRANSITIONING":
                self.state = "PLAYING"
            if self.state == "PLAYING":
                self.position += seconds
                if self.position >= self.duration:
                    self.position, self.state = self.duration, "STOPPED"

    def settle(self) -> None:
        """Finish buffering without advancing the clock."""
        with self._lock:
            if self.state == "TRANSITIONING":
                self.state = "PLAYING"

    def calls_of(self, action: str) -> list[dict[str, str]]:
        return [params for name, params in self.calls if name == action]

    def fetch_media(self, url: str, *, method: str = "GET",
                    range_header: str | None = None) -> tuple[int, dict[str, str], bytes]:
        """Fetch one loopback media response as this receiver would.

        The URL must point to a loopback server so an issue test cannot turn
        this test helper into an arbitrary network client. Profiles either
        tolerate SmoothCast's real response or return a bounded, useful error.
        """
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Fake DLNA media fetch is limited to loopback HTTP")
        method = method.upper()
        if method not in {"GET", "HEAD"}:
            raise ValueError("Fake DLNA media fetch supports only GET and HEAD")
        if method == "HEAD" and "refuses-head" in self.quirks:
            raise dlna.DlnaError("Fake receiver skips HEAD probes; retry the media URL with GET")
        headers: dict[str, str] = {}
        if method == "GET" and range_header and "no-range" not in self.quirks:
            headers["Range"] = range_header
        if method == "GET" and "Range" in headers and "closes-after-first-range" in self.quirks:
            if self._range_requests:
                raise dlna.DlnaError("Fake renderer closed the connection after its first range request")
            self._range_requests += 1
        self.media_requests.append((method, headers.get("Range")))
        request = Request(url, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                status = response.status
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                body = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            response_headers = {key.lower(): value for key, value in exc.headers.items()}
            body = exc.read(4096)
        except (OSError, URLError) as exc:
            raise dlna.DlnaError(f"Fake renderer could not fetch SmoothCast media: {exc}") from exc
        if len(body) > 2 * 1024 * 1024:
            raise dlna.DlnaError("Fake renderer media probe exceeded its 2 MiB limit")
        full_response = method == "HEAD" or "Range" not in headers
        if status not in ({200} if full_response else {206}):
            raise dlna.DlnaError(f"Fake renderer rejected media response with HTTP {status}")
        if "strict-mime" in self.quirks and response_headers.get("content-type", "").split(";", 1)[0] != "video/mp4":
            raise dlna.DlnaError("Fake renderer requires video/mp4 media (UPnP 714)")
        if "requires-dlna-headers" in self.quirks and not {
            "contentfeatures.dlna.org", "transfermode.dlna.org",
        }.issubset(response_headers):
            raise dlna.DlnaError("Fake renderer requires contentFeatures.dlna.org and transferMode.dlna.org")
        if "closes-after-first-range" in self.quirks and range_header and status != 206:
            raise dlna.DlnaError("Fake renderer requires byte-range media responses")
        return status, response_headers, body

    # -- SOAP
    def _take_fault(self, action: str) -> _Fault | None:
        queue = self._faults.get(action) or []
        if not queue:
            return None
        fault = queue[0]
        fault.times -= 1
        if fault.times <= 0:
            queue.pop(0)
        return fault

    def _serve_soap(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        # The SOAP body comes from the app under test, but still refuse DTDs and
        # entity declarations (billion-laughs) and oversized bodies outright.
        if len(body) > 256 * 1024 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            handler.send_error(400)
            return
        try:
            root = ET.fromstring(body)
            call = next(n for n in root.iter() if _local(n.tag) not in ("Envelope", "Body"))
        except (ET.ParseError, StopIteration):
            handler.send_error(400)
            return
        action = _local(call.tag)
        params = {_local(c.tag): (c.text or "") for c in call}
        service = call.tag.split("}")[0].lstrip("{") if "}" in call.tag else AV
        if action == "GetProtocolInfo" and (
            service != CM or handler.path != "/upnp/control/connection" or params
            or handler.headers.get("SOAPAction") != f'"{CM}#GetProtocolInfo"'
        ):
            handler.send_error(400)
            return
        with self._lock:
            self.calls.append((action, params))
            delay = self._delays.get(action, 0.0)
            fault = self._take_fault(action)
        if delay:
            time.sleep(delay)
        if fault is not None and fault.kind == "drop":
            handler.close_connection = True
            handler.connection.close()
            return
        if fault is not None:
            self._reply_fault(handler, fault.details["status"], fault.details["code"],
                              fault.details["description"])
            return
        with self._lock:
            result = self._perform(action, params)
        if isinstance(result, tuple):                  # ("fault", code, description)
            self._reply_fault(handler, 500, result[1], result[2])
            return
        fields = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in result.items())
        envelope = (
            f'<s:Envelope xmlns:s="{SOAP_ENV}"><s:Body><u:{action}Response xmlns:u="{service}">'
            f"{fields}</u:{action}Response></s:Body></s:Envelope>").encode()
        handler.send_response(200)
        handler.send_header("Content-Type", 'text/xml; charset="utf-8"')
        handler.send_header("Content-Length", str(len(envelope)))
        handler.end_headers()
        handler.wfile.write(envelope)

    @staticmethod
    def _reply_fault(handler, status: int, code, description: str) -> None:
        detail = (f"<detail><UPnPError xmlns=\"urn:schemas-upnp-org:control-1-0\"><errorCode>{code}"
                  f"</errorCode><errorDescription>{escape(description)}</errorDescription>"
                  "</UPnPError></detail>") if code is not None else ""
        envelope = (f'<s:Envelope xmlns:s="{SOAP_ENV}"><s:Body><s:Fault><faultcode>s:Client</faultcode>'
                    f"<faultstring>UPnPError</faultstring>{detail}</s:Fault></s:Body></s:Envelope>").encode()
        handler.send_response(status)
        handler.send_header("Content-Type", 'text/xml; charset="utf-8"')
        handler.send_header("Content-Length", str(len(envelope)))
        handler.end_headers()
        handler.wfile.write(envelope)

    def _perform(self, action: str, params: dict[str, str]):
        """Transport semantics; returns response fields or ('fault', code, text)."""
        if action == "GetProtocolInfo":
            return {"Source": "", "Sink": "http-get:*:video/mp4:*"}
        if action == "SetAVTransportURI":
            if "strict-mime" in self.quirks and 'protocolInfo="http-get:*:video/mp4:*"' not in params.get("CurrentURIMetaData", ""):
                return ("fault", 714, "Illegal MIME type; requires video/mp4")
            self.uri, self.metadata = params.get("CurrentURI", ""), params.get("CurrentURIMetaData", "")
            self.state, self.position = "STOPPED", 0.0
            return {}
        if action == "Play":
            if not self.uri:
                return ("fault", 701, "Transition not available")
            self.state = "TRANSITIONING" if self.buffer_on_play else "PLAYING"
            return {}
        if action == "Pause":
            if self.state not in ("PLAYING", "TRANSITIONING"):
                return ("fault", 701, "Transition not available")
            self.state = "PAUSED_PLAYBACK"
            return {}
        if action == "Stop":
            if not self.uri:
                return ("fault", 701, "Transition not available")
            self.state, self.position = "STOPPED", 0.0
            return {}
        if action == "Seek":
            if not self.uri:
                return ("fault", 701, "Transition not available")
            try:
                h, m, s = (int(x) for x in params.get("Target", "").split(":"))
            except ValueError:
                return ("fault", 711, "Illegal seek target")
            target = h * 3600 + m * 60 + s
            if target > self.duration:
                return ("fault", 711, "Illegal seek target")
            self.position = float(target)
            return {}
        if action == "GetTransportInfo":
            return {"CurrentTransportState": self.state, "CurrentTransportStatus": "OK",
                    "CurrentSpeed": "1"}
        if action == "GetPositionInfo":
            rel_time = _clock(self.position)
            if "nonstandard-position" in self.quirks:
                rel_time += ".500"
            return {"Track": 1, "TrackDuration": _clock(self.duration) if self.uri else "00:00:00",
                    "TrackURI": self.uri, "RelTime": rel_time,
                    "AbsTime": _clock(self.position)}
        if action == "GetVolume":
            return {"CurrentVolume": self.volume}
        if action == "SetVolume":
            self.volume = int(params.get("DesiredVolume", self.volume))
            return {}
        if action == "SetMute":
            self.muted = params.get("DesiredMute") == "1"
            return {}
        return ("fault", 401, "Invalid Action")


# --------------------------------------------------------------------------- Cast

_FAKE_CATT = r'''#!{python}
"""Fake catt: reads/writes {state} (JSON). Generated by tests/fake_receivers.py."""
import json, sys, time

STATE = {state!r}
argv = sys.argv[1:]
# The app runs catt commands concurrently (a background cast while polling
# info); serialise whole invocations so read-modify-write cannot lose updates.
import fcntl
_lock = open(STATE + ".lock", "w")
fcntl.flock(_lock, fcntl.LOCK_EX)
data = json.load(open(STATE))
device = None
if argv[:1] == ["-d"] and len(argv) >= 2:
    device, argv = argv[1], argv[2:]
sub = argv[0] if argv else ""
data.setdefault("log", []).append({{"device": device, "argv": argv}})

def save():
    tmp = STATE + ".tmp"
    json.dump(data, open(tmp, "w"))
    import os; os.replace(tmp, STATE)

def fail(message, code=1):
    save()
    sys.stderr.write(message + "\n")
    sys.exit(code)

for fault in data.get("faults", {{}}).get(sub, []):
    if fault.get("device") in (None, device) and fault.get("times", 1) > 0:
        fault["times"] -= 1
        fail(fault.get("message", "The command failed."), fault.get("exit", 1))
delay = data.get("delays", {{}}).get(sub, 0)
if delay:
    time.sleep(delay)

if sub == "scan":
    out = {{n: {{k: d[k] for k in ("host", "port", "model_name", "manufacturer", "uuid") if k in d}}
           for n, d in data["devices"].items() if d.get("online", True)}}
    save(); print(json.dumps(out)); sys.exit(0)
dev = data["devices"].get(device or "")
if dev is None or not dev.get("online", True):
    fail("Failed to find chromecast with name: %s" % device)
if sub == "info":
    save(); print(json.dumps({{k: v for k, v in dev.items() if k not in ("online", "host", "port", "uuid", "model_name", "manufacturer")}}))
elif sub == "play":
    dev["player_state"] = "PLAYING"; save()
elif sub == "pause":
    if dev["player_state"] not in ("PLAYING", "BUFFERING"):
        fail("Nothing is playing.")
    dev["player_state"] = "PAUSED"; save()
elif sub == "play_toggle":
    dev["player_state"] = "PAUSED" if dev["player_state"] == "PLAYING" else "PLAYING"; save()
elif sub == "stop":
    dev.update(player_state="IDLE", current_time=0, duration=0, title="", content_id=""); save()
elif sub == "seek":
    target = int(argv[1])
    if not dev.get("duration") or target > dev["duration"]:
        fail("Cannot seek: the media is not seekable.")
    dev["current_time"] = target; save()
elif sub == "volume":
    dev["volume_level"] = int(argv[1]) / 100; save()
elif sub == "volumemute":
    dev["volume_muted"] = argv[1] == "true"; save()
elif sub == "cast":
    title = argv[argv.index("-l") + 1] if "-l" in argv else ""
    dev.update(player_state="PLAYING", current_time=0, duration=data.get("cast_duration", 600),
               title=title, content_id=argv[-1]); save()
else:
    save()
'''


class FakeCast:
    """A fake ``catt`` and its receivers; patches ``castctl.CATT`` while active."""

    def __init__(self, directory: str | Path, *, cast_duration: float = 600.0) -> None:
        if os.name != "posix":
            raise RuntimeError("FakeCast needs a POSIX shebang script")
        self.dir = Path(directory)
        self.state_path = self.dir / "fake-catt-state.json"
        self.script = self.dir / "catt"
        self._patch = None
        self._write({"devices": {}, "faults": {}, "delays": {}, "log": [],
                     "cast_duration": cast_duration})
        self.script.write_text(_FAKE_CATT.format(python=sys.executable, state=str(self.state_path)))
        self.script.chmod(self.script.stat().st_mode | stat.S_IXUSR)

    # -- lifecycle
    def __enter__(self) -> "FakeCast":
        self._patch = mock.patch.object(castctl, "CATT", str(self.script))
        self._patch.start()
        return self

    def __exit__(self, *_exc) -> None:
        if self._patch is not None:
            self._patch.stop()

    # -- state file
    def _read(self) -> dict:
        return json.loads(self.state_path.read_text())

    def _write(self, data: dict) -> None:
        self.state_path.write_text(json.dumps(data))

    def _edit(self, change) -> None:
        data = self._read()
        change(data)
        self._write(data)

    # -- scripting
    def add_device(self, name: str, **fields) -> None:
        device = {"host": "192.168.1.50", "port": 8009, "model_name": "Fake Chromecast",
                  "manufacturer": "Fake", "uuid": f"uuid-{name}", "online": True,
                  "player_state": "IDLE", "current_time": 0, "duration": 0, "title": "",
                  "content_id": "", "volume_level": 0.5, "volume_muted": False}
        device.update(fields)
        self._edit(lambda d: d["devices"].__setitem__(name, device))

    def update(self, name: str, **fields) -> None:
        self._edit(lambda d: d["devices"][name].update(fields))

    def go_offline(self, name: str) -> None:
        self.update(name, online=False)

    def fail(self, subcommand: str, message: str = "The command failed.", *,
             exit_code: int = 1, times: int = 1, device: str | None = None) -> None:
        """Make the next *times* ``catt <subcommand>`` calls exit non-zero."""
        fault = {"message": message, "exit": exit_code, "times": times, "device": device}
        self._edit(lambda d: d["faults"].setdefault(subcommand, []).append(fault))

    def delay(self, subcommand: str, seconds: float) -> None:
        self._edit(lambda d: d["delays"].__setitem__(subcommand, seconds))

    def advance(self, name: str, seconds: float) -> None:
        """Playing media progresses; reaching the end returns the receiver to IDLE."""
        def change(data):
            dev = data["devices"][name]
            if dev["player_state"] == "PLAYING":
                dev["current_time"] += seconds
                if dev["duration"] and dev["current_time"] >= dev["duration"]:
                    dev.update(player_state="IDLE", current_time=0, duration=0, title="", content_id="")
        self._edit(change)

    # -- inspection
    def device(self, name: str) -> dict:
        return self._read()["devices"][name]

    def calls(self, subcommand: str | None = None) -> list[list[str]]:
        """argv of every catt invocation (after ``-d NAME``), optionally one subcommand."""
        argvs = [entry["argv"] for entry in self._read()["log"]]
        return [a for a in argvs if subcommand is None or a[:1] == [subcommand]]


def main(argv: list[str] | None = None) -> int:
    """Run the DLNA fake on loopback for a manual protocol session."""
    parser = argparse.ArgumentParser(description="Run the loopback-only fake DLNA renderer")
    parser.add_argument("--name", default="Fake TV")
    parser.add_argument("--profile", choices=FakeDlnaRenderer.PROFILES, default="default")
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after this many seconds (default: run until interrupted)")
    args = parser.parse_args(argv)
    if args.duration is not None and args.duration < 0:
        parser.error("--duration must be non-negative")
    with FakeDlnaRenderer(name=args.name, profile=args.profile) as receiver:
        print(f"DLNA description: {receiver.location}", flush=True)
        print(f"SSDP test socket: 127.0.0.1:{receiver.ssdp_port}", flush=True)
        try:
            threading.Event().wait(args.duration)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
