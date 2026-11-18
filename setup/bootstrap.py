"""SmoothCast installer: Python 3.10+ and operating-system built-ins only.

Native GTK4/libadwaita and FFmpeg must be installed through the platform's
package manager. Never silently report installation success when native GTK,
the CLI, or the isolated runtime is missing.

This is a bootstrapper, not a guarantee of cross-platform feature parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
GUI_CHECK = (
    "import gi; gi.require_version('Gtk','4.0'); "
    "gi.require_version('Adw','1'); "
    "from gi.repository import Gtk, Adw"
)
CATT_CHECK = (
    "import importlib.metadata as m,re; "
    "v=m.version('catt'); "
    "parts=[int(x) for x in re.findall(r'\\d+',v)[:2]]; "
    "assert tuple(parts) >= (0,12)"
)
# pip dependencies installed into the isolated runtime. Keep in sync with the
# `dependencies` list in pyproject.toml; the project itself is installed in
# editable mode alongside these, and there is no separate requirements file.
PIP_PACKAGES = ("catt>=0.12",)
WINDOWS_PACKAGES = (
    "mingw-w64-ucrt-x86_64-python",
    "mingw-w64-ucrt-x86_64-python-pip",
    "mingw-w64-ucrt-x86_64-python-gobject",
    "mingw-w64-ucrt-x86_64-gtk4",
    "mingw-w64-ucrt-x86_64-libadwaita",
    "mingw-w64-ucrt-x86_64-ffmpeg",
    "mingw-w64-ucrt-x86_64-gcc",  # pip may build pure/native dependencies
)
LINUX_PACKAGES = {
    "apt-get": (
        "python3-gi", "python3-gi-cairo", "gir1.2-gtk-4.0",
        "gir1.2-adw-1", "python3-venv", "ffmpeg",
        "libgtk-4-media-gstreamer", "gstreamer1.0-plugins-base",
        "gstreamer1.0-plugins-good", "gstreamer1.0-libav",
    ),
    "dnf": ("python3-gobject", "gtk4", "libadwaita", "python3-pip",
            "ffmpeg-free", "gstreamer1-plugins-base", "gstreamer1-plugins-good"),
    "pacman": ("python-gobject", "gtk4", "libadwaita", "ffmpeg",
               "gst-plugins-base", "gst-plugins-good", "gst-libav"),
}


class SetupError(RuntimeError):
    pass


def say(message: str) -> None:
    print(f"[SmoothCast setup] {message}", flush=True)


def checked_run(command: list[str], *, env: dict[str, str] | None = None,
                timeout: int = 1800) -> None:
    say("Running: " + " ".join(map(str, command)))
    try:
        subprocess.run(list(map(str, command)), env=env, check=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Command failed: {exc}") from exc


def works(python: Path | str, code: str, *, env: dict[str, str] | None = None) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", code], env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=20, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def python_ok(python: Path | str) -> bool:
    return works(python, "import sys; assert sys.version_info >= (3,10)")


def manager_for_linux(which=shutil.which) -> str | None:
    for manager in ("apt-get", "dnf", "pacman"):
        if which(manager):
            return manager
    return None


def privileged(command: list[str]) -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return command
    if shutil.which("sudo"):
        return ["sudo", *command]
    raise SetupError("System package installation needs sudo (or a root shell).")


def venv_python(venv: Path = VENV) -> Path:
    candidates = [venv / "bin" / "python", venv / "Scripts" / "python.exe",
                  venv / "bin" / "python.exe"]
    return next((p for p in candidates if p.is_file()), candidates[0])


def check_tools(env: dict[str, str] | None = None) -> list[str]:
    path = None if env is None else env.get("PATH")
    return [tool for tool in ("ffmpeg", "ffprobe", "ffplay")
            if not shutil.which(tool, path=path)]


def pick_runtime(candidates: list[Path | str], *,
                 env: dict[str, str] | None = None) -> Path:
    for candidate in candidates:
        if python_ok(candidate) and works(candidate, GUI_CHECK, env=env):
            return Path(candidate)
    raise SetupError(
        "No Python 3.10+ interpreter with GTK4 and libadwaita bindings "
        "was found after installing native packages."
    )


def linux_media_ready(manager: str) -> bool:
    """GTK's video decoder requires native media plugins, not just PyGObject."""
    if manager == "apt-get":
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", "libgtk-4-media-gstreamer"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return result.returncode == 0 and "install ok installed" in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
    return bool(shutil.which("gst-inspect-1.0"))


def install_linux(*, check: bool = False) -> tuple[Path, dict[str, str]]:
    candidates = [Path("/usr/bin/python3"), Path(sys.executable)]
    missing = check_tools()
    ready = next((p for p in candidates
                  if python_ok(p) and works(p, GUI_CHECK)), None)
    if check:
        if not ready or missing:
            raise SetupError(f"Linux prerequisites missing: GTK={not bool(ready)}, "
                             f"tools={', '.join(missing) or 'none'}")
        return Path(ready), dict(os.environ)
    manager = manager_for_linux()
    if not ready or missing or (manager is not None and not linux_media_ready(manager)):
        if not manager:
            raise SetupError(
                "Unsupported Linux package manager; supported: apt-get, dnf, pacman."
            )
        command = [manager, "install"]
        if manager == "apt-get":
            command += ["-y"]
        elif manager == "dnf":
            command += ["-y"]
        elif manager == "pacman":
            command = [manager, "-S", "--needed", "--noconfirm"]
        command += list(LINUX_PACKAGES[manager])
        checked_run(privileged(command))
    return pick_runtime(candidates), dict(os.environ)


def find_brew() -> str | None:
    return (shutil.which("brew") or next(
        (str(p) for p in (Path("/opt/homebrew/bin/brew"),
                          Path("/usr/local/bin/brew")) if p.exists()), None
    ))


def install_macos(*, check: bool = False) -> tuple[Path, dict[str, str]]:
    brew = find_brew()
    if not brew and not check:
        # Homebrew's documented, noninteractive installer; requires network
        # and can ask the OS for administrator approval.
        if not shutil.which("curl"):
            raise SetupError("curl is needed to install Homebrew on macOS.")
        say("Homebrew is absent; installing from the official installer.")
        checked_run([
            "/bin/bash", "-c",
            'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL '
            'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
        ])
        brew = find_brew()
    if not brew:
        raise SetupError("Homebrew not found. Install it from https://brew.sh/.")
    try:
        prefix = subprocess.check_output(
            [brew, "--prefix"], text=True, timeout=30,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Homebrew is not usable: {exc}") from exc
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join((str(Path(prefix) / "bin"),
                                    str(Path(prefix) / "sbin"), env.get("PATH", "")))
    candidates = [Path(prefix) / "bin" / "python3", Path(sys.executable)]
    missing = check_tools(env)
    good = next((p for p in candidates
                 if python_ok(p) and works(p, GUI_CHECK, env=env)), None)
    if not check and (good is None or missing):
        checked_run([brew, "install", "python", "pygobject3", "gtk4",
                     "libadwaita", "ffmpeg", "gstreamer"], env=env)
    if check and (good is None or missing):
        raise SetupError(f"macOS prerequisites missing: GTK={not bool(good)}, "
                         f"tools={', '.join(missing) or 'none'}")
    return pick_runtime(candidates, env=env), env


def msys2_root() -> Path:
    custom = os.environ.get("MSYS2_ROOT")
    return Path(custom) if custom else Path(os.environ.get("SystemDrive", "C:") + "\\msys64")


def download_verified_msys2() -> Path:
    """Fetch the official latest installer and sidecar checksum from GitHub."""
    api = "https://api.github.com/repos/msys2/msys2-installer/releases/latest"
    request = urllib.request.Request(
        api, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "SmoothCast-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.load(response)
        assets = data["assets"]
        installers = [a for a in assets if re.fullmatch(
            r"msys2-x86_64-\d+\.exe", a.get("name", "")
        )]
        if len(installers) != 1:
            raise SetupError("Could not identify the official MSYS2 installer.")
        binary = installers[0]
        checksum_name = binary["name"] + ".sha256"
        checksum = next(a for a in assets if a.get("name") == checksum_name)
        with urllib.request.urlopen(checksum["browser_download_url"], timeout=45) as r:
            checksum_data = r.read(4096).decode("ascii").strip()
        expected = checksum_data.split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise SetupError("Invalid checksum published for MSYS2 installer.")
        destination = Path(tempfile.gettempdir()) / binary["name"]
        digest = hashlib.sha256()
        with urllib.request.urlopen(binary["browser_download_url"], timeout=60) as r, \
             destination.open("wb") as out:
            while chunk := r.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != expected:
            destination.unlink(missing_ok=True)
            raise SetupError("MSYS2 installer SHA-256 mismatch; aborting.")
        return destination
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise SetupError(f"MSYS2 download/verification failed: {exc}") from exc


def windows_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        (str(root / "ucrt64" / "bin"), str(root / "usr" / "bin"),
         env.get("PATH", "")),
    )
    env["MSYSTEM"] = "UCRT64"
    # PyGObject's MSYS2 runtime needs an explicit DLL search directory.
    env["PYGI_DLL_PATH"] = str(root / "ucrt64" / "bin")
    env["GI_TYPELIB_PATH"] = str(root / "ucrt64" / "lib" / "girepository-1.0")
    env["XDG_DATA_DIRS"] = os.pathsep.join(
        (str(root / "ucrt64" / "share"), env.get("XDG_DATA_DIRS", "")),
    )
    return env


def install_windows(*, check: bool = False) -> tuple[Path, dict[str, str]]:
    root = msys2_root()
    native_python = root / "ucrt64" / "bin" / "python.exe"
    env = windows_env(root)
    ready = python_ok(native_python) and works(native_python, GUI_CHECK, env=env)
    missing = check_tools(env)
    if check:
        if not ready or missing:
            raise SetupError(f"Windows UCRT64 prerequisites missing: "
                             f"GTK={not ready}, tools={', '.join(missing) or 'none'}")
        return native_python, env
    if not (root / "usr" / "bin" / "bash.exe").is_file():
        say("MSYS2 is missing: downloading the official checksum-verified installer.")
        installer = download_verified_msys2()
        try:
            checked_run([str(installer), "in", "--confirm-command",
                         "--accept-messages", "--root", root.as_posix()],
                        timeout=1800)
        finally:
            installer.unlink(missing_ok=True)
    shell = root / "usr" / "bin" / "bash.exe"
    if not shell.is_file():
        raise SetupError("MSYS2 installation incomplete: bash.exe is missing.")
    if not ready or missing:
        # Updating MSYS2 is essential for its package trust database. Run a
        # second pass because first-time updates may replace the pacman binary.
        update = ["pacman", "-Syuu", "--noconfirm"]
        for _ in range(2):
            checked_run([str(shell), "-lc", " ".join(update)], env=env, timeout=1800)
        checked_run([
            str(shell), "-lc",
            "pacman -S --needed --noconfirm " + " ".join(WINDOWS_PACKAGES),
        ], env=env, timeout=1800)
    return pick_runtime([native_python], env=env), env


def ensure_venv(python: Path, env: dict[str, str], *,
                check: bool = False) -> Path:
    installed = venv_python()
    if check:
        if not installed.is_file() or not works(installed, GUI_CHECK, env=env):
            raise SetupError("SmoothCast virtual environment is missing or cannot load GTK.")
    else:
        if installed.is_file() and not works(installed, GUI_CHECK, env=env):
            # The project-owned venv may have been created with an unrelated
            # Python. Preserve it for inspection, then recreate with the
            # native interpreter whose GTK imports we just verified.
            backup = VENV.with_name(f".venv-incompatible-{int(time.time())}")
            VENV.rename(backup)
            say(f"Preserved stale environment at {backup}")
        if not venv_python().is_file():
            say(f"Creating isolated virtual environment: {VENV}")
            checked_run([str(python), "-m", "venv", "--system-site-packages",
                         str(VENV)], env=env)
        installed = venv_python()
        if not works(installed, GUI_CHECK, env=env):
            raise SetupError(
                f"{installed} cannot import GTK4/libadwaita after rebuild. "
                "Review the native Python/PyGObject installation."
            )
        if not works(installed, CATT_CHECK, env=env):
            # The project declares its dependencies in pyproject.toml. Install
            # catt explicitly and the project itself in editable mode into the
            # *selected venv* so every launcher resolves the same catt
            # dependency; do not download or replace native GTK bindings.
            checked_run([str(installed), "-m", "pip", "install",
                         "--disable-pip-version-check", *PIP_PACKAGES,
                         "-e", str(ROOT)], env=env)
    if not works(installed, CATT_CHECK, env=env):
        raise SetupError("catt >= 0.12 is not installed in SmoothCast's environment.")
    missing = check_tools(env)
    if missing:
        raise SetupError("Media dependencies are missing: " + ", ".join(missing))
    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap SmoothCast from Python 3.10+")
    parser.add_argument("--target", choices=("linux", "macos", "windows"), required=True)
    parser.add_argument("--check", action="store_true",
                        help="Verify only; never install or modify anything")
    parser.add_argument("--no-shortcuts", action="store_true")
    args = parser.parse_args(argv)
    actual = {"Linux": "linux", "Darwin": "macos",
              "Windows": "windows"}.get(platform.system())
    if args.target != actual:
        parser.error(f"{args.target} setup cannot run on {platform.system()}")
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ is the initial prerequisite.")
    try:
        say(f"Operating system: {args.target}; bootstrap Python: {sys.version.split()[0]}")
        install = {"linux": install_linux, "macos": install_macos,
                   "windows": install_windows}[args.target]
        python, env = install(check=args.check)
        isolated = ensure_venv(python, env, check=args.check)
        if not args.check and not args.no_shortcuts:
            checked_run([str(isolated), str(ROOT / "setup" / "shortcuts.py"),
                         "--target", args.target], env=env)
        say(f"Verified Python/GTK4/libadwaita/catt/FFmpeg: {isolated}")
        if not args.check:
            say(f"Installed. Launch with: {isolated} {ROOT / 'setup' / 'launch.py'}")
        return 0
    except SetupError as exc:
        print(f"[SmoothCast setup] FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
