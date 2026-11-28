"""Checkpoint and retry coverage for coalesced browser uploads."""

from io import BytesIO
import os
import stat

import pytest

import portal_uploads


@pytest.fixture
def upload(tmp_path):
    now = [1.0]
    manager = portal_uploads.UploadManager(tmp_path, clock=lambda: now[0])
    try:
        yield manager, now
    finally:
        manager.close()


def test_second_chunk_checkpoints_by_bytes(upload, monkeypatch):
    manager, _ = upload
    chunk_size = portal_uploads.CHUNK_SIZE
    total = 2 * chunk_size
    upload_id = manager.create("owner", "film.mkv", total)["id"]
    real_sync = os.fsync
    synced = []

    def sync(fd):
        real_sync(fd)
        synced.append(os.fstat(fd).st_size)

    monkeypatch.setattr(os, "fsync", sync)
    first = manager.append("owner", upload_id, f"bytes 0-{chunk_size - 1}/{total}",
                           chunk_size, BytesIO(b"a" * chunk_size))
    assert (first["received"], first["committed"], synced) == (chunk_size, 0, [])

    second = manager.append("owner", upload_id, f"bytes {chunk_size}-{total - 1}/{total}",
                            chunk_size, BytesIO(b"b" * chunk_size))
    assert (second["received"], second["committed"], synced) == (total, total, [total])


def test_chunk_checkpoints_by_time(upload):
    manager, now = upload
    upload_id = manager.create("owner", "film.mkv", 6)["id"]
    first = manager.append("owner", upload_id, "bytes 0-2/6", 3, BytesIO(b"abc"))
    assert first["committed"] == 0

    now[0] += portal_uploads.CHECKPOINT_SECONDS
    second = manager.append("owner", upload_id, "bytes 3-5/6", 3, BytesIO(b"def"))
    assert second["committed"] == 6


def test_failed_checkpoint_restores_offsets_and_accepts_original_range(upload, monkeypatch):
    manager, _ = upload
    upload_id = manager.create("owner", "film.mkv", 6)["id"]
    first = manager.append("owner", upload_id, "bytes 0-2/6", 3, BytesIO(b"abc"))
    assert (first["received"], first["committed"]) == (3, 0)

    real_sync = os.fsync
    calls = 0

    def fail_second_sync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(28, "No space left on device")
        return real_sync(fd)

    monkeypatch.setattr(portal_uploads, "CHECKPOINT_BYTES", 3)
    monkeypatch.setattr(os, "fsync", fail_second_sync)
    with pytest.raises(OSError, match="No space"):
        manager.append("owner", upload_id, "bytes 3-5/6", 3, BytesIO(b"def"))

    status = manager.status("owner", upload_id)
    assert (status["received"], status["committed"]) == (3, 0)
    assert manager._get("owner", upload_id).partial_path.stat().st_size == 3

    retry = manager.append("owner", upload_id, "bytes 3-5/6", 3, BytesIO(b"def"))
    assert (retry["received"], retry["committed"]) == (6, 6)


def test_finalize_syncs_trailing_bytes(upload, monkeypatch):
    manager, _ = upload
    upload_id = manager.create("owner", "film.mkv", 3)["id"]
    receipt = manager.append("owner", upload_id, "bytes 0-2/3", 3, BytesIO(b"abc"))
    assert receipt["committed"] == 0
    real_sync = os.fsync
    synced = []

    def sync(fd):
        real_sync(fd)
        synced.append(os.fstat(fd).st_mode)

    monkeypatch.setattr(os, "fsync", sync)
    final, _, _ = manager.finalize("owner", upload_id)
    assert manager.status("owner", upload_id)["committed"] == 3
    assert stat.S_ISREG(synced[0])
    assert final.read_bytes() == b"abc"
