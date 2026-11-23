"""Build an unsigned macOS disk image from the verified PyInstaller .app.

Signing/notarisation are separate release gates. Never launch the app or
contact a media receiver during packaging.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def build(dist: Path, *, system: str | None = None) -> Path:
    """Make a compressed DMG and checksum; publish only completed output."""
    if (system or platform.system()) != "Darwin":
        raise RuntimeError("macOS DMG packaging requires hdiutil on macOS")
    dist = Path(dist).resolve()
    app = dist / "SmoothCast.app"
    if not app.is_dir() or not (app / "Contents" / "Info.plist").is_file():
        raise FileNotFoundError(f"missing macOS application bundle: {app}")
    destination = dist / "smoothcast-macos.dmg"
    checksum = dist / "smoothcast-macos.dmg.sha256"
    if destination.exists() or checksum.exists():
        raise FileExistsError("macOS DMG output exists; remove it explicitly before rebuilding")
    temporary = dist / ".smoothcast-macos.partial.dmg"
    if temporary.exists():
        raise FileExistsError(f"stale partial disk image: {temporary}")
    try:
        subprocess.run(
            ["hdiutil", "create", "-srcfolder", str(app), "-volname", "SmoothCast",
             "-format", "UDZO", "-fs", "HFS+", str(temporary)],
            check=True, timeout=300, capture_output=True, text=True,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("hdiutil returned success without a nonempty disk image")
        digest = hashlib.sha256()
        with temporary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        os.replace(temporary, destination)
        try:
            checksum.write_text(f"{digest.hexdigest()}  {destination.name}\n", encoding="ascii")
        except OSError:
            destination.unlink(missing_ok=True)
            raise
        return destination
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        print(build(Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "dist"))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"macOS DMG build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
