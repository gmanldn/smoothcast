"""Portal early-cast reconciliation logic (no GTK window, no sockets)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import os
import pathlib
import stat
import sys
import textwrap
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portal_commands
import portal_uploads
from gui_source import main_window_methods


def test_stale_early_casts_ignores_starting_and_playing_casts():
    casting = {
        "playing": ("/p/play", 0.0),
        "starting": ("/p/start", 199.0),
        "stale": ("/p/stale", 0.0),
    }
    # The playing upload is kept, the one still within its grace period is kept,
    # and only the cast that never started is reported stale.
    assert portal_uploads.stale_early_casts(
        casting, now=200.0, busy=False, now_playing="/p/play", grace=5.0) == ["stale"]
    # A busy window never marks anything stale.
    assert portal_uploads.stale_early_casts(
        casting, now=200.0, busy=True, now_playing="/p/play", grace=5.0) == []
    assert portal_uploads.stale_early_casts(
        {}, now=200.0, busy=False, now_playing=None, grace=5.0) == []


class _PortalRequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _build_window(tmp_path):
    methods = main_window_methods()
    code = "\n".join(textwrap.indent(methods[name], "    ") for name in (
        "_portal_upload_path", "_portal_queue_action", "_portal_handle",
        "_portal_apply_music_autogain", "_reconcile_portal_casts",
        "_retry_portal_cast"))
    idle: list = []
    namespace = {
        "portal": SimpleNamespace(PortalRequestError=_PortalRequestError),
        "portal_commands": portal_commands,
        "portal_uploads": portal_uploads,
        "save_config": lambda cfg: saved.append(dict(cfg)),
        "pathlib": pathlib, "os": os, "stat": stat, "time": time,
        "PORTAL_CAST_GRACE_SECONDS": 5.0,
        "GLib": SimpleNamespace(idle_add=lambda fn, *args: idle.append((fn, args))),
    }
    exec(compile("class Window:\n" + code, "<portal-handle-test>", "exec"), namespace)
    window = namespace["Window"]()
    saved = []
    window.busy = False
    window.now_playing = None
    window._closing = False
    window._portal_cast_uploads = {}
    window._portal_cast_retried = set()
    window._portal_accepted_uploads = set()
    window.cfg = {"music_autogain": False}
    window.casts = []
    window.early_flags = []
    window.set_selection = lambda path: None

    def _cast(path, offset=None):
        window.casts.append((str(path), offset))
        window.early_flags.append(getattr(window, "_portal_early", None))

    window._cast_path = _cast
    uploads = portal_uploads.UploadManager(tmp_path / "uploads")
    window._portal = SimpleNamespace(uploads=uploads,
                                     server=SimpleNamespace(uploads=uploads))
    window.saved_configs = saved
    window._portal_fence = portal_commands.CommandFence()
    window._device = lambda: "TV"
    window.stop_button = SimpleNamespace(get_sensitive=lambda: True)
    window.stop_calls = []
    window.stop_stream = lambda: window.stop_calls.append("stop")
    return window, uploads, idle


def test_phone_autogain_toggle_persists_and_reports_shared_setting(tmp_path):
    window, _uploads, _idle = _build_window(tmp_path)
    assert window._portal_handle("music_autogain", {"value": True}).startswith(
        "Music autogain enabled")
    assert window.cfg["music_autogain"] is True
    assert window.saved_configs == [{"music_autogain": True}]
    try:
        window._portal_handle("music_autogain", {"value": 1})
    except _PortalRequestError as exc:
        assert exc.status == 400
    else:
        raise AssertionError("non-boolean setting was accepted")


def test_early_dispatch_tracks_the_cast_and_dedupes_finalize(tmp_path):
    window, uploads, _ = _build_window(tmp_path)
    created = uploads.create("owner", "film.mkv", 4)
    upload_id = created["id"]
    partial = uploads.root / f"{upload_id}.partial"
    partial.write_bytes(b"abcd")
    payload = {"path": str(partial), "name": "film.mkv", "upload_id": upload_id}
    assert window._portal_handle("cast_upload", {**payload, "early": True}) == (
        "Upload received; casting started.")
    assert window.casts == [(str(partial), 0)]
    assert window.early_flags == [True]  # forced transcode, never direct-cast
    assert upload_id in window._portal_cast_uploads
    assert upload_id in window._portal_accepted_uploads
    # The finalize dispatch for the same upload is deduped, not cast again.
    window._portal_handle("cast_upload", {**payload, "early": False})
    assert window.casts == [(str(partial), 0)]


def test_reconcile_recovers_a_completed_upload_whose_early_cast_never_started(tmp_path):
    window, uploads, idle = _build_window(tmp_path)
    created = uploads.create("owner", "film.mkv", 4)
    upload_id = created["id"]
    uploads.append("owner", upload_id, "bytes 0-3/4", 4, BytesIO(b"abcd"))
    path, _name, _dispatch = uploads.finalize("owner", upload_id)
    window._portal_handle("cast_upload", {"path": str(path), "name": "film.mkv",
                                          "upload_id": upload_id, "early": True})
    # Simulate a cast that never started, past the grace period.
    window._portal_cast_uploads[upload_id] = (str(path), time.monotonic() - 60)
    window._reconcile_portal_casts()
    assert upload_id not in window._portal_cast_uploads
    assert upload_id not in window._portal_accepted_uploads
    assert upload_id in window._portal_cast_retried
    assert any(fn == window._retry_portal_cast for fn, _args in idle)
    # The retry casts the finished file and is tracked again.
    window.casts.clear()
    window.early_flags.clear()
    window._retry_portal_cast(upload_id, str(path))
    assert window.casts == [(str(path), 0)]
    assert window.early_flags == [False]  # the finished file may direct-cast
    assert upload_id in window._portal_cast_uploads


def test_reconcile_keeps_a_playing_early_cast(tmp_path):
    window, uploads, idle = _build_window(tmp_path)
    created = uploads.create("owner", "film.mkv", 4)
    upload_id = created["id"]
    partial = uploads.root / f"{upload_id}.partial"
    partial.write_bytes(b"abcd")
    window._portal_handle("cast_upload", {"path": str(partial), "name": "film.mkv",
                                          "upload_id": upload_id, "early": True})
    window._portal_cast_uploads[upload_id] = (str(partial), time.monotonic() - 60)
    window.now_playing = str(partial)
    window._reconcile_portal_casts()
    assert upload_id not in window._portal_cast_uploads
    assert upload_id in window._portal_accepted_uploads  # still deduped
    assert idle == []


def test_cast_path_forces_transcode_for_an_early_portal_cast():
    cast = main_window_methods()["_cast_path"]
    assert 'and not getattr(self, "_portal_early", False)' in cast


def test_command_branch_runs_fenced_mutation(tmp_path):
    window, _uploads, _idle = _build_window(tmp_path)
    session_id, revision, _owner = window._portal_fence.snapshot()
    envelope = portal_commands.MutationEnvelope(
        client_id="phone", command_id="c1", expected_session_id=session_id,
        expected_revision=revision, action="stop", payload={})
    receipt = window._portal_handle("command", {"envelope": envelope})
    assert receipt.command_id == "c1"
    assert window.stop_calls == ["stop"]
    window._portal_fence.rotate(owner="TV")
    with pytest.raises(portal_commands.CommandError):
        window._portal_handle("command", {"envelope": envelope})
