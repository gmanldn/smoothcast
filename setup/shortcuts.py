"""Register SmoothCast in the current user's native application launcher.

Linux uses the existing XDG installer. macOS gets an ~/Applications .app
bundle. Windows gets a Start Menu shortcut. No system-wide changes are needed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def install_linux() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "install_desktop.py")],
        check=True, timeout=30,
    )


def app_launcher(python: Path, launch_script: Path) -> str:
    """Shell script for a user-local macOS .app launcher."""
    return (
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(python))} "
        f"{shlex.quote(str(launch_script))} \"$@\"\n"
    )


def install_macos(*, home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    app = base / "Applications" / "SmoothCast.app"
    executable = app / "Contents" / "MacOS" / "SmoothCast"
    plist = app / "Contents" / "Info.plist"
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    source = ROOT / "data" / "cast-control.png"
    if not source.is_file():
        raise FileNotFoundError(f"SmoothCast icon is missing: {source}")
    shutil.copy2(source, resources / "SmoothCast.png")
    if sys.platform == "darwin":
        # Finder and the macOS Dock expect a real multi-resolution .icns file.
        with tempfile.TemporaryDirectory(prefix="smoothcast-icon-") as temp:
            iconset = Path(temp) / "SmoothCast.iconset"
            iconset.mkdir()
            for pixels, name in ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
                                 (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
                                 (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                                 (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
                                 (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")):
                subprocess.run(["sips", "-s", "format", "png", "-z", str(pixels),
                                str(pixels), str(source), "--out", str(iconset / name)],
                               stdout=subprocess.DEVNULL, check=True, timeout=30)
            subprocess.run(["iconutil", "-c", "icns", "-o",
                            str(resources / "SmoothCast.icns"), str(iconset)],
                           check=True, timeout=30)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(
        app_launcher(Path(sys.executable), ROOT / "setup" / "launch.py"),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    metadata = {
        "CFBundleIdentifier": "local.smoothcast.player",
        "CFBundleExecutable": "SmoothCast",
        "CFBundleName": "SmoothCast",
        "CFBundleDisplayName": "SmoothCast",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "SmoothCast.icns" if sys.platform == "darwin" else "SmoothCast.png",
        "CFBundleShortVersionString": _version(),
        "NSHighResolutionCapable": True,
    }
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open("wb") as fh:
        plistlib.dump(metadata, fh)
    return app


def _version() -> str:
    path = ROOT / "src" / "version.py"
    try:
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and type(node.value.value) is int):
                values[node.targets[0].id] = node.value.value
        return ".".join(str(values[key]) for key in ("MAJOR", "MINOR", "PATCH"))
    except (OSError, ValueError, SyntaxError, KeyError):
        return "1.0.0"


def ps_literal(value: str | Path) -> str:
    """Single-quote a Windows PowerShell literal; do not evaluate paths."""
    return "'" + str(value).replace("'", "''") + "'"


def windows_shortcut_command(
    *, executable: Path, launcher: Path, destination: Path,
    working_dir: Path, icon: Path | None = None,
) -> str:
    args = f'"{launcher}"'
    icon_command = (f"$s.IconLocation={ps_literal(icon)}; " if icon else "")
    return (
        "$w=New-Object -ComObject WScript.Shell; "
        f"$s=$w.CreateShortcut({ps_literal(destination)}); "
        f"$s.TargetPath={ps_literal(executable)}; "
        f"$s.Arguments={ps_literal(args)}; "
        f"$s.WorkingDirectory={ps_literal(working_dir)}; "
        f"{icon_command}"
        "$s.Save()"
    )


def write_windows_icon(source: Path, destination: Path) -> None:
    """Build a Windows Vista+ PNG-compressed ICO without Pillow or extra tools."""
    png = source.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or png[12:16] != b"IHDR":
        raise ValueError("SmoothCast icon must be a PNG image")
    width, height = struct.unpack(">II", png[16:24])
    if not (1 <= width <= 256 and 1 <= height <= 256):
        raise ValueError("SmoothCast icon must be 1–256 pixels for ICO conversion")
    header = struct.pack("<HHH", 0, 1, 1)
    header += struct.pack("<BBBBHHII", width % 256, height % 256,
                          0, 0, 1, 32, len(png), 22)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(header + png)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_windows(*, appdata: Path | None = None) -> Path:
    roaming = appdata if appdata is not None else Path(os.environ["APPDATA"])
    menu = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    menu.mkdir(parents=True, exist_ok=True)
    shortcut = menu / "SmoothCast.lnk"
    local = Path(os.environ.get("LOCALAPPDATA") or roaming.parent.parent / "Local")
    icon = local / "SmoothCast" / "SmoothCast.ico"
    write_windows_icon(ROOT / "data" / "cast-control.png", icon)
    script = windows_shortcut_command(
        executable=Path(sys.executable),
        launcher=ROOT / "setup" / "launch.py",
        destination=shortcut,
        working_dir=ROOT,
        icon=icon,
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True, timeout=30,
    )
    return shortcut


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("linux", "macos", "windows"), required=True)
    opts = parser.parse_args()
    if opts.target == "linux":
        install_linux()
        print("SmoothCast added to the user's desktop application menu.")
    elif opts.target == "macos":
        print(f"SmoothCast application: {install_macos()}")
    elif opts.target == "windows":
        print(f"SmoothCast Start Menu shortcut: {install_windows()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
