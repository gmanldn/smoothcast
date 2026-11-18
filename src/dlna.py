"""UPnP AV MediaRenderer control and a private, range-capable media server.

This is an independent DLNA adapter; it never sends catt/Google Cast commands
to a renderer. Supports progressive MP4 resources, preparing compatible MP4
output from other containers with FFmpeg before playback where necessary.
Only one explicit local file is served per session, under an unguessable URL.
"""
from __future__ import annotations

import atexit
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


SSDP_ADDRESS = ("239.255.255.250", 1900)
DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaRenderer:1"
SERVICE_PREFIX = "urn:schemas-upnp-org:service:"
MAX_DESCRIPTION = 512 * 1024
MAX_SOAP_RESPONSE = 128 * 1024
MAX_RENDERERS = 64
CHUNK = 128 * 1024
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)\Z")
MEDIA_TYPE = "video/mp4"

_live_encoders: set[subprocess.Popen] = set()
_encoder_lock = threading.Lock()


def _stop_encoders_on_exit() -> None:
    """Do not orphan an FFmpeg full-film conversion when the GUI exits."""
    with _encoder_lock:
        children = list(_live_encoders)
    for proc in children:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except OSError:
            pass


atexit.register(_stop_encoders_on_exit)


class DlnaError(RuntimeError):
    """A DLNA discovery, encoding, serving or renderer operation failed."""


@dataclass(frozen=True)
class Renderer:
    name: str
    host: str
    location: str
    transport_url: str
    transport_service: str
    rendering_url: str = ""
    rendering_service: str = ""
    model: str = ""

    @property
    def key(self) -> str:
        return f"DLNA · {self.name} · {self.host}"


def _private_host(host: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return False
    return ip.is_private and not (
        ip.is_loopback or ip.is_unspecified or ip.is_link_local
        or ip.is_multicast or ip.is_reserved
    )


def _url(url: str, *, expected_host: str = "") -> tuple[str, int, str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "http" or not _private_host(host)
            or (expected_host and host != expected_host)
            or parts.username is not None or parts.password is not None):
        raise DlnaError("Renderer URLs must use a private LAN HTTP IPv4 address")
    try:
        port = parts.port or 80
    except ValueError as exc:
        raise DlnaError("Invalid DLNA service port") from exc
    if not (1 <= port <= 65535):
        raise DlnaError("Invalid DLNA service port")
    target = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    return host, port, target


def _http_get(url: str, *, expected_host: str) -> bytes:
    host, port, target = _url(url, expected_host=expected_host)
    conn = HTTPConnection(host, port, timeout=4)
    try:
        conn.request("GET", target, headers={"User-Agent": "SmoothCast/UPnP", "Connection": "close"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise DlnaError(f"Renderer description returned HTTP {resp.status}")
        data = resp.read(MAX_DESCRIPTION + 1)
        if len(data) > MAX_DESCRIPTION:
            raise DlnaError("Renderer description exceeds safe size limit")
        return data
    except (OSError, HTTPException) as exc:
        raise DlnaError(f"Could not read DLNA receiver description: {exc}") from exc
    finally:
        conn.close()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element, name: str) -> str:
    return next((str(c.text or "").strip() for c in parent if _local(c.tag) == name), "")


def parse_renderer(xml: bytes, location: str, sender_host: str) -> Renderer:
    """Parse a genuine MediaRenderer's AVTransport endpoint without cross-LAN URL redirects."""
    _url(location, expected_host=sender_host)
    if len(xml) > MAX_DESCRIPTION:
        raise DlnaError("Renderer description exceeds safe size limit")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DlnaError("Invalid DLNA receiver XML") from exc
    devices = [node for node in root.iter() if _local(node.tag) == "device"]
    device = next((d for d in devices
                   if _child_text(d, "deviceType").startswith(
                       "urn:schemas-upnp-org:device:MediaRenderer:")), None)
    if device is None:
        raise DlnaError("Description is not a UPnP MediaRenderer")
    transport = None
    rendering = None
    for service in device.iter():
        if _local(service.tag) != "service":
            continue
        service_type = _child_text(service, "serviceType")
        control = _child_text(service, "controlURL")
        if not control:
            continue
        endpoint = urljoin(location, control)
        _url(endpoint, expected_host=sender_host)
        if service_type.startswith(SERVICE_PREFIX + "AVTransport:"):
            transport = (endpoint, service_type)
        elif service_type.startswith(SERVICE_PREFIX + "RenderingControl:"):
            rendering = (endpoint, service_type)
    if transport is None:
        raise DlnaError("UPnP MediaRenderer has no AVTransport service")
    name = _child_text(device, "friendlyName") or sender_host
    return Renderer(
        name=name[:120], host=sender_host, location=location,
        transport_url=transport[0], transport_service=transport[1],
        rendering_url=rendering[0] if rendering else "",
        rendering_service=rendering[1] if rendering else "",
        model=_child_text(device, "modelName")[:120],
    )


def discover(timeout: float = 4.0) -> list[Renderer]:
    """Discover MediaRenderers by SSDP; bounded by deadline and device count."""
    query = ("M-SEARCH * HTTP/1.1\r\n"
             "HOST: 239.255.255.250:1900\r\n"
             'MAN: "ssdp:discover"\r\n'
             "MX: 2\r\n"
             f"ST: {DEVICE_TYPE}\r\n\r\n").encode("ascii")
    deadline = time.monotonic() + max(0.2, min(12.0, timeout))
    locations: dict[str, str] = {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.bind(("0.0.0.0", 0))
            sock.sendto(query, SSDP_ADDRESS)
            while len(locations) < MAX_RENDERERS:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(min(0.5, remaining))
                try:
                    payload, addr = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                sender = addr[0]
                if not _private_host(sender):
                    continue
                header = {}
                for line in payload.decode("iso-8859-1", "replace").splitlines():
                    name, sep, value = line.partition(":")
                    if sep:
                        header[name.strip().lower()] = value.strip()
                location = header.get("location", "")
                try:
                    _url(location, expected_host=sender)
                except DlnaError:
                    continue
                locations.setdefault(location, sender)
    except OSError as exc:
        raise DlnaError(f"SSDP multicast discovery failed: {exc}") from exc
    devices: list[Renderer] = []
    seen = set()
    for location, sender in locations.items():
        try:
            item = parse_renderer(_http_get(location, expected_host=sender),
                                  location, sender)
        except DlnaError:
            continue
        if (item.host, item.transport_url) not in seen:
            devices.append(item)
            seen.add((item.host, item.transport_url))
    return sorted(devices, key=lambda x: (x.name.casefold(), x.host))


def _soap(renderer: Renderer, action: str, params: dict[str, str],
          *, rendering: bool = False) -> ET.Element:
    if rendering:
        if not renderer.rendering_url:
            raise DlnaError("This renderer does not expose RenderingControl")
        url, service = renderer.rendering_url, renderer.rendering_service
    else:
        url, service = renderer.transport_url, renderer.transport_service
    host, port, target = _url(url, expected_host=renderer.host)
    params_xml = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in params.items())
    request_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service}">{params_xml}'
        f'</u:{action}></s:Body></s:Envelope>'
    ).encode("utf-8")
    conn = HTTPConnection(host, port, timeout=5)
    try:
        conn.request("POST", target, body=request_xml, headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{service}#{action}"',
            "Connection": "close",
        })
        response = conn.getresponse()
        data = response.read(MAX_SOAP_RESPONSE + 1)
        if len(data) > MAX_SOAP_RESPONSE:
            raise DlnaError("DLNA response exceeds safe size limit")
        if response.status != 200:
            raise DlnaError(f"DLNA {action} failed (HTTP {response.status})")
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DlnaError(f"DLNA {action} returned invalid XML") from exc
    except (OSError, HTTPException) as exc:
        raise DlnaError(f"DLNA {action} failed: {exc}") from exc
    finally:
        conn.close()


def _value(root: ET.Element, key: str) -> str:
    return next((str(node.text or "").strip() for node in root.iter()
                 if _local(node.tag) == key), "")


def _seconds(clock: str) -> float:
    try:
        hours, minutes, seconds = clock.split(":")
        return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except (ValueError, TypeError):
        return 0.0


def _clock(position: float) -> str:
    amount = max(0, int(position))
    hours, rem = divmod(amount, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def info(renderer: Renderer) -> dict | None:
    try:
        state = _soap(renderer, "GetTransportInfo", {"InstanceID": "0"})
    except DlnaError:
        return None
    raw = _value(state, "CurrentTransportState").upper()
    mapped = {
        "PLAYING": "PLAYING", "PAUSED_PLAYBACK": "PAUSED",
        "TRANSITIONING": "BUFFERING", "STOPPED": "IDLE",
        "NO_MEDIA_PRESENT": "IDLE",
    }
    result: dict = {"player_state": mapped.get(raw, "IDLE"),
                    "title": renderer.name}
    try:
        pos = _soap(renderer, "GetPositionInfo", {"InstanceID": "0"})
        result["current_time"] = _seconds(_value(pos, "RelTime"))
        result["duration"] = _seconds(_value(pos, "TrackDuration"))
    except DlnaError:
        pass
    if renderer.rendering_url:
        try:
            volume = _soap(renderer, "GetVolume", {
                "InstanceID": "0", "Channel": "Master",
            }, rendering=True)
            result["volume_level"] = max(0.0, min(1.0, int(_value(volume, "CurrentVolume")) / 100))
        except (DlnaError, ValueError):
            pass
    return result


def set_uri(renderer: Renderer, url: str, title: str) -> None:
    # DIDL-Lite metadata is XML-escaped again by the SOAP envelope builder.
    metadata = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="0" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.item.videoItem</upnp:class>"
        f'<res protocolInfo="http-get:*:{MEDIA_TYPE}:*">{escape(url)}</res>'
        "</item></DIDL-Lite>"
    )
    _soap(renderer, "SetAVTransportURI", {
        "InstanceID": "0", "CurrentURI": url, "CurrentURIMetaData": metadata,
    })


def play(renderer: Renderer) -> None:
    _soap(renderer, "Play", {"InstanceID": "0", "Speed": "1"})


def pause(renderer: Renderer) -> None:
    _soap(renderer, "Pause", {"InstanceID": "0"})


def stop(renderer: Renderer) -> None:
    _soap(renderer, "Stop", {"InstanceID": "0"})


def seek(renderer: Renderer, position: float) -> None:
    _soap(renderer, "Seek", {"InstanceID": "0", "Unit": "REL_TIME",
                              "Target": _clock(position)})


def volume(renderer: Renderer, percent: float) -> None:
    level = max(0, min(100, int(round(percent))))
    _soap(renderer, "SetVolume", {"InstanceID": "0", "Channel": "Master",
                                  "DesiredVolume": str(level)}, rendering=True)


def set_muted(renderer: Renderer, muted: bool) -> None:
    _soap(renderer, "SetMute", {"InstanceID": "0", "Channel": "Master",
                                "DesiredMute": "1" if muted else "0"}, rendering=True)


class ProgressiveFileServer:
    """Serve one chosen local MP4 with HTTP byte ranges and an ephemeral URL."""

    def __init__(self, path: Path, *, receiver_ip: str):
        self.path = Path(path)
        if not self.path.is_file() or self.path.stat().st_size < 1:
            raise DlnaError("DLNA file is missing or empty")
        self.receiver_ip = receiver_ip
        self.token = secrets.token_urlsafe(24)
        source = self.path
        allowed = {receiver_ip, "127.0.0.1"}
        resource = "/media/" + self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args) -> None:
                pass

            def do_HEAD(self) -> None:
                self._serve(False)

            def do_GET(self) -> None:
                self._serve(True)

            def _serve(self, body: bool) -> None:
                if self.client_address[0] not in allowed or self.path != resource:
                    self.send_error(404)
                    return
                try:
                    size = source.stat().st_size
                    raw = self.headers.get("Range")
                    start, end = 0, size - 1
                    partial = False
                    if raw is not None:
                        match = RANGE_RE.fullmatch(raw.strip())
                        if match is None or not (match.group(1) or match.group(2)):
                            self._range_error(size)
                            return
                        if match.group(1):
                            start = int(match.group(1))
                            if match.group(2):
                                end = min(end, int(match.group(2)))
                        else:
                            start = max(0, size - int(match.group(2)))
                        if start > end or start >= size:
                            self._range_error(size)
                            return
                        partial = True
                    self.send_response(206 if partial else 200)
                    self.send_header("Content-Type", MEDIA_TYPE)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(end - start + 1))
                    if partial:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("transferMode.dlna.org", "Streaming")
                    self.send_header("contentFeatures.dlna.org",
                                     "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000")
                    self.end_headers()
                    if body:
                        with source.open("rb") as media:
                            media.seek(start)
                            remaining = end - start + 1
                            while remaining:
                                data = media.read(min(CHUNK, remaining))
                                if not data:
                                    break
                                self.wfile.write(data)
                                remaining -= len(data)
                except (OSError, BrokenPipeError, ConnectionResetError):
                    return

            def _range_error(self, size: int) -> None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="smoothcast-dlna-http", daemon=True)
        self.thread.start()

    def url(self, local_ip: str) -> str:
        if not _private_host(local_ip):
            raise DlnaError("No routable private LAN address available to serve DLNA video")
        return f"http://{local_ip}:{self.port}/media/{self.token}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def prepare_mp4(media, output: Path, *, subtitle_file: Path | None = None,
                embedded_subtitle_index: int | None = None,
                audio_track: int = 0,
                cancel: threading.Event | None = None) -> Path:
    """Prepare a complete progressive MP4; never expose a partially written file.

    Compatible MKVs are remuxed without video loss. Other codecs, subtitle
    overlays or >1080p/30 sources need an offline encode, which can be slow.
    """
    from streamer import Session
    if cancel is not None and cancel.is_set():
        raise DlnaError("DLNA preparation cancelled")
    source = Path(media.path)
    if not source.is_file():
        raise DlnaError("Local film no longer exists")
    if subtitle_file is not None and not subtitle_file.is_file():
        raise DlnaError("Selected subtitle file is missing")
    if embedded_subtitle_index is not None:
        track = next((t for t in media.subtitle_tracks if t.index == embedded_subtitle_index), None)
        if track is None or not track.is_text:
            raise DlnaError("DLNA subtitles: selected embedded track cannot be burned")
    output.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(output.parent).free
    if free < max(512 * 1024 * 1024, source.stat().st_size * 2):
        raise DlnaError("Not enough free space to prepare a DLNA-compatible MP4")

    compatible = (
        media.vcodec == "h264"
        and (media.acodec in {"aac", "mp3", ""})
        and media.pix_fmt in {"", "yuv420p", "yuvj420p"}
        and media.width <= 1920 and media.height <= 1080
        and media.fps <= 30.01
        and subtitle_file is None and embedded_subtitle_index is None
    )
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-y", "-i", str(source),
            "-map", "0:v:0", "-map", f"0:a:{max(0, int(audio_track))}?"]
    if compatible:
        args += ["-c:v", "copy", "-c:a", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                 "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1",
                 "-c:a", "aac", "-b:a", "192k", "-ac", "2"]
        vf = Session()._filter_args(
            subtitle_file is not None, subtitle_file, True, 1.0,
            embedded_subtitle_index=embedded_subtitle_index,
            embedded_source=source if embedded_subtitle_index is not None else None,
            video_size=(media.width, media.height),
        )
        args += vf
        if media.fps > 30.01:
            args += ["-r", "30"]
    args += ["-movflags", "+faststart", "-f", "mp4", str(output)]
    # A full-film conversion is slow. Poll the child process so the UI's
    # Cancel/Stop button can abort immediately and no orphan FFmpeg remains.
    with tempfile.TemporaryFile() as error_log:
        try:
            proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=error_log, start_new_session=True,
            )
        except OSError as exc:
            output.unlink(missing_ok=True)
            raise DlnaError(f"Cannot start FFmpeg: {exc}") from exc
        with _encoder_lock:
            _live_encoders.add(proc)
        deadline = time.monotonic() + min(7200, max(180, media.duration * 3 + 120))
        try:
            try:
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise DlnaError("DLNA preparation cancelled")
                    if time.monotonic() > deadline:
                        raise DlnaError("FFmpeg exceeded the DLNA preparation time limit")
                    time.sleep(0.2)
            except BaseException:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait(timeout=3)
                output.unlink(missing_ok=True)
                raise
        finally:
            with _encoder_lock:
                _live_encoders.discard(proc)
        if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            error_log.seek(0, 2)
            size = error_log.tell()
            error_log.seek(max(0, size - 2048))
            message = error_log.read().decode("utf-8", "replace").strip().splitlines()
            raise DlnaError((message[-1] if message else "DLNA MP4 preparation failed")[-300:])
    return output


class Session:
    """An in-process DLNA playback session, compatible with the GUI lifecycle."""

    def __init__(self):
        self.state = None
        self.renderer: Renderer | None = None
        self._owns_renderer = False
        self.http: ProgressiveFileServer | None = None
        self.tmp: tempfile.TemporaryDirectory | None = None
        self.used_software_fallback = True
        self.audio_chain: list = []

    @property
    def mode(self) -> str:
        return "dlna"

    def active(self) -> bool:
        return self.state is not None

    def encoder_finished(self) -> bool:
        return False

    def progress(self) -> dict:
        return {}

    def start(self, media, *, renderer: Renderer, local_ip: str, offset: float,
              title: str, subtitle_file: Path | None = None,
              embedded_subtitle_index: int | None = None, audio_track: int = 0,
              cancel: threading.Event | None = None) -> None:
        from streamer import SessionState
        self.tmp = tempfile.TemporaryDirectory(prefix="smoothcast-dlna-")
        self.renderer = renderer
        try:
            path = Path(media.path)
            direct = (
                path.suffix.lower() in {".mp4", ".m4v"}
                and media.vcodec == "h264"
                and media.acodec in {"", "aac", "mp3"}
                and media.pix_fmt in {"", "yuv420p", "yuvj420p"}
                and media.width <= 1920 and media.height <= 1080 and media.fps <= 30.01
                and subtitle_file is None and embedded_subtitle_index is None
                and audio_track == 0
            )
            if not direct:
                path = prepare_mp4(
                    media, Path(self.tmp.name) / "movie.mp4",
                    subtitle_file=subtitle_file,
                    embedded_subtitle_index=embedded_subtitle_index,
                    audio_track=audio_track, cancel=cancel,
                )
            if cancel is not None and cancel.is_set():
                raise DlnaError("DLNA preparation cancelled")
            self.http = ProgressiveFileServer(path, receiver_ip=renderer.host)
            set_uri(renderer, self.http.url(local_ip), title)
            self._owns_renderer = True
            play(renderer)
            if offset > 0:
                seek(renderer, offset)
            self.state = SessionState(
                file=str(media.path), mode="dlna", offset=max(0.0, offset),
                duration=media.duration, device=renderer.key, title=title,
                audio="original", audio_track_index=audio_track,
                subs=str(subtitle_file or ""),
                burn_subs=subtitle_file is not None or embedded_subtitle_index is not None,
                embedded_subtitle_index=(
                    embedded_subtitle_index if embedded_subtitle_index is not None else -1),
                started_at=time.time(),
            )
        except Exception:
            self.stop(renderer.key, send_stop=self._owns_renderer)
            raise

    def stop(self, _device: str, *, send_stop: bool = True) -> None:
        if send_stop and self._owns_renderer and self.renderer is not None:
            try:
                stop(self.renderer)
            except DlnaError:
                pass
        if self.http is not None:
            self.http.close()
            self.http = None
        if self.tmp is not None:
            self.tmp.cleanup()
            self.tmp = None
        self.state = None
        self._owns_renderer = False
        self.renderer = None
