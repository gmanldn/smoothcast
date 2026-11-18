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
import subprocess
import sys

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
    working_dir: Path,
) -> str:
    args = f'"{launcher}"'
    return (
        "$w=New-Object -ComObject WScript.Shell; "
        f"$s=$w.CreateShortcut({ps_literal(destination)}); "
        f"$s.TargetPath={ps_literal(executable)}; "
        f"$s.Arguments={ps_literal(args)}; "
        f"$s.WorkingDirectory={ps_literal(working_dir)}; "
        "$s.Save()"
    )


def install_windows(*, appdata: Path | None = None) -> Path:
    roaming = appdata if appdata is not None else Path(os.environ["APPDATA"])
    menu = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    menu.mkdir(parents=True, exist_ok=True)
    shortcut = menu / "SmoothCast.lnk"
    script = windows_shortcut_command(
        executable=Path(sys.executable),
        launcher=ROOT / "setup" / "launch.py",
        destination=shortcut,
        working_dir=ROOT,
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
