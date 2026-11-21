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


def manager(tmp_path, *, free=10 * 1024**3):
    return portal_uploads.UploadManager(
        tmp_path / "uploads", disk_usage=lambda _path: SimpleNamespace(free=free))


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
