#!/usr/bin/env python3
"""Build native SmoothCast release artefacts with the checked-in PyInstaller spec.

Builds are deliberately opt-in and never launch GTK, a media player or a TV.
Run using a Python that can import the native GI bindings for this platform.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "SmoothCast.spec"
ICONS = ROOT / "build" / "pyinstaller" / "icons"


class BuildError(RuntimeError):
    pass


def check_environment() -> None:
    if sys.version_info < (3, 10):
        raise BuildError("Python 3.10+ is required")
    try:
        version = importlib.metadata.version("pyinstaller")
        if tuple(int(x) for x in version.split(".")[:2]) < (6, 21):
            raise BuildError("PyInstaller 6.21+ is required")
    except importlib.metadata.PackageNotFoundError as exc:
        raise BuildError("Install the packaging extra: python -m pip install -e '.[packaging]'") from exc
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk, Adw  # noqa: F401
    except (ImportError, ValueError) as exc:
        raise BuildError("Native GTK4/libadwaita/PyGObject unavailable to this Python; use the platform native Python") from exc
    try:
        import catt.cli  # noqa: F401
    except ImportError as exc:
        raise BuildError("catt is missing; install SmoothCast's project dependencies") from exc
    if not SPEC.is_file():
        raise BuildError("Canonical packaging spec is missing")


def make_icons() -> None:
    """Derive reproducible OS icons from the committed SmoothCast PNG."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise BuildError("Pillow is required for Windows/macOS packaging") from exc
    with Image.open(ROOT / "data" / "cast-control.png") as source:
        artwork = source.convert("RGBA")
    ICONS.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        artwork.resize((256, 256), Image.Resampling.LANCZOS).save(
            ICONS / "SmoothCast.ico", format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    elif sys.platform == "darwin":
        artwork.resize((1024, 1024), Image.Resampling.LANCZOS).save(
            ICONS / "SmoothCast.icns", format="ICNS",
        )


def build() -> None:
    check_environment()
    if sys.platform in {"win32", "darwin"}:
        make_icons()
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", str(ROOT / "build" / "pyinstaller" / "work"),
        "--distpath", str(ROOT / "dist"), str(SPEC),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    from ci.verify_frozen_artifact import verify

    verify(ROOT / "dist")
    print("SmoothCast PyInstaller packaging and headless artefact checks passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only verify build dependencies")
    options = parser.parse_args(argv)
    try:
        check_environment()
        if not options.check:
            build()
        else:
            print("Native PyInstaller build prerequisites are available.")
    except (BuildError, subprocess.CalledProcessError, OSError) as exc:
        print(f"Packaging failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
