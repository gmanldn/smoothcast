"""Hostile source archives are rejected before anything reaches a release (#580)."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import managed_archive as ma
import managed_generations as mg

GOOD = {"smoothcast-1/src/a.py": b"print('a')\n", "smoothcast-1/run.sh": b"#!/bin/sh\n"}


def make_tar(path, members, mode="w"):
    """members: iterable of (name, bytes | TarInfo-customiser)."""
    with tarfile.open(path, mode) as tar:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            if callable(payload):
                payload(info)
                tar.addfile(info)
            else:
                info.size = len(payload)
                info.mode = 0o755 if name.endswith(".sh") else 0o644
                tar.addfile(info, io.BytesIO(payload))
    return path


def make_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members:
            if isinstance(payload, zipfile.ZipInfo):
                bundle.writestr(payload, b"x")
            else:
                bundle.writestr(name, payload)
    return path


def symlink(info):
    info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"


def hardlink(info):
    info.type, info.linkname = tarfile.LNKTYPE, "smoothcast-1/src/a.py"


def fifo(info):
    info.type = tarfile.FIFOTYPE


def unpack(tmp_path, archive, **kw):
    return ma.unpack_archive(archive, tmp_path / "scratch", **kw)


@pytest.mark.parametrize("mode,suffix", [("w", ".tar"), ("w:gz", ".tar.gz")])
def test_valid_tar_unpacks_with_exact_manifest_and_modes(tmp_path, mode, suffix):
    archive = make_tar(tmp_path / f"c{suffix}", GOOD.items(), mode)
    entries = unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert set(entries) == {"src/a.py", "run.sh"}
    data = GOOD["smoothcast-1/src/a.py"]
    assert entries["src/a.py"] == {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    scratch = tmp_path / "scratch"
    assert (scratch / "src" / "a.py").read_bytes() == data
    if os.name != "nt":
        assert (scratch / "run.sh").stat().st_mode & 0o777 == 0o700
        assert (scratch / "src" / "a.py").stat().st_mode & 0o777 == 0o600


def test_valid_zip_unpacks_and_feeds_the_stager(tmp_path):
    archive = make_zip(tmp_path / "c.zip", GOOD.items())
    entries = unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert set(entries) == {"src/a.py", "run.sh"}
    if not hasattr(os, "O_NOFOLLOW"):
        return
    root = tmp_path / "installed"
    release = mg.stage_local_snapshot(root, tmp_path / "scratch", "b" * 40, entries)
    assert (release / "src" / "a.py").read_bytes() == GOOD["smoothcast-1/src/a.py"]


@pytest.mark.parametrize("name", [
    "../evil.py", "smoothcast-1/../../evil.py", "/abs/evil.py", "smoothcast-1/a/../../b",
    "smoothcast-1\\evil.py", "smoothcast-1/C:evil", "smoothcast-1/a//b", "smoothcast-1/./a",
    "smoothcast-1/NUL.txt", "smoothcast-1/con", "smoothcast-1/trail.", "smoothcast-1/sp ",
    "smoothcast-1/ctl\x07.py", "smoothcast-1/bidi‮.py", "smoothcast-1/é.py",
    "other/evil.py", "smoothcast-1/stage-manifest.json", "smoothcast-1/" + "x" * 600,
])
@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_unsafe_names_are_rejected_and_scratch_removed(tmp_path, name, kind):
    members = [("smoothcast-1/ok.py", b"ok"), (name, b"x")]
    archive = (make_tar(tmp_path / "c.tar", members) if kind == "tar"
               else make_zip(tmp_path / "c.zip", members))
    with pytest.raises(mg.StageError):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()
    assert not (tmp_path / "evil.py").exists() and not Path("/abs/evil.py").exists()


@pytest.mark.parametrize("customise", [symlink, hardlink, fifo])
def test_links_and_special_tar_members_are_rejected(tmp_path, customise):
    archive = make_tar(tmp_path / "c.tar", [("smoothcast-1/a.py", b"x"),
                                            ("smoothcast-1/link", customise)])
    with pytest.raises(mg.StageError, match="link or special"):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()


def test_zip_symlink_and_encrypted_members_are_rejected(tmp_path):
    info = zipfile.ZipInfo("smoothcast-1/link")
    info.create_system, info.external_attr = 3, 0o120777 << 16
    archive = make_zip(tmp_path / "c.zip", [("smoothcast-1/a.py", b"x"), ("l", info)])
    with pytest.raises(mg.StageError, match="link or special"):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    archive = make_zip(tmp_path / "e.zip", [("smoothcast-1/secret.py", b"x")])
    raw = bytearray(archive.read_bytes())
    raw[raw.index(b"PK\x01\x02") + 8] |= 0x1  # central-directory "encrypted" flag
    archive.write_bytes(bytes(raw))
    with pytest.raises(mg.StageError, match="Encrypted"):
        ma.unpack_archive(archive, tmp_path / "scratch2", strip_prefix="smoothcast-1")


@pytest.mark.parametrize("names", [
    ["smoothcast-1/a.py", "smoothcast-1/a.py"],
    ["smoothcast-1/a.py", "smoothcast-1/A.PY"],
    ["smoothcast-1/Dir/x", "smoothcast-1/dir/y"],
    ["smoothcast-1/a", "smoothcast-1/a/b"],
    ["smoothcast-1/a/b", "smoothcast-1/a"],
])
def test_duplicate_case_and_file_directory_collisions_are_rejected(tmp_path, names):
    archive = make_tar(tmp_path / "c.tar", [(n, b"x") for n in names])
    with pytest.raises(mg.StageError):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()


def test_explicit_and_implied_directories_may_coexist(tmp_path):
    def directory(info):
        info.type = tarfile.DIRTYPE
    archive = make_tar(tmp_path / "c.tar", [("smoothcast-1/", directory),
                                            ("smoothcast-1/src/a.py", b"x"),
                                            ("smoothcast-1/src", directory)])
    assert set(unpack(tmp_path, archive, strip_prefix="smoothcast-1")) == {"src/a.py"}


def test_file_and_byte_budgets_stop_a_bomb_early(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "MAX_FILES", 3)
    archive = make_tar(tmp_path / "c.tar", [(f"smoothcast-1/f{i}", b"x") for i in range(4)])
    with pytest.raises(mg.StageError, match="budget"):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    monkeypatch.setattr(mg, "MAX_FILES", 100)
    monkeypatch.setattr(mg, "MAX_TOTAL_BYTES", 10)
    archive = make_tar(tmp_path / "d.tar", [("smoothcast-1/big", b"x" * 11)])
    with pytest.raises(mg.StageError, match="budget"):
        ma.unpack_archive(archive, tmp_path / "s2", strip_prefix="smoothcast-1")
    monkeypatch.setattr(mg, "MAX_TOTAL_BYTES", 1 << 30)
    monkeypatch.setattr(mg, "MAX_FILE_BYTES", 5)
    with pytest.raises(mg.StageError, match="oversized"):
        ma.unpack_archive(archive, tmp_path / "s3", strip_prefix="smoothcast-1")
    assert not (tmp_path / "s2").exists() and not (tmp_path / "s3").exists()


def test_zip_compression_ratio_bomb_is_rejected_without_inflating(tmp_path, monkeypatch):
    monkeypatch.setattr(ma, "RATIO_FLOOR", 1000)
    archive = make_zip(tmp_path / "bomb.zip", [("smoothcast-1/zeros", b"\0" * 5_000_000)])
    with pytest.raises(mg.StageError, match="ratio"):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()


def test_truncated_corrupt_and_unknown_formats_fail_closed(tmp_path):
    good = make_tar(tmp_path / "c.tar.gz", GOOD.items(), "w:gz")
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(good.read_bytes()[:-20])
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not an archive" * 50)
    for index, bad in enumerate((cut, junk, tmp_path / "missing")):
        with pytest.raises(mg.StageError):
            ma.unpack_archive(bad, tmp_path / f"s{index}", strip_prefix="smoothcast-1")
        assert not (tmp_path / f"s{index}").exists()


def test_tar_declared_size_longer_than_data_is_rejected(tmp_path):
    archive = make_tar(tmp_path / "c.tar", [("smoothcast-1/a.py", b"x" * 1024)])
    archive.write_bytes(archive.read_bytes()[:700])  # cut inside the payload
    with pytest.raises(mg.StageError):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()


def test_existing_scratch_symlinked_archive_and_empty_archive_are_refused(tmp_path):
    archive = make_tar(tmp_path / "c.tar", GOOD.items())
    (tmp_path / "scratch").mkdir()
    with pytest.raises(mg.StageError, match="new"):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert (tmp_path / "scratch").is_dir()  # a pre-existing directory is never deleted
    link = tmp_path / "link.tar"
    link.symlink_to(archive)
    with pytest.raises(mg.StageError, match="ordinary"):
        ma.unpack_archive(link, tmp_path / "s9")
    empty = make_tar(tmp_path / "e.tar", [])
    with pytest.raises(mg.StageError, match="no files"):
        ma.unpack_archive(empty, tmp_path / "s10")
    assert not (tmp_path / "s10").exists()


def test_write_failure_midway_cleans_scratch(tmp_path, monkeypatch):
    archive = make_tar(tmp_path / "c.tar", GOOD.items())
    real = os.fsync
    calls = []

    def flaky(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(fd)

    monkeypatch.setattr(os, "fsync", flaky)
    with pytest.raises(mg.StageError):
        unpack(tmp_path, archive, strip_prefix="smoothcast-1")
    assert not (tmp_path / "scratch").exists()
