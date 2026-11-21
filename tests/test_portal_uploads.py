"""Bounded, resumable LAN portal file staging."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import os
import stat
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
    assert uploads.finalize("session-one", created["id"])[2] is False
    uploads.finish_dispatch("session-one", created["id"], accepted=False)
    assert uploads.finalize("session-one", created["id"])[2] is True
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
    path, name, dispatch = uploads.finalize("owner", created["id"])
    assert dispatch is True and name == "film.mkv" and path.read_bytes() == b"abcdef"
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
