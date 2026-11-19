"""Headless incremental index tests; no external media or ffprobe required."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

MODULE = Path(__file__).resolve().parents[1] / "src" / "library_index.py"
spec = importlib.util.spec_from_file_location("library_index", MODULE)
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


def test_indexes_in_chunks_and_reuses_stable_media(tmp_path):
    root, db = tmp_path / "media", tmp_path / "db.sqlite3"
    root.mkdir()
    movie = root / "Something.mkv"
    movie.write_bytes(b"1234567890" * 300_000)
    (root / "notes.txt").write_text("not media")
    first = index.scan(root, db)
    assert first["hashed"] == 1 and first["reused"] == 0 and first["complete"]
    row = index.list_media(db)[0]
    assert row["sha256"] == hashlib.sha256(movie.read_bytes()).hexdigest()
    second = index.scan(root, db)
    assert second["hashed"] == 0 and second["reused"] == 1
    movie.write_bytes(b"changed")
    third = index.scan(root, db)
    assert third["hashed"] == 1 and third["reused"] == 0
    assert index.list_media(db)[0]["size"] == 7


def test_symlinks_outside_root_are_never_read(tmp_path):
    root, db = tmp_path / "films", tmp_path / "media.db"
    root.mkdir()
    private = tmp_path / "private.mkv"
    private.write_bytes(b"secret")
    (root / "link.mkv").symlink_to(private)
    (root / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    out = index.scan(root, db)
    assert out["skipped_symlinks"] == 2
    assert out["files_seen"] == 0 and index.list_media(db) == []


def test_complete_scans_prune_missing_but_limited_scans_do_not(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    for name in ("one.mkv", "two.mp4"):
        (root / name).write_bytes(name.encode())
    assert index.scan(root, db)["hashed"] == 2
    (root / "two.mp4").unlink()
    limited = index.scan(root, db, max_dirs=1, max_depth=0)
    # This one-level scan is complete because there were no subdirectories.
    assert limited["removed"] == 1
    (root / "two.mp4").write_bytes(b"again")
    assert index.scan(root, db)["hashed"] == 1
    (root / "two.mp4").unlink()
    (root / "three.avi").write_bytes(b"third")
    truncated = index.scan(root, db, max_files=1)
    assert not truncated["complete"] and truncated["removed"] == 0
    assert any(row["path"].endswith("two.mp4") for row in index.list_media(db))
    done = index.scan(root, db)
    assert done["removed"] == 1


def test_errors_preserve_existing_records_without_losing_progress(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    movie = root / "x.mp4"
    movie.write_bytes(b"original")
    assert index.scan(root, db)["complete"]
    original_hash = index.list_media(db)[0]["sha256"]
    movie.write_bytes(b"new-content")
    with mock.patch.object(index, "_fingerprint", side_effect=index.IndexError("changed during read")):
        scan = index.scan(root, db)
    assert scan["errors"] == 1 and not scan["complete"]
    assert index.list_media(db)[0]["sha256"] == original_hash


def test_unreadable_directory_never_prunes_cached_data(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    movie = root / "x.mp4"
    movie.write_bytes(b"contents")
    index.scan(root, db)
    real_scandir = index.os.scandir
    def deny(path):
        if Path(path) == root:
            raise PermissionError("denied")
        return real_scandir(path)
    with mock.patch.object(index.os, "scandir", side_effect=deny):
        state = index.scan(root, db)
    assert state["errors"] == 1 and not state["complete"]
    assert len(index.list_media(db)) == 1


def test_explicit_probe_is_offline_bounded_and_cached(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    (root / "one.mkv").write_bytes(b"one")
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        kwargs["stdout"].write(b'{"format":{"duration":"12"},"streams":[]}')
        return mock.Mock(returncode=0)
    with mock.patch.object(index.shutil, "which", return_value="/usr/bin/ffprobe"), mock.patch.object(index.subprocess, "run", side_effect=fake_run):
        first = index.scan(root, db, probe=True)
        second = index.scan(root, db, probe=True)
    assert first["probed"] == 1 and second["probed"] == 0
    assert len(calls) == 1
    args, opts = calls[0]
    assert "-protocol_whitelist" in args and "file,pipe" in args
    assert opts["timeout"] == 12 and opts["stdin"] == index.subprocess.DEVNULL
    assert index.list_media(db)[0]["metadata"]["format"]["duration"] == "12"


def test_failed_probe_keeps_content_hash_but_retries(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    (root / "a.mp4").write_bytes(b"contents")
    with mock.patch.object(index.shutil, "which", return_value=None):
        first = index.scan(root, db, probe=True)
    assert first["hashed"] == 1 and first["probed"] == 0
    assert index.list_media(db)[0]["metadata"]["probe_error"]
    with mock.patch.object(index.shutil, "which", return_value=None):
        second = index.scan(root, db, probe=True)
    assert second["hashed"] == 0 and second["reused"] == 1


def test_list_is_bounded_and_invalid_limits_fail(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    for i in range(3):
        (root / f"{i}.mkv").write_bytes(str(i).encode())
    index.scan(root, db)
    assert len(index.list_media(db, limit=2)) == 2
    assert len(index.list_media(db, limit=2, offset=2)) == 1
    with pytest.raises(index.IndexError):
        index.list_media(db, limit=1001)
    with pytest.raises(index.IndexError):
        index.scan(root, db, max_files=0)


def test_cli_can_run_without_loading_gtk(tmp_path, capsys):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    root.mkdir()
    (root / "sample.mkv").write_bytes(b"x")
    assert index.main(["--db", str(db), "scan", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["hashed"] == 1
    assert index.main(["--db", str(db), "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["path"].endswith("sample.mkv")
    assert "gi" not in __import__("sys").modules


def test_overlapping_explicit_roots_do_not_evict_one_another(tmp_path):
    top, db = tmp_path / "top", tmp_path / "idx.sqlite3"
    inner = top / "inner"
    inner.mkdir(parents=True)
    (inner / "shared.mkv").write_bytes(b"shared")
    assert index.scan(top, db)["hashed"] == 1
    assert index.scan(inner, db)["hashed"] == 1
    assert len(index.list_media(db)) == 2
    assert index.scan(top, db)["reused"] == 1
    assert len(index.list_media(db)) == 2


def test_traversal_depth_limit_is_not_a_complete_scan(tmp_path):
    root, db = tmp_path / "media", tmp_path / "idx.sqlite3"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (nested / "video.mp4").write_bytes(b"x")
    index.scan(root, db)
    capped = index.scan(root, db, max_depth=0)
    assert not capped["complete"] and capped["removed"] == 0
    assert len(index.list_media(db)) == 1


def test_installed_cli_dispatch_remains_headless_in_test_context(monkeypatch):
    import os
    import sys
    import cli
    with mock.patch.dict(sys.modules, {"library_index": index}):
        with mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": "1"}):
            with mock.patch.object(sys, "argv", ["smoothcast", "--library-index", "list"]):
                with mock.patch.object(index, "main", return_value=7) as handler:
                    assert cli.main() == 7
                    handler.assert_called_once_with(["list"])


def test_index_module_is_in_wheel_build_configuration():
    config = (MODULE.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"library_index"' in config


def test_same_size_and_reset_mtime_still_rehashes(tmp_path):
    root, db = tmp_path / "media", tmp_path / "index.sqlite3"
    root.mkdir()
    media = root / "video.mkv"
    media.write_bytes(b"aaaa")
    index.scan(root, db)
    previous = media.stat()
    media.write_bytes(b"bbbb")
    import os
    os.utime(media, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert media.stat().st_ctime_ns != previous.st_ctime_ns
    result = index.scan(root, db)
    assert result["hashed"] == 1 and result["reused"] == 0
    assert index.list_media(db)[0]["sha256"] == hashlib.sha256(b"bbbb").hexdigest()
