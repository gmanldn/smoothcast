"""Offline source generation staging never mutates a running installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
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
    saved = json.loads((released / "stage-manifest.json").read_text())
    assert saved == {"commit": COMMIT, "files": files}
    assert (root / "current").read_text() == "old-verified-generation"
    assert (root / "previous").read_text() == "previous-verified-generation"
    assert not list((root / "releases").glob(".staging-*"))
    with pytest.raises(mg.StageError, match="already exists"):
        mg.stage_local_snapshot(root, source, COMMIT, files)
    assert (root / "current").read_text() == "old-verified-generation"


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
