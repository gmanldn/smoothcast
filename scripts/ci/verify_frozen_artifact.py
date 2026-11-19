"""Run bounded, GUI-free smoke checks against the actual PyInstaller artefact."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "src" / "smoothcast_assets" / "local.cast-control.png"


def console_executable(dist: Path) -> Path:
    extension = ".exe" if sys.platform == "win32" else ""
    locations = (
        dist / "SmoothCast" / f"SmoothCastCLI{extension}",
        dist / "SmoothCast.app" / "Contents" / "MacOS" / "SmoothCastCLI",
    )
    for path in locations:
        if path.is_file():
            return path
    raise FileNotFoundError("SmoothCastCLI frozen artefact missing: " + ", ".join(map(str, locations)))


def check(executable: Path, arguments: list[str], expected: str) -> None:
    result = subprocess.run(
        [str(executable), *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, cwd=executable.parent,
    )
    if result.returncode != 0 or expected not in result.stdout:
        raise RuntimeError(
            f"{executable.name} {arguments!r} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout)[-1800:]}"
        )


def verify(dist: Path) -> None:
    executable = console_executable(dist)
    # Do not launch the normal GUI or the HLS server. All probes exit promptly.
    check(executable, ["--version"], "SmoothCast v")
    check(executable, ["--_smoothcast-catt", "--help"], "Usage:")
    expected = hashlib.sha256(ICON.read_bytes()).hexdigest()
    check(executable, ["--_smoothcast-package-check"], expected)


if __name__ == "__main__":
    verify(Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "dist")
