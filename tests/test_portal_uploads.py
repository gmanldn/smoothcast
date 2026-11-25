"""Bounded, resumable LAN portal file staging."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import os
import stat
from unittest.mock import patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal_uploads


def manager(tmp_path, *, free=10 * 1024**3, early_cast_min_bytes=portal_uploads.EARLY_CAST_MIN_BYTES):
    return portal_uploads.UploadManager(
        tmp_path / "uploads",
        disk_usage=lambda _path: SimpleNamespace(free=free),
        early_cast_min_bytes=early_cast_min_bytes)


def _box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


# moov before mdat: a faststart/progressive MP4 that can cast while arriving.
FASTSTART_MP4 = _box(b"ftyp", b"isom") + _box(b"moov") + _box(b"mdat", b"\x00" * 16)
# mdat before moov: the index is at the end, so it must arrive fully first.
INDEXED_MP4 = _box(b"ftyp", b"isom") + _box(b"mdat", b"\x00" * 16) + _box(b"moov")


def test_chunks_are_bounded_resumable_and_owner_private(tmp_path):
    uploads = manager(tmp_path)
    created = uploads.create("session-one", "../holiday.mp4", 6)
    assert created["name"] == "holiday.mp4"
    path = uploads.root / f"{created['id']}.partial"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert uploads.append("session-one", created["id"], "bytes 0-2/6", 3,
                          BytesIO(b"abc"))["received"] == 3
    with pytest.raises(portal_uploads.UploadError, match="Upload not found"):
        uploads.status("other-session", created["id"])
    with pytest.raises(portal_uploads.UploadError, match="expects byte offset 3"):
        uploads.append("session-one", created["id"], "bytes 0-2/6", 3, BytesIO(b"xyz"))
    result = uploads.append("session-one", created["id"], "bytes 3-5/6", 3,
                            BytesIO(b"def"))
    assert result["complete"] and path.read_bytes() == b"abcdef"
    final, name, first_dispatch = uploads.finalize("session-one", created["id"])
    assert (name, final.read_bytes(), first_dispatch) == ("holiday.mp4", b"abcdef", True)
    with pytest.raises(portal_uploads.UploadError, match="still processing") as pending:
        uploads.finalize("session-one", created["id"])
    assert pending.value.status == 409
    assert uploads.status("session-one", created["id"])["dispatch_state"] == "pending"
    uploads.finish_dispatch("session-one", created["id"], accepted=False)
    assert uploads.status("session-one", created["id"])["dispatch_state"] == "not_submitted"
    assert uploads.finalize("session-one", created["id"])[2] is True
    uploads.finish_dispatch("session-one", created["id"], accepted=True)
    assert uploads.finalize("session-one", created["id"])[2] is False
    assert uploads.status("session-one", created["id"])["dispatch_state"] == "accepted"
    uploads.close()


def test_short_chunk_rolls_back_to_acknowledged_offset(tmp_path):
    uploads = manager(tmp_path)
    created = uploads.create("owner", "movie.mkv", 4)
    with pytest.raises(portal_uploads.UploadError, match="ended early"):
        uploads.append("owner", created["id"], "bytes 0-3/4", 4, BytesIO(b"xy"))
    assert uploads.status("owner", created["id"])["received"] == 0
    assert (uploads.root / f"{created['id']}.partial").stat().st_size == 0
    uploads.close()


@pytest.mark.parametrize("name", ["movie.txt", "", "..", "bad\nname.mp4"])
def test_rejects_unsafe_names(name, tmp_path):
    uploads = manager(tmp_path)
    with pytest.raises(portal_uploads.UploadError):
        uploads.create("owner", name, 1)
    uploads.close()


def test_reserves_space_caps_concurrency_and_cancels_partial(tmp_path):
    uploads = manager(tmp_path, free=portal_uploads.MIN_FREE_BYTES + 9)
    first = uploads.create("owner", "one.mp4", 5)
    with pytest.raises(portal_uploads.UploadError) as error:
        uploads.create("owner", "too-large.mp4", 5)
    assert error.value.status == 507
    uploads.cancel("owner", first["id"])
    assert not (uploads.root / f"{first['id']}.partial").exists()
    uploads.close()


def test_close_discards_partials_but_keeps_completed_sources(tmp_path):
    uploads = manager(tmp_path)
    partial = uploads.create("owner", "partial.mp4", 1)
    complete = uploads.create("owner", "complete.mp4", 1)
    uploads.append("owner", complete["id"], "bytes 0-0/1", 1, BytesIO(b"x"))
    final, _, _ = uploads.finalize("owner", complete["id"])
    uploads.close()
    assert not (uploads.root / f"{partial['id']}.partial").exists()
    assert final.read_bytes() == b"x"


def test_symlink_partial_is_rejected_without_reading_target(tmp_path):
    if not hasattr(os, "symlink") or os.name == "nt":
        pytest.skip("symlink checks require POSIX permissions")
    uploads = manager(tmp_path)
    created = uploads.create("owner", "safe.mp4", 1)
    partial = uploads.root / f"{created['id']}.partial"
    partial.unlink()
    target = tmp_path / "target"
    target.write_bytes(b"x")
    partial.symlink_to(target)
    with pytest.raises(OSError):
        uploads.append("owner", created["id"], "bytes 0-0/1", 1, BytesIO(b"y"))
    assert target.read_bytes() == b"x"
    partial.unlink()
    uploads.close()


def test_early_cast_starts_once_for_a_streamable_container_and_keeps_the_path(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    created = uploads.create("owner", "film.mkv", 6, "192.168.1.5")
    first = uploads.append("owner", created["id"], "bytes 0-2/6", 3, BytesIO(b"abc"))
    assert first["ready_to_cast"] is True
    assert first["cast_path"] == str(uploads.root / f"{created['id']}.partial")
    assert first["client"] == "192.168.1.5"
    assert uploads.status("owner", created["id"])["ready_to_cast"] is True
    # The threshold is crossed only once.
    second = uploads.append("owner", created["id"], "bytes 3-5/6", 3, BytesIO(b"def"))
    assert second["ready_to_cast"] is False
    uploads.mark_early_cast(created["id"], accepted=True)
    assert uploads.by_id(created["id"])["phase"] == "casting"
    path, name, dispatch = uploads.finalize("owner", created["id"])
    assert (name, dispatch) == ("film.mkv", True)
    # A cast may still be reading the growing file, so the path stays stable.
    assert path == uploads.root / f"{created['id']}.partial"
    assert path.read_bytes() == b"abcdef"
    uploads.close()


def test_queue_only_upload_never_starts_an_early_cast(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    created = uploads.create("owner", "film.mkv", 6, queue_only=True)
    assert uploads.is_queue_only("owner", created["id"]) is True
    result = uploads.append("owner", created["id"], "bytes 0-5/6", 6, BytesIO(b"abcdef"))
    assert result["ready_to_cast"] is False
    valid_video = SimpleNamespace(
        has_video=True, audio_streams=[], is_audio_only=False, duration=2.0,
    )
    with patch("streamer.ffprobe", return_value=valid_video):
        path, name, dispatch = uploads.finalize("owner", created["id"])
    assert dispatch is True and name == "film.mkv" and path.read_bytes() == b"abcdef"
    uploads.close()


def test_queue_only_rejects_unreadable_media_without_a_completed_source(tmp_path):
    uploads = manager(tmp_path)
    created = uploads.create("owner", "film.mkv", 6, queue_only=True)
    uploads.append("owner", created["id"], "bytes 0-5/6", 6, BytesIO(b"abcdef"))
    with patch("streamer.ffprobe", side_effect=RuntimeError("invalid media")):
        with pytest.raises(portal_uploads.UploadError, match="not readable media") as error:
            uploads.finalize("owner", created["id"])
    assert error.value.status == 422
    with pytest.raises(portal_uploads.UploadError, match="Upload not found"):
        uploads.status("owner", created["id"])
    assert not (uploads.root / f"{created['id']}.mkv").exists()
    uploads.close()


def test_indexed_mp4_is_not_cast_before_it_finishes_arriving(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    created = uploads.create("owner", "film.mp4", len(INDEXED_MP4))
    result = uploads.append("owner", created["id"], f"bytes 0-{len(INDEXED_MP4) - 1}/{len(INDEXED_MP4)}",
                            len(INDEXED_MP4), BytesIO(INDEXED_MP4))
    assert result["ready_to_cast"] is False
    assert uploads.by_id(created["id"])["phase"] == "finalizing"
    uploads.close()


def test_faststart_mp4_is_cast_while_arriving(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    prefix = FASTSTART_MP4[:24]
    created = uploads.create("owner", "film.mp4", len(FASTSTART_MP4))
    result = uploads.append("owner", created["id"], f"bytes 0-{len(prefix) - 1}/{len(FASTSTART_MP4)}",
                            len(prefix), BytesIO(prefix))
    assert result["ready_to_cast"] is True
    uploads.close()


def test_faststart_mp4_waits_for_complete_front_index_and_retries(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    ftyp = _box(b"ftyp", b"isom")
    moov = _box(b"moov", b"12345678")
    data = ftyp + moov + _box(b"mdat", b"1234567890123456")
    created = uploads.create("owner", "film.mp4", len(data))
    offset = 0
    for end, ready in ((len(ftyp), False), (len(ftyp) + 8, False),
                       (len(ftyp + moov), True), (len(data), False)):
        result = uploads.append("owner", created["id"],
                                f"bytes {offset}-{end - 1}/{len(data)}",
                                end - offset, BytesIO(data[offset:end]))
        assert result["ready_to_cast"] is ready
        offset = end
    uploads.close()


def test_rear_index_mp4_never_starts_early_after_later_chunks(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    data = INDEXED_MP4
    created = uploads.create("owner", "film.mp4", len(data))
    offset = 0
    for end in (12, 20, len(data) - 1, len(data)):
        result = uploads.append("owner", created["id"],
                                f"bytes {offset}-{end - 1}/{len(data)}",
                                end - offset, BytesIO(data[offset:end]))
        assert result["ready_to_cast"] is False
        offset = end
    uploads.close()


def test_declined_early_cast_falls_back_and_snapshot_reports_progress(tmp_path):
    uploads = manager(tmp_path, early_cast_min_bytes=1)
    created = uploads.create("owner", "film.mkv", 6)
    uploads.append("owner", created["id"], "bytes 0-2/6", 3, BytesIO(b"abc"))
    uploads.mark_early_cast(created["id"], accepted=False)
    assert uploads.by_id(created["id"])["phase"] == "receiving"
    snapshot = uploads.snapshot()
    assert snapshot and snapshot[0]["name"] == "film.mkv"
    assert snapshot[0]["received"] == 3 and snapshot[0]["percent"] == 50
    assert uploads.by_id("missing") is None
    uploads.close()


def test_format_portal_activity_summarises_phases():
    assert portal_uploads.format_portal_activity([]) == "No client activity"
    text = portal_uploads.format_portal_activity([
        {"name": "film.mkv", "phase": "casting", "percent": 40, "client": "192.168.1.5"},
        {"name": "clip.mp4", "phase": "receiving", "percent": 10,
         "bytes_per_second": 5 * 1024 * 1024, "client": ""},
    ])
    assert "192.168.1.5 · film.mkv: casting now (40% received)" in text
    assert "clip.mp4: receiving 10% (5.0 MB/s)" in text


def test_chunk_cannot_exceed_declared_file_size(tmp_path):
    uploads = manager(tmp_path)
    created = uploads.create("owner", "movie.mp4", 2)
    with pytest.raises(portal_uploads.UploadError, match="range or size"):
        uploads.append("owner", created["id"], "bytes 0-2/2", 3, BytesIO(b"abc"))
    assert uploads.status("owner", created["id"])["received"] == 0
    uploads.append("owner", created["id"], "bytes 0-1/2", 2, BytesIO(b"ab"))
    with pytest.raises(portal_uploads.UploadError, match="range or size"):
        uploads.append("owner", created["id"], "bytes 2-2/2", 1, BytesIO(b"c"))
    uploads.close()


def test_create_reclaims_idle_slots_but_preserves_recent_progress(tmp_path):
    now = 0
    uploads = portal_uploads.UploadManager(
        tmp_path / "uploads", clock=lambda: now,
        disk_usage=lambda _path: SimpleNamespace(free=10 * 1024**3),
    )
    active, *idle = [uploads.create("owner", "movie.mp4", 2)["id"]
                     for _ in range(portal_uploads.MAX_ACTIVE_UPLOADS)]
    now = portal_uploads.PARTIAL_TTL_SECONDS - 1
    uploads.append("owner", active, "bytes 0-0/2", 1, BytesIO(b"a"))
    now += 1
    uploads.create("owner", "new.mp4", 2)
    for upload_id in idle:
        with pytest.raises(portal_uploads.UploadError, match="Upload not found"):
            uploads.status("owner", upload_id)
    assert uploads.status("owner", active)["received"] == 1
    uploads.close()


def test_can_cancel_staged_upload_after_cast_rejection(tmp_path):
    uploads = manager(tmp_path)
    created = uploads.create("owner", "movie.mp4", 1)
    uploads.append("owner", created["id"], "bytes 0-0/1", 1, BytesIO(b"x"))
    path, _, _ = uploads.finalize("owner", created["id"])
    with pytest.raises(portal_uploads.UploadError, match="Casting has already been requested"):
        uploads.cancel("owner", created["id"])
    uploads.finish_dispatch("owner", created["id"], accepted=False)
    uploads.cancel("owner", created["id"])
    assert not path.exists()


def test_large_chunk_is_streamed_in_bounded_reads_and_synced_once(tmp_path):
    """One 8 MiB chunk replaces four 2 MiB requests without weakening ACK."""
    uploads = manager(tmp_path)
    size = portal_uploads.CHUNK_SIZE
    assert size == 8 * 1024 * 1024
    created = uploads.create("owner", "large.mkv", size)
    assert created["chunk_size"] == size

    class MeasuredSource:
        def __init__(self):
            self.reads = []

        def read(self, amount):
            assert 0 < amount <= portal_uploads.READ_SIZE
            self.reads.append(amount)
            return b"x" * amount

    source = MeasuredSource()
    with patch("portal_uploads.os.fsync", wraps=os.fsync) as synced:
        result = uploads.append("owner", created["id"], f"bytes 0-{size - 1}/{size}",
                                size, source)
    assert result["received"] == size
    assert len(source.reads) == size // portal_uploads.READ_SIZE
    assert synced.call_count == 1
    uploads.close()


def test_small_legacy_chunks_resume_and_oversized_chunk_is_rejected(tmp_path):
    uploads = manager(tmp_path)
    size = portal_uploads.CHUNK_SIZE
    legacy = 2 * 1024 * 1024
    total = legacy + size + 1  # Oversized second chunk fits file but exceeds cap.
    created = uploads.create("owner", "movie.mkv", total)
    uploads.append("owner", created["id"], f"bytes 0-{legacy - 1}/{total}",
                   legacy, BytesIO(b"a" * legacy))
    assert uploads.status("owner", created["id"])["received"] == legacy
    with pytest.raises(portal_uploads.UploadError, match="range or size"):
        uploads.append("owner", created["id"],
                       f"bytes {legacy}-{legacy + size}/{total}",
                       size + 1, BytesIO(b""))
    assert uploads.status("owner", created["id"])["received"] == legacy
    uploads.close()


def test_activity_snapshot_never_waits_for_inflight_chunk(tmp_path):
    """GTK must not wait for the lock held while reading a browser chunk."""
    import threading

    uploads = manager(tmp_path)
    upload_id = uploads.create("owner", "clip.mkv", 6)["id"]
    uploads.append("owner", upload_id, "bytes 0-2/6", 3, BytesIO(b"abc"))
    upload = uploads._get("owner", upload_id)
    results = []
    done = threading.Event()

    def read_activity():
        try:
            results.extend((uploads.snapshot()[0], uploads.by_id(upload_id)))
        finally:
            done.set()

    with upload.lock:
        thread = threading.Thread(target=read_activity, daemon=True)
        thread.start()
        completed_without_waiting = done.wait(1.0)
    thread.join(timeout=2.0)
    assert completed_without_waiting, "activity refresh blocked behind a live HTTP chunk"
    assert len(results) == 2
    assert all(row["received"] == 3 and row["percent"] == 50 for row in results)
    uploads.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows does not require directory fsync")
def test_finalize_retry_preserves_file_after_directory_sync_failure(tmp_path):
    """A rename that succeeds before fsync fails must remain recoverable."""
    import errno

    uploads = manager(tmp_path)
    upload_id = uploads.create("owner", "clip.mp4", 6)["id"]
    uploads.append("owner", upload_id, "bytes 0-5/6", 6, BytesIO(b"abcdef"))
    with patch.object(portal_uploads.os, "fsync", side_effect=OSError(errno.EIO, "sync failed")):
        with pytest.raises(OSError, match="sync failed"):
            uploads.finalize("owner", upload_id)
        assert uploads.status("owner", upload_id)["complete"] is False
    final, name, dispatch = uploads.finalize("owner", upload_id)
    assert (final.read_bytes(), name, dispatch) == (b"abcdef", "clip.mp4", True)
    assert uploads.status("owner", upload_id)["complete"] is True
    uploads.finish_dispatch("owner", upload_id, accepted=True)
    assert uploads.finalize("owner", upload_id)[2] is False
    uploads.close()


def test_accepted_upload_cannot_report_a_different_room_action(tmp_path):
    uploads = manager(tmp_path)
    upload_id = uploads.create("owner", "clip.mp4", 3)["id"]
    uploads.append("owner", upload_id, "bytes 0-2/3", 3, BytesIO(b"abc"))
    assert uploads.finalize("owner", upload_id, queue_only=False)[2]
    uploads.finish_dispatch("owner", upload_id, accepted=True)
    with pytest.raises(portal_uploads.UploadError, match="different accepted room action"):
        uploads.finalize("owner", upload_id, queue_only=True)
    assert uploads.finalize("owner", upload_id, queue_only=False)[2] is False
    uploads.close()


def test_rejected_media_does_not_exhaust_guest_upload_slots(tmp_path):
    uploads = manager(tmp_path)
    with patch("streamer.ffprobe", side_effect=RuntimeError("invalid media")):
        for index in range(portal_uploads.MAX_ACTIVE_UPLOADS + 2):
            upload_id = uploads.create(
                "owner", f"broken-{index}.mkv", 3, queue_only=True)["id"]
            uploads.append("owner", upload_id, "bytes 0-2/3", 3, BytesIO(b"bad"))
            with pytest.raises(portal_uploads.UploadError) as error:
                uploads.finalize("owner", upload_id)
            assert error.value.status == 422
    good = uploads.create("owner", "good.mp4", 3)
    assert good["received"] == 0
    assert len(uploads.snapshot()) == 1
    uploads.close()
