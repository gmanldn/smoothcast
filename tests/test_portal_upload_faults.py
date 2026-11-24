"""#585: injected storage/dispatch faults at the real os layer stay recoverable.

Headless loopback HTTP only: no GTK, no receiver. Every case asserts a JSON
error (never a dropped connection or traceback text), that bytes already
received survive, and that retrying never duplicates a playback dispatch.
"""
from __future__ import annotations

import errno
import json
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portal
import portal_uploads
from test_portal import PortalRig, decode, login

DATA = b"0123456789abcdef"
RANGE = {"Content-Range": f"bytes 0-{len(DATA) - 1}/{len(DATA)}"}


@pytest.fixture
def rig(tmp_path):
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    harness = PortalRig(uploads)
    _, result, cookie = login(harness)
    harness.auth = {"cookie": cookie, "csrf": result["csrf"], "origin": f"http://{harness.host}"}
    harness.uploads = uploads
    yield harness
    harness.close()
    uploads.close()


def create(rig, queue=False):
    status, raw, _ = rig.request("POST", "/api/uploads",
                                 {"name": "clip.mp4", "size": len(DATA), "queue": queue}, **rig.auth)
    return status, decode(raw)


def put(rig, upload_id, data=DATA, start=0):
    headers = {"Content-Range": f"bytes {start}-{start + len(data) - 1}/{len(DATA)}"}
    return rig.request("PUT", f"/api/uploads/{upload_id}", data, **rig.auth,
                       extra_headers=headers, content_type="application/octet-stream")


def complete(rig, upload_id):
    return rig.request("POST", f"/api/uploads/{upload_id}/complete", {}, **rig.auth)


def received(rig, upload_id):
    return decode(rig.request("GET", f"/api/uploads/{upload_id}", cookie=rig.auth["cookie"])[1])["received"]


def casts(rig):
    return [a for a, _p in rig.calls if a in ("cast_upload", "queue_add")]


def assert_clean_json(raw, *private):
    body = decode(raw)  # raises if the host answered with HTML/plain traceback
    text = json.dumps(body)
    assert body.get("ok") is False and body.get("error")
    assert "Traceback" not in text and "File \"" not in text
    for secret in private:
        assert secret not in text
    return body


@pytest.mark.parametrize("exc,status", [
    (PermissionError(errno.EACCES, "denied /private/dir"), 503),
    (OSError(errno.ENOSPC, "full /private/dir"), 507),
    (OSError(errno.EROFS, "read-only /private/dir"), 503),
])
def test_creation_storage_failure_is_json_and_leaves_no_slot_used(rig, exc, status):
    with mock.patch.object(portal_uploads.os, "open", side_effect=exc):
        got, raw, _ = rig.request("POST", "/api/uploads", {"name": "clip.mp4", "size": 16}, **rig.auth)
    assert got == status
    assert_clean_json(raw, "/private/dir")
    assert create(rig)[0] == 201  # nothing was reserved by the failed attempt


def test_chunk_disk_full_reports_507_keeps_resume_point_and_retry_is_exact(rig):
    _, created = create(rig)
    uid = created["id"]
    assert put(rig, uid, DATA[:6])[0] == 200
    real = portal_uploads.os.write
    calls = {"n": 0}

    def flaky(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            real(fd, bytes(data[:2]))  # a partial write lands before the disk fills
            raise OSError(errno.ENOSPC, "No space left on /private/dir")
        return real(fd, data)

    with mock.patch.object(portal_uploads.os, "write", side_effect=flaky):
        status, raw, _ = put(rig, uid, DATA[6:], start=6)
    assert status == 507
    assert assert_clean_json(raw, "/private/dir")["code"] == "upload.disk_full"
    assert received(rig, uid) == 6  # durable offset unchanged, partial bytes rolled back
    assert put(rig, uid, DATA[6:], start=6)[0] == 200
    assert received(rig, uid) == len(DATA)
    assert complete(rig, uid)[0] == 202
    path = Path(rig.calls[-1][1]["path"])
    assert path.read_bytes() == DATA and len(casts(rig)) == 1


def test_finalise_rename_failure_is_retryable_without_losing_bytes_or_duplicating(rig):
    _, created = create(rig)
    uid = created["id"]
    assert put(rig, uid)[0] == 200
    with mock.patch.object(portal_uploads.os, "replace", side_effect=PermissionError(errno.EACCES, "/private/x")):
        status, raw, _ = complete(rig, uid)
    assert status == 503
    assert_clean_json(raw, "/private/x")
    assert casts(rig) == [] and received(rig, uid) == len(DATA)
    assert complete(rig, uid)[0] == 202
    assert complete(rig, uid)[0] == 202  # an impatient second click is an idempotent replay
    assert len(casts(rig)) == 1
    assert Path(rig.calls[-1][1]["path"]).read_bytes() == DATA


def test_finalise_fsync_failure_is_retryable(rig):
    _, created = create(rig)
    uid = created["id"]
    assert put(rig, uid)[0] == 200
    with mock.patch.object(portal_uploads.os, "fsync", side_effect=OSError(errno.EIO, "/private/io")):
        status, raw, _ = complete(rig, uid)
    assert status == 503
    assert_clean_json(raw, "/private/io")
    assert complete(rig, uid)[0] == 202 and len(casts(rig)) == 1


@pytest.mark.parametrize("fail", [
    lambda: portal.PortalRequestError(503, "The room is busy"),
    lambda: RuntimeError("host dispatch exploded /private/dispatch"),
])
def test_dispatch_failure_is_503_json_then_retry_dispatches_exactly_once(rig, fail):
    _, created = create(rig)
    uid = created["id"]
    assert put(rig, uid)[0] == 200
    real = rig.server.dispatch
    state = {"fail": True}

    def dispatch(action, payload):
        if action in ("cast_upload", "queue_add") and state["fail"]:
            raise fail()
        return real(action, payload)

    rig.server.dispatch = dispatch
    status, raw, _ = complete(rig, uid)
    assert status >= 500
    assert_clean_json(raw, "/private/dispatch")
    assert received(rig, uid) == len(DATA) and casts(rig) == []
    state["fail"] = False
    assert complete(rig, uid)[0] == 202
    assert len(casts(rig)) == 1


@pytest.mark.parametrize("stage", ["create", "chunk", "complete"])
def test_unexpected_exception_never_drops_the_connection(rig, stage):
    """A bug (not an OSError) inside the manager must still answer in JSON."""
    boom = RuntimeError("internal bug in /private/module")
    if stage == "create":
        with mock.patch.object(rig.uploads, "create", side_effect=boom):
            status, raw, _ = rig.request("POST", "/api/uploads", {"name": "c.mp4", "size": 16}, **rig.auth)
    else:
        _, created = create(rig)
        uid = created["id"]
        if stage == "chunk":
            with mock.patch.object(rig.uploads, "append", side_effect=boom):
                status, raw, _ = put(rig, uid)
        else:
            assert put(rig, uid)[0] == 200
            with mock.patch.object(rig.uploads, "finalize", side_effect=boom):
                status, raw, _ = complete(rig, uid)
    assert 500 <= status < 600
    assert_clean_json(raw, "/private/module")


def test_slow_client_timeout_is_408_and_resumable(rig):
    _, created = create(rig)
    uid = created["id"]
    with mock.patch.object(rig.uploads, "append", side_effect=TimeoutError("slow")):
        status, raw, _ = put(rig, uid)
    assert status == 408 and "Resume" in assert_clean_json(raw)["error"]
    assert put(rig, uid)[0] == 200 and received(rig, uid) == len(DATA)


def test_stale_session_and_unknown_upload_are_distinct_actionable_errors(rig):
    status, raw, _ = put(rig, "does-not-exist-0123456789abcdef")
    assert status == 404 and "Choose the file again" in assert_clean_json(raw)["error"]
    status, raw, _ = rig.request("POST", "/api/uploads", {"name": "c.mp4", "size": 16},
                                 cookie="sc_session=bogus", origin=rig.auth["origin"], csrf=rig.auth["csrf"])
    assert status in (401, 403) and assert_clean_json(raw)["error"]
