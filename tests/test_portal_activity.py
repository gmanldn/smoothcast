"""Portal early-cast reconciliation logic (no GTK window, no sockets)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import os
import pathlib
import stat
import sys
import textwrap
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import command_trace
import portal_commands
import peer_discovery_ui
import paths
import portal_uploads
import portal_status
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


def _build_window(tmp_path, *, idle_add=None):
    methods = main_window_methods()
    code = "\n".join(textwrap.indent(methods[name], "    ") for name in (
        "_portal_upload_path", "_portal_queue_action", "_portal_handle",
        "_portal_note_display_name",
        "_portal_dispatch", "_publish_portal_status",
        "_portal_apply_music_autogain", "_reconcile_portal_casts",
        "_retry_portal_cast"))
    idle: list = []
    namespace = {
        "portal": SimpleNamespace(PortalRequestError=_PortalRequestError),
        "command_trace": command_trace,
        "portal_commands": portal_commands,
        "portal_uploads": portal_uploads,
        "save_config": lambda cfg: saved.append(dict(cfg)),
        "pathlib": pathlib, "os": os, "stat": stat, "time": time,
        "PORTAL_CAST_GRACE_SECONDS": 5.0,
        "threading": threading, "paths": paths,
        "GLib": SimpleNamespace(
            idle_add=idle_add or (lambda fn, *args: idle.append((fn, args)))),
    }
    exec(compile("class Window:\n" + code, "<portal-handle-test>", "exec"), namespace)
    window = namespace["Window"]()
    saved = []
    window.busy = False
    window.now_playing = None
    window.queue = []
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
    # Retry consent is covered by test_portal_recovery_target.py; here the
    # confirmed receiver is unchanged so the retry path itself is exercised.
    uploads.recovery_target = lambda upload_id, path: "confirmed"
    window._portal_upload_target = lambda: {"target_id": "confirmed"}
    window.saved_configs = saved
    window._portal_fence = portal_commands.CommandFence()
    window._device = lambda: "TV"
    window.device_state = "PLAYING"
    window.session = SimpleNamespace(state=object())
    window.external = False
    window._preview_path = None
    window._dlna_cancel = None
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


def test_status_dispatch_reads_snapshot_without_idle_callback(tmp_path):
    window, _uploads, idle = _build_window(tmp_path)
    window._portal_status = portal_status.PublishedStatus()
    window._portal_status.publish({"title": "Cached", "queue": []})

    result = window._portal_dispatch("status", {})

    assert result["title"] == "Cached"
    assert result["snapshot_version"] == 1
    assert isinstance(result["snapshot_age_ms"], int)
    assert idle == []


def test_portal_mutation_and_snapshot_publication_stay_on_gtk_thread(tmp_path):
    callbacks = Queue()
    window, uploads, _idle = _build_window(tmp_path, idle_add=callbacks.put)
    window._portal_status = portal_status.PublishedStatus()
    gtk_thread = threading.get_ident()
    handle = window._portal_handle

    def guarded_handle(operation, payload):
        assert threading.get_ident() == gtk_thread
        if operation == "status":
            return {"music_autogain": window.cfg["music_autogain"]}
        return handle(operation, payload)

    window._portal_handle = guarded_handle
    window._publish_portal_status()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            mutation = pool.submit(window._portal_dispatch, "music_autogain", {"value": True})
            run_on_gtk = callbacks.get(timeout=1)
            before = pool.submit(window._portal_dispatch, "status", {}).result(timeout=1)
            assert before["music_autogain"] is False
            assert before["snapshot_version"] == 1

            assert run_on_gtk() is False
            assert mutation.result(timeout=1) == "Music autogain enabled."
            after = pool.submit(window._portal_dispatch, "status", {}).result(timeout=1)
            assert after["music_autogain"] is True
            assert after["snapshot_version"] == 2
            assert callbacks.empty()
    finally:
        uploads.close()


def test_peer_links_open_only_compatible_hosts_and_keep_the_pin_boundary():
    class Widget:
        def __init__(self, label="", uri=""):
            self.label, self.uri = label, uri
            self.classes = []
            self.tooltip = ""
            self.parent = None

        def add_css_class(self, name):
            self.classes.append(name)

        def set_halign(self, _align):
            pass

        def set_tooltip_text(self, value):
            self.tooltip = value

        def get_next_sibling(self):
            index = self.parent.children.index(self)
            return self.parent.children[index + 1] if index + 1 < len(
                self.parent.children) else None

    class Box:
        def __init__(self):
            self.children = []

        def get_first_child(self):
            return self.children[0] if self.children else None

        def remove(self, child):
            self.children.remove(child)
            child.parent = None

        def append(self, child):
            child.parent = self
            self.children.append(child)

    class LinkButton:
        @staticmethod
        def new_with_label(uri, label):
            return Widget(label=label, uri=uri)

    gtk = SimpleNamespace(
        Label=lambda **kwargs: Widget(label=kwargs.get("label", "")),
        LinkButton=LinkButton,
        Align=SimpleNamespace(START="start"),
    )
    window = SimpleNamespace()
    window.portal_peers_box = Box()
    rows = [
        ("a" * 32, "http://192.168.1.20:8765/", "smoothcast-lounge", True),
        ("b" * 32, "http://192.168.1.21:8765/", "smoothcast-old", False),
    ]
    peer_discovery_ui.refresh_peer_links(window, [
        {"id": peer_id, "url": url, "name": name, "compatible": compatible}
        for peer_id, url, name, compatible in rows
    ], available=True, gtk=gtk)
    first, second = window.portal_peers_box.children
    assert first.uri == rows[0][1]
    assert "PIN is required" in first.tooltip
    assert second.label == "smoothcast-old (incompatible)"
    assert second.uri == ""
    peer_discovery_ui.refresh_peer_links(
        window, [], available=False, status="Peer discovery is unavailable", gtk=gtk)
    assert [child.label for child in window.portal_peers_box.children] == [
        "Peer discovery is unavailable"]


def test_immediate_receiver_rejection_does_not_poison_upload_id(tmp_path):
    window, uploads, _ = _build_window(tmp_path)
    upload_id = uploads.create("owner", "film.mkv", 4)["id"]
    partial = uploads.root / f"{upload_id}.partial"
    partial.write_bytes(b"abcd")
    payload = {"path": str(partial), "name": "film.mkv", "upload_id": upload_id}
    accepted_cast = window._cast_path
    window._cast_path = lambda *_args: "Choose a room receiver before casting"

    with pytest.raises(_PortalRequestError, match="Choose a room receiver") as rejected:
        window._portal_handle("cast_upload", {**payload, "early": True})
    assert rejected.value.status == 409
    assert upload_id not in window._portal_accepted_uploads
    assert upload_id not in window._portal_cast_uploads
    assert window._portal_early is False

    window._cast_path = accepted_cast
    window._portal_handle("cast_upload", {**payload, "early": False})
    assert window.casts == [(str(partial), 0)]
    assert upload_id in window._portal_accepted_uploads
    uploads.close()


def test_status_publication_failure_cannot_erase_command_receipt(tmp_path):
    def immediate_idle(callback):
        callback()
        return 1

    window, uploads, _ = _build_window(tmp_path, idle_add=immediate_idle)

    def failed_publish():
        raise RuntimeError("status serialization failed")

    window._publish_portal_status = failed_publish
    window._portal_handle = lambda _operation, _payload: "accepted once"
    assert window._portal_dispatch("music_autogain", {"value": True}) == "accepted once"
    uploads.close()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_early_cast_fallback_clears_deduplication(tmp_path, raises):
    window, uploads, _ = _build_window(tmp_path)
    upload_id = uploads.create("owner", "film.mkv", 4)["id"]
    path = uploads.root / f"{upload_id}.partial"

    def rejected(*_args):
        if raises:
            raise RuntimeError("could not submit")
        return "Choose a room receiver before casting"

    window._cast_path = rejected
    if raises:
        with pytest.raises(RuntimeError, match="could not submit"):
            window._retry_portal_cast(upload_id, str(path))
    else:
        assert window._retry_portal_cast(upload_id, str(path)) is False
    assert upload_id not in window._portal_accepted_uploads
    assert upload_id not in window._portal_cast_uploads
    uploads.close()
