"""Archive PyInstaller's onedir artefact, preserving Unix symlinks/modes."""
from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def archive(dist: Path) -> Path:
    system = platform.system().lower()
    if system == "windows":
        package = dist / "SmoothCast"
        if not package.is_dir():
            raise FileNotFoundError(package)
        destination = Path(shutil.make_archive(str(dist / "smoothcast-windows"), "zip", root_dir=dist, base_dir="SmoothCast"))
    else:
        package = dist / "SmoothCast.app" if system == "darwin" else dist / "SmoothCast"
        if not package.is_dir():
            raise FileNotFoundError(package)
        destination = dist / f"smoothcast-{system}.tar.gz"
        with tarfile.open(destination, "w:gz") as handle:
            handle.add(package, arcname=package.name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8",
    )
    return destination


if __name__ == "__main__":
    print(archive(Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "dist"))
