#!/usr/bin/env python3
"""Register SmoothCast's launcher and icon for the current Linux user.

Safe to run on every GUI launch; no sudo, no PATH assumptions, no duplicate
visible application entry. The desktop ID matches GTK's application ID.
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


def exec_argument(path: Path) -> str:
    """Quote an absolute Exec argument per the Desktop Entry specification."""
    value = str(path.resolve())
    for before, after in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), (chr(96), "\\" + chr(96)), ("%", "%%")):
        value = value.replace(before, after)
    return f'"{value}"'


def desktop_entry(launcher, *, legacy: bool = False) -> bytes:
    """Build a desktop entry whose Exec is either a bare command name or a path.

    A bare name (e.g. ``smoothcast``) is used once the pip-installed console
    script is the canonical entry point; it relies on the user's PATH, which
    always includes ``~/.local/bin`` for GUI sessions after ``pip install``.
    """
    if isinstance(launcher, Path):
        exec_value = exec_argument(launcher)
    else:
        exec_value = str(launcher)
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=SmoothCast\n"
        "Comment=Chromecast companion with live compressor metering\n"
        f"Exec={exec_value} %F\n"
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


def install(*, data_home: Path | None = None, repair_pins: bool = True, pin: bool = False) -> bool:
    """Install the canonical desktop entry and icon; repair legacy pins.

    The canonical launcher is the pip-installed ``smoothcast`` console script
    (bare command name, resolved through the user's PATH). The legacy
    ``smoothcast.desktop`` entry is still written (hidden) so existing dock
    pins keep working until GNOME favourites are migrated.
    """
    source_icon = ROOT / "data" / "cast-control.png"
    if not source_icon.is_file():
        raise FileNotFoundError("SmoothCast icon missing from checkout")
    base = data_home or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
    apps = base / "applications"
    icon = base / "icons" / "hicolor" / "128x128" / "apps" / f"{APP_ID}.png"
    changed = write_if_changed(icon, source_icon.read_bytes())
    # Canonical entry: bare command name (PATH resolves to the pip-installed script).
    changed |= write_if_changed(apps / f"{APP_ID}.desktop", desktop_entry("smoothcast"))
    # Shadow any system-wide legacy entry and keep existing legacy dock pins usable.
    changed |= write_if_changed(apps / "smoothcast.desktop", desktop_entry("smoothcast", legacy=True))
    # The originally shipped desktop ID was smoothcast.desktop; GNOME favourites
    # need updating to the real GTK app ID for dock grouping and window focusing.
    if repair_pins:
        changed |= repair_gnome_favourites(pin=pin)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check desktop integration without modifying files")
    parser.add_argument("--pin", action="store_true", help="Also pin SmoothCast to the GNOME dock (adds it to favorite-apps if missing)")
    args = parser.parse_args()
    try:
        if args.check:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
            ok = (base / "applications" / f"{APP_ID}.desktop").read_bytes() == desktop_entry("smoothcast")
            ok &= (base / "icons" / "hicolor" / "128x128" / "apps" / f"{APP_ID}.png").read_bytes() == (ROOT / "data" / "cast-control.png").read_bytes()
            if not args.quiet:
                print("SmoothCast desktop integration: OK" if ok else "SmoothCast desktop integration: needs repair")
            return 0 if ok else 1
        changed = install(repair_pins=True, pin=args.pin)
        if not args.quiet:
            print("SmoothCast desktop integration: repaired" if changed else "SmoothCast desktop integration: OK")
        return 0
    except (OSError, ValueError) as exc:
        if not args.quiet:
            print(f"SmoothCast desktop integration: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
