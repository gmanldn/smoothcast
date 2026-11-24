#!/usr/bin/env python3
"""Register SmoothCast's launcher and icon for the current Linux user.

Dock entries use the registered installation's absolute launcher, never an
accidental development checkout or same-named PATH command. The desktop ID matches GTK's application ID.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import shutil
import subprocess

APP_ID = "local.cast-control"  # Must equal src/cast_control.py:APP_ID
ROOT = Path(__file__).resolve().parents[1]
LEGACY_IDS = ("smoothcast.desktop", "cast-control.desktop")


def registration_root(*, installer_target: bool = False) -> Path:
    """Resolve the installed application; setup explicitly owns its new target.

    A broken saved installation must not silently repoint a working dock
    entry to a development checkout. Only an unregistered machine may use
    the checkout fallback.
    """
    if installer_target:
        return ROOT
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    pointer = config / "smoothcast" / "install-location"
    try:
        saved = pointer.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        candidate = Path.home() / ".local" / "opt" / "SmoothCast"
        if not candidate.exists():
            return ROOT
    else:
        candidate = Path(saved).expanduser()
    if (not candidate.is_absolute()
            or not (candidate / "smoothcast").is_file()
            or not (candidate / "setup" / "bootstrap.py").is_file()
            or not (candidate / "data" / "cast-control.png").is_file()
            or not (candidate / "pyproject.toml").is_file()
            or 'name = "smoothcast"' not in (candidate / "pyproject.toml").read_text(encoding="utf-8")):
        raise ValueError(f"Registered SmoothCast installation is incomplete: {candidate}. Rerun setup.")
    return candidate.resolve()


def exec_argument(path: Path) -> str:
    """Quote an absolute Exec argument per the Desktop Entry specification."""
    value = str(path.resolve())
    for before, after in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), (chr(96), "\\" + chr(96)), ("%", "%%")):
        value = value.replace(before, after)
    return f'"{value}"'


def desktop_entry(launcher: Path, *, legacy: bool = False) -> bytes:
    """Build a desktop entry whose Exec is the selected absolute launcher."""
    exec_value = exec_argument(launcher)
    try_exec = f"TryExec={launcher.resolve()}\n"
    path_line = f"Path={launcher.resolve().parent}\n"
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=SmoothCast\n"
        "Comment=Chromecast companion with live compressor metering\n"
        f"Exec={exec_value} %F\n"
        f"{try_exec}{path_line}"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        f"StartupWMClass={APP_ID}\n"
        "Categories=AudioVideo;Video;Audio;\n"
        "Keywords=chromecast;cast;stream;video;audio;\n"
    )
    if legacy:
        body += "NoDisplay=true\n"  # Existing pinned legacy launchers still work.
    return body.encode("utf-8")


def write_if_changed(destination: Path, contents: bytes) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() == contents:
        return False
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(contents)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def repair_gnome_favourites(*, pin: bool = False) -> bool:
    """Migrate SmoothCast's old dock pins; with pin=True also add a missing pin.

    Existing pins keep their positions; nothing is reordered or duplicated.
    """
    if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return False
    if not shutil.which("gsettings"):
        return False
    key = ("org.gnome.shell", "favorite-apps")
    try:
        result = subprocess.run(("gsettings", "get", *key), capture_output=True,
                                text=True, timeout=3, check=True)
        parsed = ast.literal_eval(result.stdout.strip().removeprefix("@as "))
        if not isinstance(parsed, list) or not all(isinstance(v, str) for v in parsed):
            return False
        replacement = f"{APP_ID}.desktop"
        updated: list[str] = []
        for item in parsed:
            item = replacement if item in LEGACY_IDS else item
            if item != replacement or item not in updated:
                updated.append(item)
        if pin and replacement not in updated:
            updated.append(replacement)
        if updated == parsed:
            return False
        subprocess.run(("gsettings", "set", *key, str(updated)),
                       capture_output=True, text=True, timeout=3, check=True)
        return True
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError):
        return False  # Unsupported shell/schema/session; never block launch.


def desktop_files(root: Path, base: Path) -> dict[Path, bytes]:
    """One source of truth for both installation and read-only verification."""
    apps = base / "applications"
    launcher = root / "smoothcast"
    icon = base / "icons" / "hicolor" / "128x128" / "apps" / f"{APP_ID}.png"
    files = {icon: (root / "data" / "cast-control.png").read_bytes(),
             apps / f"{APP_ID}.desktop": desktop_entry(launcher)}
    files.update({apps / name: desktop_entry(launcher, legacy=True) for name in LEGACY_IDS})
    return files


def install(*, data_home: Path | None = None, repair_pins: bool = True,
            pin: bool = False, installer_target: bool = False) -> bool:
    """Register the installed application, preserving both legacy dock IDs."""
    root = registration_root(installer_target=installer_target)
    base = data_home or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
    changed = False
    for destination, contents in desktop_files(root, base).items():
        changed |= write_if_changed(destination, contents)
    if repair_pins:
        changed |= repair_gnome_favourites(pin=pin)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check desktop integration without modifying files")
    parser.add_argument("--pin", action="store_true", help="Also pin SmoothCast to the GNOME dock (adds it to favorite-apps if missing)")
    parser.add_argument("--installer-target", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.check:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
            root = registration_root(installer_target=args.installer_target)
            ok = all(path.is_file() and path.read_bytes() == contents
                     for path, contents in desktop_files(root, base).items())
            if not args.quiet:
                print("SmoothCast desktop integration: OK" if ok else "SmoothCast desktop integration: needs repair")
            return 0 if ok else 1
        changed = install(repair_pins=True, pin=args.pin, installer_target=args.installer_target)
        if not args.quiet:
            print("SmoothCast desktop integration: repaired" if changed else "SmoothCast desktop integration: OK")
        return 0
    except (OSError, ValueError) as exc:
        if not args.quiet:
            print(f"SmoothCast desktop integration: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())