"""Manifest and static checks for the Windows payload (#528). Builds tiny PE fixtures; runs anywhere."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))
import windows_payload as wp  # noqa: E402

VERSION = "2.0.30"


def make_pe(*, machine=0x8664, subsystem=2, imports=("KERNEL32.dll",)) -> bytes:
    """A minimal PE32+ image with an import table; just what the checker reads."""
    names = b"".join(name.encode() + b"\0" for name in imports)
    descriptors = 20 * (len(imports) + 1)
    section = bytearray(descriptors + len(names))
    cursor = descriptors
    for index, name in enumerate(imports):
        struct.pack_into("<I", section, 20 * index + 12, 0x1000 + cursor)
        cursor += len(name) + 1
    section[descriptors:] = names
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<H", optional, 68, subsystem)
    struct.pack_into("<I", optional, 108, 16)
    struct.pack_into("<I", optional, 112 + 8, 0x1000)
    coff = struct.pack("<HHIIIHH", machine, 1, 0, 0, 0, 240, 0x22)
    header = bytearray(0x40)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    table = struct.pack("<8sIIIIIIHHI", b".idata", len(section), 0x1000, len(section), 0x400, 0, 0, 0, 0, 0)
    return bytes(header) + b"PE\0\0" + coff + bytes(optional) + table + b"\0" * (0x400 - 0x40 - 4 - 20 - 240 - 40) + bytes(section)


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist ünï" / "SmoothCast"
    (root / "_internal").mkdir(parents=True)
    (root / wp.GUI_EXE).write_bytes(make_pe(subsystem=2, imports=("KERNEL32.dll", "libgtk-4-1.dll")))
    (root / wp.CLI_EXE).write_bytes(make_pe(subsystem=3, imports=("api-ms-win-crt-runtime-l1-1-0.dll",)))
    (root / "_internal" / "libgtk-4-1.dll").write_bytes(make_pe(subsystem=2, imports=("USER32.dll",)))
    (root / "_internal" / "base.txt").write_text("hello", encoding="utf-8")
    wp.write_manifest(root, VERSION)
    return root


def test_a_sound_payload_has_no_problems(dist):
    assert wp.verify(dist, VERSION) == []


def test_the_manifest_is_deterministic_and_portable(dist):
    first = (dist / wp.MANIFEST).read_bytes()
    wp.write_manifest(dist, VERSION)
    assert (dist / wp.MANIFEST).read_bytes() == first
    data = json.loads(first)
    assert data["platform"] == "windows-x64" and data["version"] == VERSION and data["schema"] == 1
    paths = [entry["path"] for entry in data["files"]]
    assert paths == sorted(paths) and wp.MANIFEST not in paths
    assert all("\\" not in p and not p.startswith("/") and ":" not in p for p in paths)
    assert b"\r" not in first and str(dist.parent).encode() not in first


def test_a_changed_file_names_the_file(dist):
    (dist / "_internal" / "base.txt").write_text("hellO", encoding="utf-8")
    assert any("_internal/base.txt: changed since the manifest" in p for p in wp.verify(dist, VERSION))


def test_a_deleted_dll_and_an_unlisted_file_are_reported(dist):
    (dist / "_internal" / "libgtk-4-1.dll").unlink()
    (dist / "extra.bin").write_bytes(b"x")
    problems = wp.verify(dist, VERSION)
    assert any("_internal/libgtk-4-1.dll: listed in the manifest but missing" in p for p in problems)
    assert any("extra.bin: present but not in the manifest" in p for p in problems)
    # The executable that needed that DLL now reports it as unresolved too.
    assert any(p.startswith("SmoothCast.exe: needs libgtk-4-1.dll") for p in problems)


def test_a_non_x64_binary_is_rejected(dist):
    (dist / "_internal" / "libgtk-4-1.dll").write_bytes(make_pe(machine=0x14C))
    wp.write_manifest(dist, VERSION)
    assert any("libgtk-4-1.dll: machine type 0x014c is not x64" in p for p in wp.verify(dist, VERSION))


def test_unresolved_non_system_imports_are_named(dist):
    (dist / wp.CLI_EXE).write_bytes(make_pe(subsystem=3, imports=("KERNEL32.dll", "libglib-2.0-0.dll")))
    wp.write_manifest(dist, VERSION)
    assert any("SmoothCastCLI.exe: needs libglib-2.0-0.dll" in p for p in wp.verify(dist, VERSION))


def test_import_names_match_ignoring_case(dist):
    (dist / wp.CLI_EXE).write_bytes(make_pe(subsystem=3, imports=("LIBGTK-4-1.DLL",)))
    wp.write_manifest(dist, VERSION)
    assert wp.verify(dist, VERSION) == []


def test_subsystems_are_checked_by_pe_metadata_not_by_running(dist):
    (dist / wp.GUI_EXE).write_bytes(make_pe(subsystem=3, imports=("libgtk-4-1.dll",)))
    (dist / wp.CLI_EXE).write_bytes(make_pe(subsystem=2, imports=("KERNEL32.dll",)))
    wp.write_manifest(dist, VERSION)
    problems = wp.verify(dist, VERSION)
    assert "SmoothCast.exe: must be a windowed (GUI) program" in problems
    assert "SmoothCastCLI.exe: must be a console program" in problems


def test_missing_required_executable_and_wrong_version(dist):
    (dist / wp.CLI_EXE).unlink()
    wp.write_manifest(dist, VERSION)
    problems = wp.verify(dist, "9.9.9")
    assert "SmoothCastCLI.exe: required executable is missing" in problems
    assert any("version 2.0.30 does not match 9.9.9" in p for p in problems)


def test_build_machine_paths_in_launch_files_are_rejected(dist):
    (dist / "_internal" / "pyvenv.cfg").write_text("home = C:\\msys64\\ucrt64\\bin\n", encoding="utf-8")
    wp.write_manifest(dist, VERSION)
    assert any(p.startswith("_internal/pyvenv.cfg: refers to the build machine") for p in wp.verify(dist, VERSION))


def test_case_duplicates_and_links_cannot_be_described(dist, tmp_path):
    (dist / "_internal" / "Base.TXT").write_text("again", encoding="utf-8")
    if not (dist / "_internal" / "base.txt").samefile(dist / "_internal" / "Base.TXT"):
        with pytest.raises(wp.PayloadError, match="duplicates"):
            wp.payload_files(dist)
    (dist / "_internal" / "Base.TXT").unlink(missing_ok=True)
    try:
        os.symlink(tmp_path, dist / "_internal" / "escape")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(wp.PayloadError, match="links are not allowed"):
        wp.payload_files(dist)


def test_corrupt_inputs_fail_closed(dist):
    (dist / wp.MANIFEST).write_text("{not json", encoding="utf-8")
    assert wp.verify(dist, VERSION)[0].startswith("payload-manifest.json is unreadable")
    (dist / wp.MANIFEST).unlink()
    assert wp.verify(dist, VERSION)[0].startswith("payload-manifest.json is missing")
    (dist / "_internal" / "libgtk-4-1.dll").write_bytes(b"MZ junk")
    wp.write_manifest(dist, VERSION)
    assert any("libgtk-4-1.dll: unreadable PE file" in p for p in wp.verify(dist, VERSION))


def test_cli_returns_status_codes(dist, tmp_path, capsys):
    import importlib

    import verify_windows_payload as cli
    importlib.reload(cli)
    assert cli.main(["--dist", str(tmp_path / "nowhere")]) == 2
    assert cli.main(["--dist", str(dist)]) == 1          # manifest has a stale version
    assert cli.main(["--dist", str(dist), "--write-manifest"]) == 0
    (dist / "_internal" / "base.txt").write_text("tampered", encoding="utf-8")
    assert cli.main(["--dist", str(dist)]) == 1
    assert "PROBLEM: _internal/base.txt: changed" in capsys.readouterr().err
