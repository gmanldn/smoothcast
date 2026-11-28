"""Guest upload smoke: real HTTP, real staged bytes, no live desktop/receiver.

Run the HTTP smoke in the normal test lane. Opt into a real headless Chromium
journey with SMOOTHCAST_BROWSER_SMOKE=1 (Playwright + Chromium + FFmpeg).
"""
from __future__ import annotations

import errno
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import wave

import pytest

import portal
import portal_uploads
from test_portal import PortalRig, decode


def _audio_bytes() -> bytes:
    """Deterministic, valid PCM WAV, large enough for multiple small chunks."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x01\x00" * 8000)
    return buffer.getvalue()


@pytest.fixture
def guest_room(tmp_path, monkeypatch):
    # Exercise the production chunk loop without transferring a large film.
    monkeypatch.setattr(portal_uploads, "CHUNK_SIZE", 4096)
    uploads = portal_uploads.UploadManager(
        tmp_path / "uploads",
        disk_usage=lambda _: SimpleNamespace(free=10 * 1024**3),
    )
    rig = PortalRig(uploads)
    rig.server.pin_required = False
    deliveries = []
    original_dispatch = rig.server.dispatch

    def dispatch(action, payload):
        if action == "upload_target":
            return {"receiver": "Test TV", "target_id": "a" * 64, "active": False}
        if action in {"queue_add", "cast_upload"}:
            data = Path(payload["path"]).read_bytes()
            deliveries.append((action, payload["name"], hashlib.sha256(data).hexdigest()))
        return original_dispatch(action, payload)

    rig.server.dispatch = dispatch
    try:
        yield rig, uploads, deliveries
    finally:
        rig.close()
        uploads.close()


def test_guest_cast_target_preflight_and_upload_fence(guest_room):
    rig, uploads, _deliveries = guest_room
    origin = f"http://{rig.host}"
    status, raw, response = rig.request("POST", "/api/login", {"name": "Cast guest", "pin": ""}, origin=origin)
    assert status == 200
    cookie = response["Set-Cookie"].split(";", 1)[0]
    auth = {"cookie": cookie, "csrf": decode(raw)["csrf"], "origin": origin}
    status, raw, _ = rig.request("POST", "/api/uploads/target", {}, **auth)
    assert status == 200 and decode(raw)["receiver"] == "Test TV"
    target = decode(raw)["target_id"]
    status, _, _ = rig.request("POST", "/api/uploads",
                              {"name": "movie.mp4", "size": 32, "queue": False,
                               "cast_target": "b" * 64}, **auth)
    assert status == 409
    status, raw, _ = rig.request("POST", "/api/uploads",
                                {"name": "movie.mp4", "size": 32, "queue": False,
                                 "cast_target": target}, **auth)
    assert status == 201
    assert uploads.cast_target(cookie.split("=", 1)[1], decode(raw)["id"]) == target


def test_guest_upload_http_smoke(guest_room, monkeypatch):
    """Join, authenticate, upload, retry and finalise through the real HTTP API."""
    import streamer

    rig, uploads, deliveries = guest_room
    # Isolate the transport smoke from system codec installation. The opt-in
    # browser smoke below uses the actual FFprobe and generated media.
    monkeypatch.setattr(streamer, "ffprobe", lambda _: SimpleNamespace(
        duration=1.0, audio_streams=[object()], has_video=False, is_audio_only=True))
    data = _audio_bytes()
    status, html, _ = rig.request("GET", "/")
    assert status == 200 and b"Live transfer monitor" in html
    origin = f"http://{rig.host}"
    headers = {"X-SmoothCast-Client-Schema": str(portal.CLIENT_SCHEMA),
               "X-SmoothCast-Client-Build": portal.page_build(),
               "Sec-Fetch-Mode": "cors"}
    status, raw, response = rig.request(
        "POST", "/api/login", {"name": "Smoke guest", "pin": ""},
        origin=origin, extra_headers=headers)
    assert status == 200
    cookie = response["Set-Cookie"].split(";", 1)[0]
    auth = {"cookie": cookie, "csrf": decode(raw)["csrf"], "origin": origin}
    status, raw, _ = rig.request(
        "POST", "/api/uploads", {"name": "smoke.wav", "size": len(data), "queue": False},
        **auth, extra_headers=headers)
    assert status == 201
    created = decode(raw)
    path = "/api/uploads/" + created["id"]
    chunk_size = created["chunk_size"]
    assert chunk_size == 4096 and len(data) > 3 * chunk_size
    for start in range(0, len(data), chunk_size):
        end = min(start + chunk_size, len(data))
        chunk_headers = {**headers, "Content-Range": f"bytes {start}-{end-1}/{len(data)}"}
        if start == chunk_size:
            # Reject a chunk before storage, then consult the authoritative
            # offset exactly as the browser does after an interrupted request.
            def reject_chunk(*_args):
                raise OSError(errno.EIO, "injected smoke fault")

            with monkeypatch.context() as fault:
                fault.setattr(uploads, "append", reject_chunk)
                status, raw, _ = rig.request("PUT", path, data[start:end],
                                             **auth, extra_headers=chunk_headers)
                assert status == 503
                assert "Host could not store" in decode(raw)["error"]
            status, raw, _ = rig.request("GET", path, cookie=cookie, extra_headers=headers)
            assert status == 200 and decode(raw)["received"] == start
        status, raw, _ = rig.request(
            "PUT", path, data[start:end], **auth, extra_headers=chunk_headers,
            content_type="application/octet-stream")
        receipt = decode(raw)
        assert status == 200 and receipt["received"] == end
        assert receipt["size"] == len(data)
        assert "cast_path" not in receipt
        assert receipt["ready_to_cast"] is False
    for _ in range(2):
        status, raw, _ = rig.request("POST", path + "/complete", {"queue": False},
                                     **auth, extra_headers=headers)
        assert status == 202 and decode(raw)["ok"]
    assert deliveries == [("queue_add", "smoke.wav", hashlib.sha256(data).hexdigest())]


@pytest.mark.skipif(os.environ.get("SMOOTHCAST_BROWSER_SMOKE") != "1",
                    reason="explicit opt-in: installed Playwright Chromium and FFmpeg")
def test_guest_upload_real_browser_smoke(guest_room, monkeypatch, tmp_path):
    """Actual served HTML, browser file picker, XHR, cookies, UI and real probe."""
    from playwright.sync_api import expect, sync_playwright

    rig, uploads, deliveries = guest_room
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "Install FFmpeg first"
    audio = tmp_path / "smoke.wav"
    audio.write_bytes(_audio_bytes())
    video = tmp_path / "smoke.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=128x96:rate=12",
        "-t", "2", "-c:v", "mpeg4", "-q:v", "2", str(video),
    ], check=True, timeout=20)
    assert video.stat().st_size > 4096
    original_append = uploads.append
    failed_once = False

    def flaky_append(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise OSError(errno.EIO, "injected first-chunk failure")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(uploads, "append", flaky_append)
    origin = f"http://{rig.host}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--disable-background-networking", "--disable-sync"])
        context = browser.new_context(viewport={"width": 390, "height": 844},
                                      service_workers="block")
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(origin + "/") else route.abort())
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            expect(page.locator("#pinRow")).to_be_hidden()
            page.locator("#name").fill("Smoke guest")
            page.locator("#loginForm button").click()
            expect(page.locator("#uploadCard")).to_be_visible()
            page.locator("#videoFile").set_input_files(str(audio))
            expect(page.locator("#uploadButton")).to_be_enabled()
            page.locator("#uploadButton").click()
            expect(page.locator("#transferDelivery")).to_have_text("Added to Up Next")
            expect(page.locator("#transferPercent")).to_have_text("100%")
            expect(page.locator("#transferEvents")).to_contain_text("Retry 1 of 4")
            expect(page.locator("#videoFile")).to_have_value("")
            expect(page.locator("#videoFile")).to_be_enabled()
            expect(page.locator("#uploadButton")).to_be_disabled()
            assert failed_once
            assert deliveries == [("queue_add", audio.name,
                                   hashlib.sha256(audio.read_bytes()).hexdigest())]

            expect(page.locator("#uploadCastNow")).to_be_visible()
            page.on("dialog", lambda dialog: dialog.accept())
            with page.expect_file_chooser() as chooser:
                page.locator("#uploadCastNow").click()
            chooser.value.set_files(str(video))
            expect(page.locator("#transferDelivery")).to_have_text(
                "Play requested — waiting for the TV or speaker")
            expect(page.locator("#videoFile")).to_have_value("")
            expect(page.locator("#videoFile")).to_be_enabled()
            expect(page.locator("#uploadButton")).to_be_disabled()
            assert deliveries[-1] == ("cast_upload", video.name,
                                      hashlib.sha256(video.read_bytes()).hexdigest())
            assert len(deliveries) == 2
            assert not errors, errors
        finally:
            context.close()
            browser.close()


@pytest.mark.skipif(os.environ.get("SMOOTHCAST_BROWSER_SMOKE") != "1",
                    reason="explicit opt-in: installed Playwright Chromium")
@pytest.mark.parametrize("width", [320, 768, 1440])
def test_guest_upload_card_never_overflows_viewport(guest_room, width):
    """#570: Add panel and its actions stay inside 320 px to desktop widths."""
    from playwright.sync_api import expect, sync_playwright

    rig = guest_room[0]
    origin = f"http://{rig.host}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": 800},
                                      service_workers="block")
        page = context.new_page()
        page.set_default_timeout(15000)
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(origin + "/") else route.abort())
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill("Layout guest")
            page.locator("#loginForm button").click()
            expect(page.locator("#uploadCard")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            for sel in ("#uploadCard", "#uploadButton", "#uploadCastNow"):
                box = page.locator(sel).bounding_box()
                assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width + 0.5, sel
        finally:
            context.close()
            browser.close()


@pytest.mark.skipif(os.environ.get("SMOOTHCAST_BROWSER_SMOKE") != "1",
                    reason="explicit opt-in: installed Playwright Chromium")
def test_guest_upload_cancel_mid_transfer_delivers_nothing(guest_room, monkeypatch, tmp_path):
    """#570: Cancel during a slow transfer stops it and nothing reaches the room."""
    import threading
    import time
    from playwright.sync_api import expect, sync_playwright

    rig, uploads, deliveries = guest_room
    audio = tmp_path / "slow.wav"
    audio.write_bytes(_audio_bytes())
    original_append = uploads.append
    entered = threading.Event()

    def slow_append(*args, **kwargs):
        entered.set()
        time.sleep(4)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(uploads, "append", slow_append)
    origin = f"http://{rig.host}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844},
                                      service_workers="block")
        page = context.new_page()
        page.set_default_timeout(15000)
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(origin + "/") else route.abort())
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill("Cancel guest")
            page.locator("#loginForm button").click()
            expect(page.locator("#uploadCard")).to_be_visible()
            page.locator("#videoFile").set_input_files(str(audio))
            page.locator("#uploadButton").click()
            for _ in range(100):  # never block Playwright's loop with a threading wait
                if entered.is_set():
                    break
                page.wait_for_timeout(100)
            assert entered.is_set()
            expect(page.locator("#cancelUpload")).to_be_visible()
            page.locator("#cancelUpload").click()
            expect(page.locator("#cancelUpload")).to_be_hidden(timeout=15000)
            expect(page.locator("#uploadStatus")).to_have_text("Upload cancelled")
            expect(page.locator("#uploadButton")).to_have_text("Upload and add")
            expect(page.locator("#videoFile")).to_have_value("")
            assert deliveries == []
        finally:
            context.close()
            browser.close()


@pytest.mark.skipif(os.environ.get("SMOOTHCAST_BROWSER_SMOKE") != "1",
                    reason="explicit opt-in: installed Playwright Chromium")
def test_guest_upload_pause_then_resume_delivers_once(guest_room, monkeypatch, tmp_path):
    """#570: Pause keeps the saved offset, Resume finishes, one delivery, matching bytes."""
    import threading
    import time
    from playwright.sync_api import expect, sync_playwright

    rig, uploads, deliveries = guest_room
    audio = tmp_path / "pause.wav"
    audio.write_bytes(_audio_bytes())
    original_append = uploads.append
    entered = threading.Event()
    calls = []

    def slow_first_append(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            time.sleep(3)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(uploads, "append", slow_first_append)
    origin = f"http://{rig.host}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844},
                                      service_workers="block")
        page = context.new_page()
        page.set_default_timeout(15000)
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(origin + "/") else route.abort())
        try:
            page.goto(origin + "/", wait_until="domcontentloaded")
            page.locator("#name").fill("Pause guest")
            page.locator("#loginForm button").click()
            expect(page.locator("#uploadCard")).to_be_visible()
            page.locator("#videoFile").set_input_files(str(audio))
            page.locator("#uploadButton").click()
            for _ in range(100):  # never block Playwright's loop with a threading wait
                if entered.is_set():
                    break
                page.wait_for_timeout(100)
            assert entered.is_set()
            expect(page.locator("#pauseUpload")).to_be_visible()
            page.locator("#pauseUpload").click()
            expect(page.locator("#uploadStatus")).to_contain_text("Paused", timeout=15000)
            expect(page.locator("#uploadButton")).to_contain_text("Resume", timeout=15000)
            expect(page.locator("#uploadButton")).to_be_enabled()
            page.locator("#uploadButton").click()
            expect(page.locator("#transferDelivery")).to_have_text("Added to Up Next", timeout=20000)
            expect(page.locator("#transferPercent")).to_have_text("100%")
            assert deliveries == [("queue_add", audio.name,
                                   hashlib.sha256(audio.read_bytes()).hexdigest())]
        finally:
            context.close()
            browser.close()
