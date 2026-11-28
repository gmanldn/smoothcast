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
        size = os.fstat(fd).st_size
        if size >= total:  # sidecar and directory syncs are separate metadata costs
            synced.append(size)

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


def test_incomplete_finalize_does_not_flush_pending_bytes(upload, monkeypatch):
    manager, _ = upload
    upload_id = manager.create("owner", "film.mkv", 10)["id"]
    receipt = manager.append("owner", upload_id, "bytes 0-3/10", 4, BytesIO(b"abcd"))
    assert (receipt["received"], receipt["committed"]) == (4, 0)

    real_sync = os.fsync
    synced_sizes = []

    def sync(fd):
        synced_sizes.append(os.fstat(fd).st_size)
        return real_sync(fd)

    monkeypatch.setattr(os, "fsync", sync)
    for _ in range(2):
        with pytest.raises(portal_uploads.UploadError) as incomplete:
            manager.finalize("owner", upload_id)
        assert incomplete.value.status == 409
    status = manager.status("owner", upload_id)
    assert (status["received"], status["committed"]) == (4, 0)
    assert synced_sizes == []

    monkeypatch.setattr(portal_uploads, "CHECKPOINT_BYTES", 100)
    receipt = manager.append("owner", upload_id, "bytes 4-9/10", 6, BytesIO(b"efghij"))
    assert (receipt["received"], receipt["committed"]) == (10, 0)
    final, _, should_dispatch = manager.finalize("owner", upload_id)
    assert should_dispatch is True
    assert synced_sizes[0] == 10  # the complete file is durable before dispatch is accepted
    assert final.read_bytes() == b"abcdefghij"
    manager.finish_dispatch("owner", upload_id, accepted=True)
    assert manager.status("owner", upload_id)["complete"] is True


def test_restart_recovers_queue_upload_only_to_the_durable_offset(tmp_path, monkeypatch):
    now = [1.0]
    first = portal_uploads.UploadManager(tmp_path, clock=lambda: now[0])
    monkeypatch.setattr(portal_uploads, "CHECKPOINT_BYTES", 3)
    created = first.create("owner", "song.mp3", 6, queue_only=True)
    upload_id = created["id"]
    first.append("owner", upload_id, "bytes 0-2/6", 3, BytesIO(b"abc"))

    monkeypatch.setattr(portal_uploads, "CHECKPOINT_BYTES", 100)
    volatile = first.append("owner", upload_id, "bytes 3-5/6", 3, BytesIO(b"def"))
    assert (volatile["received"], volatile["committed"]) == (6, 3)
    sidecar = tmp_path / f"{upload_id}.upload.json"
    assert b'"owner":"owner"' not in sidecar.read_bytes()

    recovered = portal_uploads.UploadManager(tmp_path, clock=lambda: now[0])
    status = recovered.status("owner", upload_id)
    assert (status["received"], status["committed"]) == (3, 3)
    assert (tmp_path / f"{upload_id}.partial").read_bytes() == b"abc"
    with pytest.raises(portal_uploads.UploadError):
        recovered.status("another-owner", upload_id)

    retry = recovered.append("owner", upload_id, "bytes 3-5/6", 3, BytesIO(b"def"))
    assert (retry["received"], retry["committed"]) == (6, 3)
    assert (tmp_path / f"{upload_id}.partial").read_bytes() == b"abcdef"
    assert sidecar.exists()
    recovered.close()
    first.close()


def test_torn_checkpoint_metadata_never_recovers_or_authorizes_partial(tmp_path):
    first = portal_uploads.UploadManager(tmp_path, clock=lambda: 1.0)
    created = first.create("owner", "song.mp3", 3, queue_only=True)
    upload_id = created["id"]
    first.append("owner", upload_id, "bytes 0-2/3", 3, BytesIO(b"abc"))
    (tmp_path / f"{upload_id}.upload.json").write_text("{torn", encoding="utf-8")

    recovered = portal_uploads.UploadManager(tmp_path, clock=lambda: 2.0)
    with pytest.raises(portal_uploads.UploadError):
        recovered.status("owner", upload_id)
    assert (tmp_path / f"{upload_id}.partial").read_bytes() == b"abc"
    assert not (tmp_path / f"{upload_id}.upload.json").exists()
    recovered.close()
    first.close()


def test_restart_preserves_expiry_and_removes_abandoned_metadata_temp(tmp_path):
    first = portal_uploads.UploadManager(tmp_path, clock=lambda: 1.0)
    upload_id = first.create("owner", "song.mp3", 3, queue_only=True)["id"]
    first.append("owner", upload_id, "bytes 0-2/3", 3, BytesIO(b"abc"))
    temp = tmp_path / f".{upload_id}.upload.tmp"
    temp.write_text("interrupted write", encoding="ascii")

    recovered = portal_uploads.UploadManager(
        tmp_path, clock=lambda: 2 + portal_uploads.PARTIAL_TTL_SECONDS)
    with pytest.raises(portal_uploads.UploadError):
        recovered.status("owner", upload_id)
    assert not temp.exists()
    assert not (tmp_path / f"{upload_id}.upload.json").exists()
    assert (tmp_path / f"{upload_id}.partial").read_bytes() == b"abc"
    recovered.close()
    first.close()
