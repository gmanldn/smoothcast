"""Security #233: cache contents and crash-recovery state are owner-private.

All filesystem activity is isolated to pytest tmp_path; tests never launch
GTK, FFmpeg, receiver discovery or a real streaming server.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from unittest import mock

import pytest

import cache_privacy
import streamer


POSIX = pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@POSIX
def test_new_directory_is_0700_regardless_of_umask(tmp_path):
    directory = tmp_path / "cache" / "cast-control"
    previous = os.umask(0)
    try:
        cache_privacy.ensure_private_directory(directory)
    finally:
        os.umask(previous)
    assert mode(directory) == 0o700


@POSIX
def test_existing_0777_directory_tightens_without_deleting_anything(tmp_path):
    directory = tmp_path / "cast-control"
    directory.mkdir()
    old = directory / "user-metadata.txt"
    old.write_text("preserved", encoding="utf-8")
    directory.chmod(0o777)
    cache_privacy.ensure_private_directory(directory)
    assert mode(directory) == 0o700
    assert old.read_text(encoding="utf-8") == "preserved"


@POSIX
def test_symlink_to_cache_is_rejected_without_chmod_or_modification(tmp_path):
    target = tmp_path / "other-folder"
    target.mkdir()
    target.chmod(0o755)
    (target / "keep.txt").write_text("leave me", encoding="utf-8")
    shortcut = tmp_path / "cast-control"
    shortcut.symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError, PermissionError, NotADirectoryError)):
        cache_privacy.ensure_private_directory(shortcut)
    assert mode(target) == 0o755
    assert (target / "keep.txt").read_text(encoding="utf-8") == "leave me"


@POSIX
def test_foreign_uid_never_gets_cache_chmod(tmp_path):
    directory = tmp_path / "cast-control"
    directory.mkdir()
    directory.chmod(0o755)
    original = cache_privacy.os.fstat
    def foreign(fd):
        metadata = original(fd)
        return mock.Mock(st_mode=metadata.st_mode, st_uid=os.getuid() + 1)
    with mock.patch.object(cache_privacy.os, "fstat", side_effect=foreign), \
         mock.patch.object(cache_privacy.os, "fchmod",
                           side_effect=AssertionError("must never chmod foreign cache")):
        with pytest.raises(PermissionError, match="another user"):
            cache_privacy.ensure_private_directory(directory)


@POSIX
def test_session_saves_are_atomic_0600_even_under_permissive_umask(tmp_path):
    directory = tmp_path / "cast-control"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    session_file = directory / "session.json"
    session_file.write_text("old session", encoding="utf-8")
    session_file.chmod(0o644)
    previous = os.umask(0)
    try:
        cache_privacy.write_private_json_atomic(
            session_file, {"film": "/private/Movie.mkv", "position": 123})
    finally:
        os.umask(previous)
    assert mode(directory) == 0o700
    assert mode(session_file) == 0o600
    assert json.loads(session_file.read_text("utf-8")) == {
        "film": "/private/Movie.mkv", "position": 123}
    assert list(directory.glob(".session.json-*.tmp")) == []


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_failed_atomic_write_preserves_old_session_and_cleans_temp(tmp_path, failure):
    directory = tmp_path / "cache"
    session_file = directory / "session.json"
    cache_privacy.write_private_json_atomic(session_file, {"status": "old"})
    original = session_file.read_bytes()
    with mock.patch.object(cache_privacy.os, failure,
                           side_effect=OSError("injected write failure")):
        with pytest.raises(OSError, match="injected"):
            cache_privacy.write_private_json_atomic(session_file, {"status": "new"})
    assert session_file.read_bytes() == original
    assert list(directory.glob(".session.json-*.tmp")) == []


@POSIX
def test_load_session_tightens_existing_cache_before_read(tmp_path, monkeypatch):
    root = tmp_path / "old-cache"
    root.mkdir()
    root.chmod(0o755)
    saved = streamer.SessionState(file="/private/film.mkv", mode="direct",
                                  offset=0, duration=3600, device="TV", title="Film")
    monkeypatch.setattr(streamer, "SESSION_FILE", root / "session.json")
    # Write an old-world-readable state using a raw file operation, as a
    # pre-upgrade version of SmoothCast would have done.
    (root / "session.json").write_text(
        json.dumps(vars(saved)), encoding="utf-8")
    loaded = streamer.load_session()
    assert loaded is not None
    assert loaded.file == saved.file
    assert mode(root) == 0o700


@POSIX
def test_streamer_save_session_updates_old_file_mode_and_retains_state(tmp_path, monkeypatch):
    root = tmp_path / "old-cache"
    root.mkdir()
    root.chmod(0o755)
    session_file = root / "session.json"
    session_file.write_text("old", encoding="utf-8")
    session_file.chmod(0o644)
    monkeypatch.setattr(streamer, "SESSION_FILE", session_file)
    state = streamer.SessionState(file="/private/film.mkv", mode="direct",
                                  offset=13.5, duration=100, device="TV", title="Film")
    streamer._save_session(state)
    assert mode(root) == 0o700
    assert mode(session_file) == 0o600
    assert streamer.load_session().offset == 13.5


def test_private_cache_helper_is_in_installed_wheel_manifest():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"cache_privacy"' in pyproject
    assert "write_private_json_atomic(SESSION_FILE" in (
        root / "src/streamer.py").read_text(encoding="utf-8")
