"""Finished portal uploads unused for two weeks are reclaimed at start-up."""
import os
import time

import portal_uploads


def _touch(path, age):
    path.write_bytes(b"x")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def test_stale_finished_uploads_are_removed_and_recent_or_foreign_files_kept(tmp_path):
    day = 24 * 3600
    stale = tmp_path / ("A" * 32 + ".mkv")
    recent = tmp_path / ("B" * 32 + ".mp4")
    foreign = tmp_path / "notes.mkv"
    sub = tmp_path / "link-acquisitions"
    sub.mkdir()
    _touch(stale, 20 * day)
    _touch(recent, 2 * day)
    _touch(foreign, 20 * day)
    portal_uploads.UploadManager(tmp_path, disk_usage=lambda p: None)
    assert not stale.exists()
    assert recent.exists() and foreign.exists() and sub.exists()


def test_recently_read_upload_is_kept(tmp_path):
    path = tmp_path / ("C" * 32 + ".mkv")
    path.write_bytes(b"x")
    old = time.time() - 30 * 24 * 3600
    os.utime(path, (time.time(), old))  # read yesterday, written a month ago
    portal_uploads.UploadManager(tmp_path, disk_usage=lambda p: None)
    assert path.exists()
