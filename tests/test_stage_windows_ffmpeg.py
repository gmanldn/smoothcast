import hashlib
import io
import struct
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "packaging"))
import stage_windows_ffmpeg as s


def pe(machine=0x8664):
    b = bytearray(0x100); b[:2] = b"MZ"; struct.pack_into("<I", b, 0x3C, 0x80); b[0x80:0x84] = b"PE\0\0"; struct.pack_into("<H", b, 0x84, machine); return bytes(b)


def make_zip(files, extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in {**files, **dict(extra)}.items(): z.writestr(name, data)
    return buf.getvalue()


GOOD = {"bin/ffmpeg.exe": pe(), "bin/ffprobe.exe": pe(), "bin/ffplay.exe": pe(), "bin/avcodec-60.dll": b"dll",
        "THIRD_PARTY_NOTICES.txt": b"n", "LICENSE.txt": b"l", "PROVENANCE.txt": b"p", "random/readme.md": b"skip me"}


def lock_for(blob, **kw):
    return {"version": "6.1", "url": "https://example.invalid/ff.zip", "filename": "ff.zip", "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
            "license": "GPL-3.0", "configure": "--enable-gpl", "tools": list(s.TOOLS), "dlls": ["avcodec-60.dll"], **kw}


def test_good_archive_stages_only_allowlisted_files_atomically(tmp_path):
    blob = make_zip(GOOD); dest = tmp_path / "ffmpeg"
    names = s.stage(blob, lock_for(blob), dest)
    assert names == ["LICENSE.txt", "PROVENANCE.txt", "THIRD_PARTY_NOTICES.txt", "avcodec-60.dll", "ffmpeg.exe", "ffplay.exe", "ffprobe.exe"]
    assert sorted(p.name for p in dest.iterdir()) == names and not (dest / "readme.md").exists() and [p for p in tmp_path.iterdir() if p.name.startswith(".stage")] == []


@pytest.mark.parametrize("mutate,msg", [
    (lambda b: b + b"x", "size"), (lambda b: b[:-5], "size"), (lambda b: bytes([b[0] ^ 1]) + b[1:], "SHA-256")])
def test_tampered_or_truncated_archive_fails_before_extract(tmp_path, mutate, msg):
    blob = make_zip(GOOD); lock = lock_for(blob); dest = tmp_path / "ffmpeg"
    with pytest.raises(s.StageError, match=msg): s.stage(mutate(blob), lock, dest)
    assert not dest.exists() and list(tmp_path.iterdir()) == []


def test_missing_nonx64_traversal_and_duplicates_fail_with_no_partial_dest(tmp_path):
    cases = {
        "missing tool": ({k: v for k, v in GOOD.items() if "ffplay" not in k}, "missing tool: ffplay.exe"),
        "arm64": ({**GOOD, "bin/ffmpeg.exe": pe(0xAA64)}, "not a Windows x64"),
        "missing dll": ({k: v for k, v in GOOD.items() if "dll" not in k}, "missing declared dll"),
        "missing notice": ({k: v for k, v in GOOD.items() if "LICENSE" not in k}, "missing notice"),
        "traversal": ({**GOOD, "../evil.exe": b"x"}, "unsafe archive member"),
        "absolute": ({**GOOD, "/etc/passwd": b"x"}, "unsafe archive member"),
        "drive": ({**GOOD, "C:\\win\\x.dll": b"x"}, "unsafe archive member"),
        "not pe": ({**GOOD, "bin/ffprobe.exe": b"MZ-not-really"}, "not a Windows x64"),
    }
    for label, (files, msg) in cases.items():
        blob = make_zip(files); dest = tmp_path / label / "ff"; dest.parent.mkdir()
        with pytest.raises(s.StageError, match=msg): s.stage(blob, lock_for(blob), dest)
        assert not dest.exists() and list(dest.parent.iterdir()) == [], label
    dup = make_zip(GOOD, extra={"other/ffmpeg.exe": pe()}); d = tmp_path / "dup"; d.mkdir()
    with pytest.raises(s.StageError, match="duplicate"): s.stage(dup, lock_for(dup), d / "ff")
    junk = b"not a zip"; j = tmp_path / "junk"; j.mkdir()
    with pytest.raises(s.StageError, match="valid zip"): s.stage(junk, lock_for(junk), j / "ff")


def test_lock_validation_rejects_unreviewed_or_malformed_locks():
    blob = make_zip(GOOD); ok = lock_for(blob); assert s.validate_lock(ok) is ok
    for bad in ({"sha256": "ABC"}, {"sha256": "G" * 64}, {"url": "http://x/ff.zip"}, {"filename": "../x.zip"}, {"size": 0}, {"size": True},
                {"tools": ["ffmpeg.exe"]}, {"dlls": ["../x.dll"]}, {"dlls": ["x.exe"]}):
        with pytest.raises(s.StageError): s.validate_lock({**ok, **bad})
    for k in ("sha256", "license", "configure"):
        with pytest.raises(s.StageError, match="missing"): s.validate_lock({a: b for a, b in ok.items() if a != k})
    with pytest.raises(s.StageError): s.validate_lock([])


def test_pe_detection():
    assert s.pe_is_x64(pe()) and not s.pe_is_x64(pe(0x014c)) and not s.pe_is_x64(b"") and not s.pe_is_x64(b"MZ" + b"\0" * 100)
    bad = bytearray(pe()); struct.pack_into("<I", bad, 0x3C, 0xFFFFFF); assert not s.pe_is_x64(bytes(bad))


def test_capability_check_names_the_exact_missing_feature():
    ver = "ffmpeg version 6.1-full_build Copyright (c) 2000-2023"
    enc = " V....D libx264              H.264 \n A....D aac                  AAC"
    fil = " ... subtitles  V->V  render subtitles\n ... loudnorm A->A\n ... aresample A->A"
    assert s.check_capabilities(ver, enc, fil) == []
    assert s.check_capabilities(ver, enc.replace("libx264", "libx265"), fil.replace("subtitles", "ass")) == ["encoder: libx264", "filter: subtitles"]
    assert s.check_capabilities("ffmpeg version 4.4.2", enc, fil) == ["version: 4 < 5"] and s.check_capabilities("garbage", enc, fil) == ["version: unreadable"]
    assert s.parse_major("ffprobe version n7.0.1") == 7
