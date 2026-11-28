"""Offline source generation staging never mutates a running installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import managed_generations as mg

COMMIT = "a" * 40


def sample(tmp_path):
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    data = b"import sys\nprint('v1')\n"
    (source / "src" / "entry.py").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    root = tmp_path / "installed"
    root.mkdir(mode=0o700)
    (root / "current").write_text("old-verified-generation")
    (root / "previous").write_text("previous-verified-generation")
    return source, root, {"src/entry.py": {"size": len(data), "sha256": digest}}


def test_stages_immutable_generation_without_touching_active_install(tmp_path):
    source, root, files = sample(tmp_path)
    released = mg.stage_local_snapshot(root, source, COMMIT, files)
    assert released == root / "releases" / COMMIT
    assert (released / "src/entry.py").read_bytes() == (
        source / "src/entry.py"
    ).read_bytes()
    marker = (COMMIT + "\n").encode()
    saved = json.loads((released / "stage-manifest.json").read_text())
    assert saved == {"commit": COMMIT, "files": {
        **files,
        "src/.smoothcast-build": {"size": len(marker),
                                  "sha256": hashlib.sha256(marker).hexdigest()}}}
    assert (released / "src" / ".smoothcast-build").read_bytes() == marker
    assert (root / "current").read_text() == "old-verified-generation"
    assert (root / "previous").read_text() == "previous-verified-generation"
    assert not list((root / "releases").glob(".staging-*"))
    with pytest.raises(mg.StageError, match="already exists"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"


def test_rejects_candidate_supplied_build_marker(tmp_path):
    source, root, files = sample(tmp_path)
    data = b"forged\n"
    (source / "src" / ".smoothcast-build").write_bytes(data)
    files = {**files, "src/.smoothcast-build": {
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
    with pytest.raises(mg.StageError, match="reserved build marker"):
        mg.stage_local_snapshot(root, source, COMMIT, files)


@pytest.mark.parametrize("name", [
    "../escape", "/absolute", "src/../escape", "src//bad", "src/./bad",
    "C:/windows", "src\\bad", "stage-manifest.json/../overwrite",
])
def test_rejects_unsafe_manifest_paths_before_creating_release(tmp_path, name):
    source, root, files = sample(tmp_path)
    files[name] = next(iter(files.values()))
    with pytest.raises(mg.StageError):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert not (root / "releases" / COMMIT).exists()
    assert (root / "current").read_text() == "old-verified-generation"


def test_rejects_case_collisions_and_invalid_digest(tmp_path):
    source, root, files = sample(tmp_path)
    files["SRC/ENTRY.py"] = next(iter(files.values()))
    with pytest.raises(mg.StageError, match="case-colliding"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    files.pop("SRC/ENTRY.py")
    files["src/entry.py"]["sha256"] = "0" * 64
    with pytest.raises(mg.StageError, match="SHA-256"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert not list((root / "releases").glob(".staging-*"))
    assert (root / "current").read_text() == "old-verified-generation"


def test_staging_refuses_symlink_without_copying_private_target(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    source, root, files = sample(tmp_path)
    victim = tmp_path / "private"
    victim.write_text("secret")
    (source / "src/entry.py").unlink()
    try:
        (source / "src/entry.py").symlink_to(victim)
    except OSError:
        pytest.skip("symlink creation is not permitted on this runner")
    with pytest.raises(mg.StageError, match="symbolic-link"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert victim.read_text() == "secret"
    assert not (root / "releases" / COMMIT).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_staging_refuses_windows_reparse_directory(tmp_path):
    source, root, files = sample(tmp_path)
    source_dir = source / "src"
    shutil.rmtree(source_dir)
    private = tmp_path / "private-source"
    private.mkdir()
    victim = private / "entry.py"
    victim.write_text("private content")
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(source_dir), str(private)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        pytest.skip("Windows junction creation is unavailable")
    try:
        with pytest.raises(mg.StageError, match="symbolic-link component"):
            mg.stage_local_snapshot(root, source, COMMIT, files)
        assert victim.read_text() == "private content"
        assert not (root / "releases" / COMMIT).exists()
    finally:
        source_dir.rmdir()


def test_oversize_and_invalid_commit_are_rejected(tmp_path):
    source, root, files = sample(tmp_path)
    with pytest.raises(mg.StageError, match="immutable"):
        mg.stage_local_snapshot(root, source, "develop", files)
    files["src/entry.py"]["size"] = mg.MAX_FILE_BYTES + 1
    with pytest.raises(mg.StageError, match="file size"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"


def test_fails_closed_on_unprivileged_install_directory(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX directory mode is required")
    source, root, files = sample(tmp_path)
    root.chmod(0o755)
    with pytest.raises(mg.StageError, match="owned and private"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert not (root / "releases" / COMMIT).exists()


def test_rejects_directory_case_collisions_and_reserved_manifest(tmp_path):
    source, root, files = sample(tmp_path)
    files["SRC/another.py"] = next(iter(files.values()))
    with pytest.raises(mg.StageError, match="Directory names collide"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    files.pop("SRC/another.py")
    files["stage-manifest.json"] = next(iter(files.values()))
    with pytest.raises(mg.StageError, match="reserved"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"


def test_disk_space_refusal_does_not_touch_live_generation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source, root, files = sample(tmp_path)
    monkeypatch.setattr(mg.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    with pytest.raises(mg.StageError, match="Insufficient free space"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"
    assert not list((root / "releases").glob(".staging-*"))


def test_write_sync_failure_cleans_private_staging(tmp_path, monkeypatch):
    source, root, files = sample(tmp_path)

    def fail_sync(_fd):
        raise OSError("disk I/O failed")

    monkeypatch.setattr(mg.os, "fsync", fail_sync)
    with pytest.raises(mg.StageError, match="Cannot stage"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"
    assert not (root / "releases" / COMMIT).exists()
    assert not list((root / "releases").glob(".staging-*"))


def test_failed_publication_directory_sync_removes_new_generation(tmp_path, monkeypatch):
    source, root, files = sample(tmp_path)
    original = mg._sync_dir

    def fail_publication(path):
        if path == root / "releases":
            raise OSError("parent directory fsync failed")
        return original(path)

    monkeypatch.setattr(mg, "_sync_dir", fail_publication)
    with pytest.raises(OSError, match="parent directory"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"
    assert not (root / "releases" / COMMIT).exists()
    assert not list((root / "releases").glob(".staging-*"))

def test_build_marker_fsync_failure_prevents_generation_publication(tmp_path, monkeypatch):
    source, root, files = sample(tmp_path)
    original = mg.os.fsync
    marker_synced = []

    def fail_marker(fd):
        # Identify the marker by its exact bytes, without relying on /proc.
        info = os.fstat(fd)
        if info.st_size == len(COMMIT) + 1:
            marker_synced.append(True)
            raise OSError("build marker fsync failed")
        original(fd)

    monkeypatch.setattr(mg.os, "fsync", fail_marker)
    with pytest.raises(OSError, match="build marker fsync failed"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert marker_synced
    assert not (root / "releases" / COMMIT).exists()
    assert not list((root / "releases").glob(".staging-*"))
    assert (root / "current").read_text() == "old-verified-generation"


def test_fifo_source_is_rejected_without_waiting_for_a_writer(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"):
        pytest.skip("POSIX named pipes are unavailable")
    source, root, files = sample(tmp_path)
    fifo = source / "src/entry.py"
    fifo.unlink()
    os.mkfifo(fifo)
    original = mg.os.open

    def guarded_open(path, flags, *args, **kwargs):
        if Path(path) == fifo:
            # Fail immediately on a regression instead of hanging pytest.
            assert flags & os.O_NONBLOCK
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(mg.os, "open", guarded_open)
    with pytest.raises(mg.StageError, match="ordinary private file"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"
    assert not (root / "releases" / COMMIT).exists()
    assert not list((root / "releases").glob(".staging-*"))

@pytest.mark.parametrize("name", [
    "src/CON.txt", "src/aux", "src/COM1.py", "src/LPT².log",
    "src/file.", "src/dir /file.py", "src/bad?.py", "src/bad|name",
    "src/bad\x01name", "STAGE-MANIFEST.JSON", "stage-manifest.json/child",
    "src/.SMOOTHCAST-BUILD", "src/.smoothcast-build/child",
])
def test_nonportable_or_reserved_paths_rejected_before_staging(tmp_path, monkeypatch, name):
    source, root, files = sample(tmp_path)
    files[name] = next(iter(files.values()))

    def no_io(_path):
        pytest.fail("invalid manifest reached staging directory creation")

    monkeypatch.setattr(mg, "_directory", no_io)
    with pytest.raises(mg.StageError):
        mg.stage_local_snapshot(root, source, COMMIT, files)


@pytest.mark.parametrize("names", [
    ("folder", "folder/file.py"), ("folder/file.py", "folder"),
    ("folder", "FOLDER/file.py"),
])
def test_manifest_refuses_file_directory_collisions_in_either_order(names):
    metadata = {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    with pytest.raises(mg.StageError, match="collides with a directory"):
        mg._manifest({name: metadata for name in names})


def test_manifest_cannot_replace_build_marker_parent(tmp_path, monkeypatch):
    source, root, files = sample(tmp_path)
    metadata = next(iter(files.values()))
    monkeypatch.setattr(mg, "_directory", lambda _path: pytest.fail("unexpected staging I/O"))
    for name in ("src", "SRC/entry.py"):
        with pytest.raises(mg.StageError, match="reserved build marker"):
            mg.stage_local_snapshot(root, source, COMMIT, {name: metadata})


def test_marker_records_the_commit_time_so_the_installed_app_can_show_it(tmp_path):
    source, root, files = sample(tmp_path)
    released = mg.stage_local_snapshot(root, source, COMMIT, files, commit_date="2026-11-28 0157")
    marker = (released / "src" / ".smoothcast-build").read_text()
    assert marker == COMMIT + "\n2026-11-28 0157\n"
    saved = json.loads((released / "stage-manifest.json").read_text())
    body = marker.encode()
    assert saved["files"]["src/.smoothcast-build"] == {
        "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import commit_identity
    assert commit_identity.read_checkout_commit_date(released, COMMIT) == "2026-11-28 0157"
    label = commit_identity.display_label("v2.3.1", COMMIT, "2026-11-28 0157")
    assert label == f"v2.3.1 - 2026-11-28 0157 - {commit_identity.codename(COMMIT)}"


@pytest.mark.parametrize("bad", ["2026-11-28", "yesterday", "2026-11-28 01:57", "2026-11-28 0157\nx", 5])
def test_malformed_commit_date_is_dropped_never_invented(tmp_path, bad):
    source, root, files = sample(tmp_path)
    released = mg.stage_local_snapshot(root, source, COMMIT, files, commit_date=bad)
    assert (released / "src" / ".smoothcast-build").read_text() == COMMIT + "\n"
