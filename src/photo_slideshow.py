"""Family photo slideshow (#381). Pure: JPEG EXIF handling, slideshow plan, ephemeral store.

``strip_metadata`` removes every APP1(EXIF/XMP)/APP13 segment from a JPEG so GPS never reaches disk;
``orientation`` reads the EXIF tag first so the renderer can rotate (``ORIENT_FILTER`` = ffmpeg filter per
value 1..8). ``plan`` clamps seconds (3-15), caps 300, shuffles deterministically. ``Ephemeral`` tracks
uploaded files and deletes them on end and on startup unless kept.
"""
from __future__ import annotations

import os
import random
import shutil
import struct
from pathlib import Path

MAX_PHOTOS, MIN_S, MAX_S, DEFAULT_S = 300, 3, 15, 6
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
ORIENT_FILTER = {1: "", 2: "hflip", 3: "hflip,vflip", 4: "vflip", 5: "transpose=0", 6: "transpose=1", 7: "transpose=3", 8: "transpose=2"}
PRIVACY_NOTE = "Photos are removed from this computer when the slideshow ends."


def _segments(data: bytes):
    """Yield (marker, start, end) of JPEG segments before the scan data."""
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            yield m, i, i + 2
            i += 2
            continue
        if m == 0xDA:                                   # start of scan: the rest is image data
            return
        n = struct.unpack(">H", data[i + 2:i + 4])[0]
        if n < 2 or i + 2 + n > len(data):
            return
        yield m, i, i + 2 + n
        i += 2 + n


def is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def orientation(data: bytes) -> int:
    """EXIF orientation 1..8 (1 when absent or unreadable)."""
    if not is_jpeg(data):
        return 1
    for m, s, e in _segments(data):
        seg = data[s + 4:e]
        if m == 0xE1 and seg[:6] == b"Exif\x00\x00" and len(seg) >= 14:
            t = seg[6:]
            end = "<" if t[:2] == b"II" else ">" if t[:2] == b"MM" else None
            if not end:
                return 1
            try:
                off = struct.unpack(end + "I", t[4:8])[0]
                n = struct.unpack(end + "H", t[off:off + 2])[0]
                for k in range(min(n, 64)):
                    ent = t[off + 2 + 12 * k: off + 14 + 12 * k]
                    if len(ent) == 12 and struct.unpack(end + "H", ent[:2])[0] == 0x0112:
                        v = struct.unpack(end + "H", ent[8:10])[0]
                        return v if 1 <= v <= 8 else 1
            except struct.error:
                return 1
    return 1


def strip_metadata(data: bytes) -> bytes:
    """Drop EXIF/XMP/IPTC (APP1, APP13) and comments from a JPEG; other formats pass through unchanged."""
    if not is_jpeg(data):
        return data
    out, last = bytearray(data[:2]), 2
    for m, s, e in _segments(data):
        if s < 2:
            continue
        if m in (0xE1, 0xED, 0xFE):                     # APP1 (EXIF, XMP), APP13 (IPTC), COM
            out += data[last:s]
            last = e
    out += data[last:]
    return bytes(out)


def contains_gps(data: bytes) -> bool:
    return is_jpeg(data) and any(m == 0xE1 and b"GPS" in data[s:e] or (m == 0xE1 and b"\x25\x88" in data[s + 10:e] and b"Exif" in data[s:s + 10]) for m, s, e in _segments(data))


def accept(name: str) -> bool:
    return Path(name or "").suffix.lower() in EXTS


def plan(names: list[str], seconds: float = DEFAULT_S, shuffle: bool = False, seed: int = 0, decodable_heic: bool = False) -> dict:
    ok = [n for n in names if accept(n) and (decodable_heic or Path(n).suffix.lower() not in (".heic", ".heif"))]
    skipped = len(names) - len(ok)
    if shuffle:
        ok = random.Random(seed).sample(ok, len(ok))
    over = max(0, len(ok) - MAX_PHOTOS)
    ok = ok[:MAX_PHOTOS]
    s = max(MIN_S, min(MAX_S, float(seconds))) if seconds == seconds else DEFAULT_S
    return {"items": ok, "seconds": s, "skipped": skipped + over, "total_s": s * len(ok)}


def concat_list(paths: list[str], seconds: float) -> str:
    """ffmpeg concat-demuxer listing (last file repeated so its duration is honoured)."""
    esc = lambda p: p.replace("'", "'\\''")
    lines = [f"file '{esc(p)}'\nduration {seconds:g}" for p in paths]
    if paths:
        lines.append(f"file '{esc(paths[-1])}'")
    return "\n".join(lines) + "\n"


class Ephemeral:
    """Per-slideshow temp folders; removed at end/startup unless the uploader kept them."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, sid: str) -> Path:
        return self.root / "".join(c for c in sid if c.isalnum() or c in "-_")[:64]

    def save(self, sid: str, name: str, data: bytes) -> Path | None:
        if not accept(name):
            return None
        d = self._dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        p = d / (f"{len(list(d.iterdir())):04d}" + Path(name).suffix.lower())
        p.write_bytes(strip_metadata(data))             # metadata never reaches disk
        return p

    def keep(self, sid: str) -> None:
        (self._dir(sid) / ".keep").write_text("1")

    def end(self, sid: str) -> bool:
        d = self._dir(sid)
        if not d.is_dir() or (d / ".keep").exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    def cleanup_startup(self, live: set[str] = frozenset()) -> int:
        n = 0
        if self.root.is_dir():
            for d in self.root.iterdir():
                if d.is_dir() and d.name not in live and not (d / ".keep").exists():
                    shutil.rmtree(d, ignore_errors=True)
                    n += 1
        return n
