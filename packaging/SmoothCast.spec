"""Canonical native PyInstaller onedir build; invoked by scripts/build_release.py.

Do not use --onefile: GTK resources, local media helpers and startup latency
make an explicit folder (or macOS .app bundle) the safer release format.
Build separately on each OS using the OS-native GTK/PyGObject interpreter.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ICON_ROOT = ROOT / "build" / "pyinstaller" / "icons"
ICON = ICON_ROOT / ("SmoothCast.ico" if sys.platform == "win32" else "SmoothCast.icns")
if sys.platform in {"win32", "darwin"} and not ICON.is_file():
    raise FileNotFoundError(f"Build icon missing: {ICON}; use scripts/build_release.py")

catt_datas, catt_binaries, catt_modules = collect_all("catt")
ytdlp_datas, ytdlp_binaries, ytdlp_modules = collect_all("yt_dlp")

a = Analysis(
    [str(ROOT / "src" / "frozen_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[*catt_binaries, *ytdlp_binaries],
    datas=[
        (str(ROOT / "LICENSE"), "legal"),
        (str(ROOT / "packaging" / "SmoothCast-NOTICE.txt"), "legal"),
        (str(ROOT / "src" / "smoothcast_assets" / "local.cast-control.png"), "smoothcast_assets"),
        (str(ROOT / "data" / "cast-control.png"), "data"),
        *catt_datas,
        *ytdlp_datas,
    ],
    hiddenimports=[
        *catt_modules,
        *ytdlp_modules,
        *collect_submodules("pychromecast"),
        "gi.repository.Gtk",
        "gi.repository.Adw",
        "gi.repository.Gdk",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.Gst",
        "portal",
        "cast_portal",
    ],
    hookspath=[],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "languages": ["en_GB"],
            "module-versions": {"Gtk": "4.0", "Adw": "1"},
        },
    },
    noarchive=False,
)
pyz = PYZ(a.pure)

# A GUI entry never flashes a Windows console. The console companion is also
# shipped for support/CI, so --version and --diagnostics produce visible output.
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="SmoothCast",
    console=sys.platform not in {"win32", "darwin"},
    icon=str(ICON) if sys.platform in {"win32", "darwin"} else None,
    strip=False, upx=False,
)
console_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="SmoothCastCLI",
    console=True,
    icon=str(ICON) if sys.platform in {"win32", "darwin"} else None,
    strip=False, upx=False,
)
bundle = COLLECT(
    exe, console_exe, a.binaries, a.datas,
    strip=False, upx=False, name="SmoothCast",
)
if sys.platform == "darwin":
    app = BUNDLE(
        bundle, name="SmoothCast.app",
        icon=str(ICON),
        bundle_identifier="local.smoothcast.player",
        info_plist={"CFBundleName": "SmoothCast", "CFBundleDisplayName": "SmoothCast"},
    )
