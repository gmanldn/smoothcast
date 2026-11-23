"""Room screens over a private loopback listener: auth, media and playback flow."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_join
import portal_media
import portal_status

PIN = "234567"
CAPS = ["video/mp4", "audio/mpeg", "audio/mp4"]


class Rig:
    def __init__(self, tmp_path: Path, *, status_snapshot=None):
        self.tmp = tmp_path
        self.files: dict[str, Path] = {}
        self.queue: list[dict] = []
        self.calls: list[tuple] = []
        self.resolve_error: portal.PortalRequestError | None = None
        self.server = portal._PortalHTTPServer(
            ("127.0.0.1", 0), PIN, self.dispatch,
            status_snapshot=status_snapshot,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    # The fake GTK owner: status lists the queue, media_path resolves opaque IDs.
    def dispatch(self, action, payload):
        self.calls.append((action, payload))
        if action == "status":
            return {"title": "x", "state": "PLAYING", "queue": list(self.queue)}
        if action == "media_path":
            if self.resolve_error is not None:
                raise self.resolve_error
            path = self.files.get(payload["id"])
            if path is None:
                raise portal.PortalRequestError(404, "That queue item is no longer here")
            return {"path": str(path), "title": path.name, "duration": 12.0}
        return "accepted"

    def add(self, name: str, data: bytes = b"", ident: str | None = None) -> str:
        ident = ident or f"id{len(self.files):02d}"
        path = self.tmp / name
        path.write_bytes(data)
        self.files[ident] = path
        self.queue.append({"id": ident, "title": name, "duration": 12.0})
        return ident

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def request(self, method, path, body=None, *, cookie=None, csrf=None,
                headers=None, origin=True, host=None):
        hdrs = {"Host": host or self.host}
        if origin and method != "GET" and method != "HEAD":
            hdrs["Origin"] = f"http://{self.host}"
        if cookie:
            hdrs["Cookie"] = cookie
        if csrf is not None:
            hdrs["X-CSRF-Token"] = csrf
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=raw, headers=hdrs)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def login(self, name="Guest"):
        status, body, headers = self.request("POST", "/api/login",
                                             {"pin": PIN, "name": name})
        assert status == 200, body
        return headers["Set-Cookie"].split(";")[0], json.loads(body)["csrf"]

    def json(self, *args, **kwargs):
        status, body, _headers = self.request(*args, **kwargs)
        return status, json.loads(body)

    def register(self, cookie, csrf, name="Lounge TV", caps=None, claim=None):
        body = {"name": name, "capabilities": CAPS if caps is None else caps}
        if claim:
            body["claim"] = claim
        status, data = self.json("POST", "/api/screens", body, cookie=cookie, csrf=csrf)
        assert status == 200, data
        return data["screen"]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


@pytest.fixture
def rig(tmp_path):
    value = Rig(tmp_path)
    yield value
    value.close()


# -- authentication boundaries --------------------------------------------

def test_screen_page_is_public_but_everything_else_needs_a_paired_session(rig):
    status, body, headers = rig.request("GET", "/screen")
    assert status == 200 and b"SmoothCast Screen" in body
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")
    # Self-hosted: no external origins anywhere in the page.
    assert b"http://" not in body and b"https://" not in body
    media = rig.add("a.mp4", b"0123456789")
    for method, path, body in [
        ("GET", "/api/screens", None),
        ("POST", "/api/screens", {"name": "x"}),
        ("GET", "/api/screens/abcdef01/poll", None),
        ("POST", "/api/screens/abcdef01/command", {"action": "stop"}),
        ("DELETE", "/api/screens/abcdef01", None),
        ("GET", f"/api/media/{media}", None),
        ("HEAD", f"/api/media/{media}", None),
    ]:
        status, _body, _h = rig.request(method, path, body)
        assert status in {401, 403}, (method, path, status)
    assert not any(c[0] == "media_path" for c in rig.calls)


def test_state_changes_need_the_csrf_token_and_a_matching_host(rig):
    cookie, csrf = rig.login()
    status, _ = rig.json("POST", "/api/screens", {"name": "x"}, cookie=cookie)
    assert status == 403
    status, _ = rig.json("POST", "/api/screens", {"name": "x"}, cookie=cookie,
                         csrf="wrong")
    assert status == 403
    status, _ = rig.json("POST", "/api/screens", {"name": "x"}, cookie=cookie,
                         csrf=csrf, host="evil.example:80")
    assert status in {400, 403}
    media = rig.add("a.mp4", b"abc")
    status, _body, _h = rig.request("GET", f"/api/media/{media}", cookie=cookie,
                                    host="rebind.example")
    assert status == 400                       # DNS-rebinding guard applies to media


def test_revoking_a_guest_drops_their_screen_and_media_access(rig):
    cookie, csrf = rig.login("Sam")
    screen = rig.register(cookie, csrf)
    media = rig.add("a.mp4", b"abc")
    assert rig.request("GET", f"/api/media/{media}", cookie=cookie)[0] == 200
    participant = rig.server.session_participant(cookie.split("=", 1)[1])
    assert rig.server.revoke_participant(participant) == 1
    assert rig.server.screens.snapshot() == []
    assert rig.request("GET", f"/api/media/{media}", cookie=cookie)[0] == 401
    assert rig.request("GET", f"/api/screens/{screen['id']}/poll", cookie=cookie)[0] == 401


def test_ending_all_guest_access_drops_every_screen(rig):
    for name in ("A", "B"):
        cookie, csrf = rig.login(name)
        rig.register(cookie, csrf, name)
    rig.server.revoke_all()
    assert rig.server.screens.snapshot() == []


# -- registration, polling and control ------------------------------------

def test_full_remote_control_round_trip_between_two_guests(rig):
    screen_cookie, screen_csrf = rig.login("TV")
    remote_cookie, remote_csrf = rig.login("Phone")
    screen = rig.register(screen_cookie, screen_csrf)
    media = rig.add("film.mp4", b"x" * 100)

    status, data = rig.json("GET", "/api/screens", cookie=remote_cookie)
    assert [s["name"] for s in data["screens"]] == ["Lounge TV"]
    status, data = rig.json("POST", f"/api/screens/{screen['id']}/command",
                            {"action": "play", "item": media, "follow": True,
                             "command_id": "c1"},
                            cookie=remote_cookie, csrf=remote_csrf)
    assert status == 202 and data["seq"] == 1

    status, polled = rig.json("GET", f"/api/screens/{screen['id']}/poll?since=0",
                              cookie=screen_cookie)
    order = polled["orders"][0]
    assert order["kind"] == "play" and order["url"] == f"/api/media/{media}"
    assert order["route"]["mode"] == "direct" and order["follow"] is True
    # Paths never reach a client, only opaque IDs and titles.
    assert str(rig.tmp) not in json.dumps(polled)

    status, _ = rig.json("POST", f"/api/screens/{screen['id']}/report",
                         {"state": "playing", "position": 3.5, "ack": 1,
                          "play_seq": 1}, cookie=screen_cookie, csrf=screen_csrf)
    assert status == 200
    status, state = rig.json("GET", "/api/status", cookie=remote_cookie)
    row = state["state"]["screens"][0]
    assert row["state"] == "playing" and row["title"] == "film.mp4"
    assert row["position"] == 3.5 and row["ready"] is True

    status, _ = rig.json("POST", f"/api/screens/{screen['id']}/command",
                         {"action": "pause"}, cookie=remote_cookie, csrf=remote_csrf)
    assert status == 202
    status, _ = rig.json("POST", f"/api/screens/{screen['id']}/command",
                         {"action": "seek", "value": "soon"},
                         cookie=remote_cookie, csrf=remote_csrf)
    assert status == 400


def test_another_guest_cannot_poll_report_or_delete_a_screen_they_do_not_own(rig):
    owner_cookie, owner_csrf = rig.login("TV")
    other_cookie, other_csrf = rig.login("Other")
    screen = rig.register(owner_cookie, owner_csrf)
    path = f"/api/screens/{screen['id']}"
    assert rig.request("GET", path + "/poll", cookie=other_cookie)[0] == 404
    assert rig.request("POST", path + "/report", {"state": "idle"},
                       cookie=other_cookie, csrf=other_csrf)[0] == 404
    assert rig.request("DELETE", path, cookie=other_cookie, csrf=other_csrf)[0] == 404
    assert rig.request("DELETE", path, cookie=owner_cookie, csrf=owner_csrf)[0] == 200
    assert rig.server.screens.snapshot() == []


def test_unsupported_methods_and_malformed_routes_are_rejected(rig):
    cookie, csrf = rig.login()
    screen = rig.register(cookie, csrf)
    for method, path in [("PUT", f"/api/screens/{screen['id']}"),
                         ("GET", f"/api/screens/{screen['id']}"),
                         ("GET", f"/api/screens/{screen['id']}/command")]:
        assert rig.request(method, path, cookie=cookie, csrf=csrf)[0] in {404, 405, 401, 403}
    assert rig.request("GET", "/api/screens/ZZZZZZZZ/poll", cookie=cookie)[0] == 404
    assert rig.request("GET", "/api/media/../../etc/passwd", cookie=cookie)[0] == 404
    assert rig.request("HEAD", "/api/status", cookie=cookie)[0] == 405


def test_play_validates_the_queue_item_and_surfaces_host_refusals(rig):
    cookie, csrf = rig.login()
    screen = rig.register(cookie, csrf)
    url = f"/api/screens/{screen['id']}/command"
    assert rig.json("POST", url, {"action": "play", "item": "gone"},
                    cookie=cookie, csrf=csrf)[0] == 404
    assert rig.json("POST", url, {"action": "play"}, cookie=cookie, csrf=csrf)[0] == 400
    rig.add("a.mp4", b"abc", ident="have")
    rig.resolve_error = portal.PortalRequestError(403, "The host has turned off screens")
    status, data = rig.json("POST", url, {"action": "play", "item": "have"},
                            cookie=cookie, csrf=csrf)
    assert status == 403 and "turned off" in data["error"]


def test_unplayable_file_types_are_refused_before_any_bytes_move(rig):
    cookie, csrf = rig.login()
    screen = rig.register(cookie, csrf)
    junk = rig.add("notes.txt", b"secret")
    status, data = rig.json("POST", f"/api/screens/{screen['id']}/command",
                            {"action": "play", "item": junk}, cookie=cookie, csrf=csrf)
    assert status == 415
    assert rig.request("GET", f"/api/media/{junk}", cookie=cookie)[0] == 415


# -- following the queue ---------------------------------------------------

def test_a_following_screen_advances_and_skips_unplayable_entries(rig):
    cookie, csrf = rig.login("TV")
    screen = rig.register(cookie, csrf)
    first = rig.add("one.mp4", b"1")
    rig.add("readme.txt", b"no")            # skipped, not a stall
    third = rig.add("three.mp3", b"3")
    url = f"/api/screens/{screen['id']}"
    assert rig.json("POST", url + "/command", {"action": "play", "item": first,
                                                "follow": True},
                    cookie=cookie, csrf=csrf)[0] == 202
    rig.json("POST", url + "/report", {"state": "playing", "play_seq": 1},
             cookie=cookie, csrf=csrf)
    rig.json("POST", url + "/report", {"state": "ended", "play_seq": 1},
             cookie=cookie, csrf=csrf)
    orders = rig.json("GET", url + "/poll?since=1", cookie=cookie)[1]["orders"]
    assert [o["item"] for o in orders] == [third]
    assert orders[0]["follow"] is True and orders[0]["route"]["kind"] == "audio"
    # Queue exhausted: finishing the last item stops cleanly instead of looping.
    rig.json("POST", url + "/report", {"state": "ended", "play_seq": 2},
             cookie=cookie, csrf=csrf)
    assert rig.json("GET", url + "/poll?since=2", cookie=cookie)[1]["orders"] == []


# -- media delivery --------------------------------------------------------

def test_direct_media_supports_full_ranged_suffix_and_head_requests(rig):
    cookie, _csrf = rig.login()
    data = bytes(range(256)) * 8
    media = rig.add("clip.mp4", data)
    path = f"/api/media/{media}"
    status, body, headers = rig.request("GET", path, cookie=cookie)
    assert (status, body) == (200, data)
    assert headers["Content-Type"] == "video/mp4" and headers["Accept-Ranges"] == "bytes"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert str(rig.tmp) not in "".join(headers.values())

    status, body, headers = rig.request("GET", path, cookie=cookie,
                                        headers={"Range": "bytes=10-19"})
    assert (status, body) == (206, data[10:20])
    assert headers["Content-Range"] == f"bytes 10-19/{len(data)}"
    status, body, _ = rig.request("GET", path, cookie=cookie,
                                  headers={"Range": "bytes=2040-"})
    assert (status, body) == (206, data[2040:])
    status, body, _ = rig.request("GET", path, cookie=cookie,
                                  headers={"Range": "bytes=-5"})
    assert (status, body) == (206, data[-5:])
    status, body, _ = rig.request("GET", path, cookie=cookie,
                                  headers={"Range": "bytes=0-99999"})
    assert (status, len(body)) == (206, len(data))

    status, body, headers = rig.request("HEAD", path, cookie=cookie)
    assert status == 200 and body == b"" and headers["Content-Length"] == str(len(data))


@pytest.mark.parametrize("header", ["bytes=9999-", "bytes=5-2", "bytes=0-1,4-5",
                                    "items=0-1", "bytes=-", "bytes=--3", "bytes=x-y"])
def test_bad_ranges_get_416_and_never_leak_bytes(rig, header):
    cookie, _csrf = rig.login()
    media = rig.add("clip.mp4", b"0123456789")
    status, body, headers = rig.request("GET", f"/api/media/{media}", cookie=cookie,
                                        headers={"Range": header})
    assert status == 416 and body == b""
    assert headers["Content-Range"] == "bytes */10"


def test_symlinks_and_vanished_files_are_never_served(rig, tmp_path):
    cookie, _csrf = rig.login()
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"private")
    link = tmp_path / "link.mp4"
    link.symlink_to(secret)
    rig.files["lnk"] = link
    rig.files["gone"] = tmp_path / "missing.mp4"
    rig.files["dir"] = tmp_path
    for item in ("lnk", "gone", "dir"):
        assert rig.request("GET", f"/api/media/{item}", cookie=cookie)[0] in {404, 415}
    assert rig.request("GET", "/api/media/unknown", cookie=cookie)[0] == 404


def test_media_slots_are_bounded_and_always_released(rig):
    cookie, _csrf = rig.login()
    media = rig.add("clip.mp4", b"abc")
    held = []
    try:
        for _ in range(portal_media.MAX_STREAMS):
            slot = portal_media.stream_slot()
            slot.__enter__()
            held.append(slot)
        assert rig.request("GET", f"/api/media/{media}", cookie=cookie)[0] == 503
    finally:
        for slot in held:
            slot.__exit__(None, None, None)
    assert rig.request("GET", f"/api/media/{media}", cookie=cookie)[0] == 200


def test_media_path_lookup_is_cached_briefly_between_range_requests(rig):
    cookie, _csrf = rig.login()
    media = rig.add("clip.mp4", b"0123456789")
    for _ in range(5):
        assert rig.request("GET", f"/api/media/{media}", cookie=cookie,
                           headers={"Range": "bytes=0-1"})[0] == 206
    assert sum(1 for call in rig.calls if call[0] == "media_path") == 1


# -- host-side conversion --------------------------------------------------

class FakeProc:
    def __init__(self, chunks):
        self.stdout = _Pipe(chunks)
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def terminate(self):
        self.kill()

    def wait(self, timeout=None):
        return self.returncode


class _Pipe:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, _n):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


class _Handler:
    def __init__(self, fail_after=None):
        self.writes = []
        self.fail_after = fail_after
        outer = self

        class Wfile:
            def write(self, data):
                if outer.fail_after is not None and len(outer.writes) >= outer.fail_after:
                    raise BrokenPipeError
                outer.writes.append(data)
        self.wfile = Wfile()


def test_conversion_child_is_killed_when_the_client_disconnects(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_media, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    source = tmp_path / "a.mkv"
    source.write_bytes(b"x")
    procs = []

    def popen(command, **_kwargs):
        procs.append(FakeProc([b"a" * 10, b"b" * 10, b"c" * 10]))
        assert command[0] == "/usr/bin/ffmpeg" and f"file:{source}" in command
        return procs[0]

    handler = _Handler(fail_after=1)
    sent = []
    portal_media.serve_transcode(handler, source, "video", 0, "video/mp4",
                                 write_headers=lambda s, h: sent.append((s, h)),
                                 popen=popen)
    assert sent[0][0] == 200 and "Content-Length" not in sent[0][1]
    assert procs[0].killed and procs[0].stdout.closed
    # The next conversion can start: the slot was released.
    with portal_media.transcode_slot():
        pass


def test_conversion_reports_failure_instead_of_empty_200(tmp_path, monkeypatch):
    monkeypatch.setattr(portal_media, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    source = tmp_path / "a.mkv"
    source.write_bytes(b"x")
    with pytest.raises(portal_media.MediaError) as info:
        portal_media.serve_transcode(
            _Handler(), source, "video", 0, "video/mp4",
            write_headers=lambda *_a: pytest.fail("headers sent before data"),
            popen=lambda *_a, **_k: FakeProc([]))
    assert info.value.status == 502


def test_conversion_is_refused_without_ffmpeg_and_at_the_concurrency_cap(
        tmp_path, monkeypatch):
    source = tmp_path / "a.mkv"
    source.write_bytes(b"x")
    monkeypatch.setattr(portal_media, "ffmpeg_path", lambda: None)
    with pytest.raises(portal_media.MediaError) as info:
        portal_media.serve_transcode(_Handler(), source, "video", 0, "video/mp4",
                                     write_headers=lambda *_a: None)
    assert info.value.status == 503
    monkeypatch.setattr(portal_media, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    held = [portal_media.transcode_slot() for _ in range(portal_media.MAX_TRANSCODES)]
    for slot in held:
        slot.__enter__()
    try:
        with pytest.raises(portal_media.MediaError) as info:
            portal_media.serve_transcode(_Handler(), source, "video", 0, "video/mp4",
                                         write_headers=lambda *_a: None)
        assert info.value.status == 503
    finally:
        for slot in held:
            slot.__exit__(None, None, None)


def test_ffmpeg_command_is_bounded_and_streams_fragmented_mp4():
    video = portal_media.ffmpeg_command("ffmpeg", "/m/film.mkv", "video", 90.5)
    assert video[video.index("-ss") + 1] == "90.500"
    assert video.index("-ss") < video.index("-i")        # fast input seek
    assert "-sn" in video and video[-3:] == ["-f", "mp4", "pipe:1"]
    assert "frag_keyframe+empty_moov+default_base_moof" in video
    audio = portal_media.ffmpeg_command("ffmpeg", "/m/a.flac", "audio", 0)
    assert "-vn" in audio and "-ss" not in audio and "libx264" not in audio
    clamped = portal_media.ffmpeg_command("ffmpeg", "/m/a.mkv", "video", 10**9)
    assert float(clamped[clamped.index("-ss") + 1]) == portal_media.MAX_START_SECONDS


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires FFmpeg")
def test_real_conversion_streams_playable_mp4_to_a_screen(rig, tmp_path):
    source = tmp_path / "tiny.avi"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "mpeg4",
         "-c:a", "mp3", str(source)], check=True, timeout=60)
    rig.files["tiny"] = source
    rig.queue.append({"id": "tiny", "title": "tiny.avi", "duration": 1.0})
    cookie, csrf = rig.login()
    screen = rig.register(cookie, csrf)
    status, data = rig.json("POST", f"/api/screens/{screen['id']}/command",
                            {"action": "play", "item": "tiny"}, cookie=cookie, csrf=csrf)
    assert status == 202
    order = rig.json("GET", f"/api/screens/{screen['id']}/poll?since=0",
                     cookie=cookie)[1]["orders"][0]
    assert order["route"]["mode"] == "transcode" and order["route"]["reason"]
    status, body, headers = rig.request("GET", order["url"], cookie=cookie)
    assert status == 200 and headers["Content-Type"] == "video/mp4"
    assert body[4:8] == b"ftyp" and b"moof" in body and len(body) > 1000
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", "-"],
        input=body, capture_output=True, timeout=30)
    assert b"h264" in probe.stdout and b"aac" in probe.stdout


def test_screens_never_touch_the_hosts_own_playback_session(rig):
    """Only read-only status and path lookups may reach the GTK owner."""
    screen_cookie, screen_csrf = rig.login("TV")
    remote_cookie, remote_csrf = rig.login("Phone")
    screen = rig.register(screen_cookie, screen_csrf)
    media = rig.add("film.mp4", b"x" * 10)
    url = f"/api/screens/{screen['id']}/command"
    for body in ({"action": "play", "item": media, "follow": True},
                 {"action": "pause"}, {"action": "resume"},
                 {"action": "seek", "value": 3}, {"action": "volume", "value": 20},
                 {"action": "stop"}):
        assert rig.json("POST", url, body, cookie=remote_cookie,
                        csrf=remote_csrf)[0] == 202
    rig.request("GET", f"/api/media/{media}", cookie=screen_cookie)
    assert {call[0] for call in rig.calls} <= {"status", "media_path"}


def test_status_http_reads_snapshot_while_gtk_dispatcher_is_blocked(tmp_path):
    snapshot = portal_status.PublishedStatus()
    snapshot.publish({"title": "Cached", "state": "PLAYING", "queue": []})
    rig = Rig(tmp_path, status_snapshot=snapshot.read)
    entered, release = threading.Event(), threading.Event()
    blocked_at = [0.0]

    dispatch_calls = []

    def blocked_dispatch(operation, _payload):
        dispatch_calls.append(operation)
        blocked_at[0] = time.monotonic()
        entered.set()
        release.wait()
        return {"title": "Live", "state": "PLAYING", "queue": []}

    rig.server.dispatch = blocked_dispatch
    blocker = threading.Thread(target=lambda: rig.server.dispatch("status", {}), daemon=True)
    blocker.start()
    assert entered.wait(1.0)
    try:
        guests = [rig.login(f"Guest {index}")[0] for index in range(32)]

        def read_status(cookie):
            started = time.perf_counter()
            status, data = rig.json("GET", "/api/status", cookie=cookie)
            return status, data, time.perf_counter() - started

        with ThreadPoolExecutor(max_workers=32) as pool:
            replies = list(pool.map(read_status, guests))
        assert all(status == 200 for status, _data, _elapsed in replies)
        assert all(elapsed < 0.05 for _status, _data, elapsed in replies), \
            f"status latency over 50 ms: {max(elapsed for _status, _data, elapsed in replies):.3f}s"
        assert all(data["state"]["title"] == "Cached" for _status, data, _elapsed in replies)
        assert all("snapshot_age_ms" in data["state"] for _status, data, _elapsed in replies)
        assert dispatch_calls == ["status"]
        first_age = replies[0][1]["state"]["snapshot_age_ms"]
        time.sleep(0.03)
        status, later = rig.json("GET", "/api/status", cookie=guests[0])
        assert status == 200
        assert later["state"]["snapshot_age_ms"] > first_age
        assert later["state"]["snapshot_version"] == 1
        remaining = 3.0 - (time.monotonic() - blocked_at[0])
        if remaining > 0:
            time.sleep(remaining)
        assert not release.is_set()
    finally:
        release.set()
        blocker.join(3.0)
        rig.close()


def test_join_qr_is_public_png_for_bound_ip_and_never_contains_pin(rig, monkeypatch):
    """Idle screen QR is a room URL, not an authenticated/private token."""
    import struct

    actual = portal_join.qr_png
    seen = []

    def capture(url):
        seen.append(url)
        return actual(url)

    monkeypatch.setattr(portal_join, "qr_png", capture)
    status, data, headers = rig.request("GET", "/join-qr.png")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert headers["Cache-Control"] == "no-store"
    assert data[:8] == bytes.fromhex("89504e470d0a1a0a")
    width, height = struct.unpack(">II", data[16:24])
    assert width == height and width >= 100
    assert seen == [f"http://127.0.0.1:{rig.port}/"]
    assert PIN not in seen[0] and "?" not in seen[0]
    assert rig.request("GET", "/join-qr.png", host="evil.example")[0] == 400


def test_join_qr_invalid_binding_fails_closed_without_secret(rig, monkeypatch):
    def invalid(_url):
        raise ValueError("invalid internal address")

    monkeypatch.setattr(portal_join, "qr_png", invalid)
    status, data, _headers = rig.request("GET", "/join-qr.png")
    assert status == 503
    assert PIN.encode() not in data
    assert b"invalid internal address" not in data
