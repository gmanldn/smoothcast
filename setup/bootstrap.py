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

import native_runtime
import install_location

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
GUI_CHECK = (
    "import gi; gi.require_version('Gtk','4.0'); "
    "gi.require_version('Adw','1'); "
    "from gi.repository import Gtk, Adw"
)
CAST_DEPENDENCIES_CHECK = (
    "import importlib.metadata as m,re,sys; "
    "v=m.version('catt'); "
    "c=re.fullmatch(r'(\\d+)\\.(\\d+)(?:\\.\\d+)?'"
    "r'(?:\\.post\\d+)?(?:\\+[A-Za-z0-9.]+)?',v); "
    "p=m.version('PyChromecast'); "
    "pc=re.fullmatch(r'(\\d+)\\.(\\d+)\\.(\\d+)'"
    "r'(?:\\.post\\d+)?(?:\\+[A-Za-z0-9.]+)?',p); "
    "pv=tuple(map(int,pc.groups())) if pc else (); "
    "sys.exit(0 if c and (int(c[1]),int(c[2])) >= (0,12) "
    "and pc and (13,1,0) <= pv < (15,0,0) else 1)"
)
# pip dependencies installed into the isolated runtime. Keep in sync with the
# `dependencies` list in pyproject.toml; the project itself is installed in
# editable mode alongside these, and there is no separate requirements file.
PIP_PACKAGES = ("catt>=0.12,<0.14", "PyChromecast>=13.1.0,<15",
                "psutil>=5.9,<8", "zeroconf>=0.132,<1", "segno>=1.6,<2")
# The project itself must be installed: a venv may have catt from an unrelated app
# but still lack SmoothCast or its other runtime dependencies. pip enforces version ranges.
PROJECT_DEPENDENCIES_CHECK = (
    "import importlib.metadata as m,sys; import psutil,zeroconf,segno; "
    "p=m.version('psutil').split('.'); z=m.version('zeroconf').split('.'); "
    "s=m.version('segno').split('.'); v=m.version('smoothcast'); "
    "sys.exit(0 if (5,9) <= tuple(map(int,p[:2])) < (8,0) "
    "and (0,132) <= tuple(map(int,z[:2])) < (1,0) and (1,6) <= tuple(map(int,s[:2])) < (2,0) and v else 1)"
)
# A compromised or corrupt release asset must never exhaust the local disk.
MAX_MSYS2_DOWNLOAD_BYTES = 1024 * 1024 * 1024
# Reviewed immutable Homebrew installer (2026-11-18); update commit and digest
# together only after reviewing the new upstream script. Never execute HEAD.
HOMEBREW_INSTALL_COMMIT = "eaa2af62ca1d5349c9743f82b1b0c4e5d365fb2d"
HOMEBREW_INSTALL_SHA256 = "8fd2f1a5287a7c2e3d7362924c677edcc04c5a0e16448c77132d056bc88cf1ed"
HOMEBREW_INSTALL_MAX_BYTES = 256 * 1024
HOMEBREW_INSTALL_URL = (
    "https://raw.githubusercontent.com/Homebrew/install/"
    f"{HOMEBREW_INSTALL_COMMIT}/install.sh"
)

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
    return works(python, "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)")


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
    """Verify the actual media executables, not only names on PATH.

    Loader failures, nonzero exits and hangs have previously passed a PATH
    lookup, causing the app to fail later while playing a film.
    """
    path = None if env is None else env.get("PATH")
    failures: list[str] = []
    for tool in ("ffmpeg", "ffprobe", "ffplay"):
        executable = shutil.which(tool, path=path)
        if not executable:
            failures.append(tool + " (missing)")
            continue
        try:
            result = subprocess.run(
                [executable, "-version"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if tool == "ffmpeg" else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=env, timeout=4, check=False,
            )
        except subprocess.TimeoutExpired:
            failures.append(tool + " (version probe timed out)")
        except OSError:
            failures.append(tool + " (failed to start; check loader/runtime)")
        else:
            if result.returncode != 0:
                failures.append(f"{tool} (version probe exited {result.returncode})")
            elif tool == "ffmpeg" and result.stdout:
                version = result.stdout.decode("utf-8", "replace") if isinstance(
                    result.stdout, bytes) else str(result.stdout)
                match = re.search(r"(?m)^ffmpeg version (?:n)?(\d+)", version)
                if match and int(match.group(1)) < 5:
                    failures.append(f"ffmpeg {match.group(1)} (requires >=5.0)")
                elif not match:
                    failures.append("ffmpeg (unrecognised version; requires >=5.0)")
    return failures


def venv_supported(python: Path | str) -> bool:
    """Exercise venv+ensurepip in disposable storage, without installing.

    Debian can import the venv module yet fail to create an environment
    because python3-venv/ensurepip is absent. --help would miss that failure.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="smoothcast-venv-probe-") as temp:
            target = Path(temp) / "probe"
            result = subprocess.run(
                [str(python), "-m", "venv", "--system-site-packages", str(target)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=30, check=False,
            )
            return result.returncode == 0 and (target / "pyvenv.cfg").is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


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
    manager = manager_for_linux()
    venv_ready = bool(ready) and (
        manager != "apt-get" or venv_supported(ready)
    )
    if check:
        if not ready or missing or not venv_ready:
            raise SetupError(
                f"Linux prerequisites missing: GTK={not bool(ready)}, "
                f"tools={', '.join(missing) or 'none'}, "
                f"venv/ensurepip={not venv_ready} "
                "(on Debian/Ubuntu install python3-venv)"
            )
        return Path(ready), dict(os.environ)
    if not ready or missing or not venv_ready or (manager is not None and not linux_media_ready(manager)):
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


def download_verified_homebrew() -> bytes:
    """Download a pinned Homebrew installer with bounded size and SHA-256.

    Returns verified bytes; never writes or executes untrusted partial data.
    Offline tests replace urlopen, and a failed check never reaches Bash.
    """
    request = urllib.request.Request(
        HOMEBREW_INSTALL_URL, headers={"User-Agent": "SmoothCast-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            script = response.read(HOMEBREW_INSTALL_MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise SetupError(f"Homebrew installer download failed: {exc}") from exc
    if not script or len(script) > HOMEBREW_INSTALL_MAX_BYTES:
        raise SetupError("Homebrew installer is empty or exceeds safe download size")
    if hashlib.sha256(script).hexdigest() != HOMEBREW_INSTALL_SHA256:
        raise SetupError("Homebrew installer SHA-256 mismatch; refusing execution")
    if not script.startswith(b"#!/bin/bash\n"):
        raise SetupError("Verified Homebrew installer lacks the expected Bash header")
    return script


def install_macos(*, check: bool = False) -> tuple[Path, dict[str, str]]:
    brew = find_brew()
    if not brew and not check:
        # Never pipe mutable network content into Bash. Download, bound,
        # compare against the reviewed SHA-256 and only then invoke a file.
        say("Homebrew is absent; downloading checksum-verified pinned installer.")
        verified_script = download_verified_homebrew()
        with tempfile.TemporaryDirectory(prefix="smoothcast-homebrew-") as directory:
            script = Path(directory) / "install.sh"
            script.write_bytes(verified_script)
            install_env = dict(os.environ)
            install_env["NONINTERACTIVE"] = "1"
            checked_run(["/bin/bash", str(script)], env=install_env)
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
    env["SMOOTHCAST_NATIVE_PREFIX"] = str(Path(prefix).resolve())
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
        # Each caller gets a private, randomly named directory, avoiding
        # same-name races and symlink attacks in the shared OS temp folder.
        directory = Path(tempfile.mkdtemp(prefix="smoothcast-msys2-"))
        destination = directory / binary["name"]
        try:
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(binary["browser_download_url"], timeout=60) as r, \
                 destination.open("xb") as out:
                while chunk := r.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_MSYS2_DOWNLOAD_BYTES:
                        raise SetupError("MSYS2 installer exceeds safe download size limit.")
                    out.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise SetupError("MSYS2 installer SHA-256 mismatch; aborting.")
            return destination
        except BaseException:
            # Includes network failure, invalid checksum and Ctrl+C: never
            # retain or execute a partial/unverified installer payload.
            shutil.rmtree(directory, ignore_errors=True)
            raise
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise SetupError(f"MSYS2 download/verification failed: {exc}") from exc


def windows_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        (str(root / "ucrt64" / "bin"), str(root / "usr" / "bin"),
         env.get("PATH", "")),
    )
    env["MSYSTEM"] = "UCRT64"
    env["MSYS2_ROOT"] = str(root.resolve())
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
            # Only remove the newly created private staging directory, never
            # a global temp path or the actual MSYS2 installation tree.
            if installer.parent.name.startswith("smoothcast-msys2-"):
                shutil.rmtree(installer.parent, ignore_errors=True)
            else:
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
        if not works(installed, CAST_DEPENDENCIES_CHECK, env=env) or not works(
                installed, PROJECT_DEPENDENCIES_CHECK, env=env):
            raise SetupError("SmoothCast runtime packages are missing or invalid "
                             "(catt, PyChromecast, psutil, zeroconf, segno, smoothcast).")
        missing = check_tools(env)
        if missing:
            raise SetupError("Media dependencies are missing: " + ", ".join(missing))
        return installed

    # A failed rebuild must not strand an existing installation, including a
    # partially populated project .venv whose Python executable is missing.
    # Move it aside before attempting replacement; do not modify user files.
    original_exists = VENV.exists() or VENV.is_symlink()
    backup: Path | None = None
    incompatible = (
        original_exists and (
            not installed.is_file() or not works(installed, GUI_CHECK, env=env)
        )
    )
    if incompatible:
        backup = VENV.with_name(f".venv-incompatible-{time.time_ns()}")
        VENV.rename(backup)
        say(f"Preserved stale environment at {backup}")
    try:
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
        if (not works(installed, CAST_DEPENDENCIES_CHECK, env=env) or
                not works(installed, PROJECT_DEPENDENCIES_CHECK, env=env)):
            # The project declares its dependencies in pyproject.toml. Install
            # missing runtime packages and the project in editable mode into
            # the *selected venv* so every launcher resolves the same runtime;
            # do not download or replace native GTK bindings.
            checked_run([str(installed), "-m", "pip", "install",
                         "--disable-pip-version-check", *PIP_PACKAGES,
                         "-e", str(ROOT)], env=env)
        if not works(installed, CAST_DEPENDENCIES_CHECK, env=env) or not works(
                installed, PROJECT_DEPENDENCIES_CHECK, env=env):
            raise SetupError("SmoothCast runtime packages could not be installed "
                             "(catt, PyChromecast, psutil, zeroconf, segno, smoothcast).")
        missing = check_tools(env)
        if missing:
            raise SetupError("Media dependencies are missing: " + ", ".join(missing))
        return installed
    except Exception:
        # Never delete a pre-existing environment. Only the replacement tree
        # created after the backup (or a brand new install) is disposable.
        if backup is not None or not original_exists:
            try:
                if VENV.is_symlink():
                    VENV.unlink()
                elif VENV.is_dir():
                    shutil.rmtree(VENV)
                elif VENV.exists():
                    VENV.unlink()
                if backup is not None:
                    backup.rename(VENV)
                    say(f"Rebuild failed; restored previous environment: {VENV}")
            except OSError as restore_error:
                raise SetupError(
                    "SmoothCast setup failed and automatic rollback also failed. "
                    f"Previous environment preserved at {backup}; "
                    f"restore it manually to {VENV}: {restore_error}"
                ) from restore_error
        raise

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap SmoothCast from Python 3.10+")
    parser.add_argument("--target", choices=("linux", "macos", "windows"), required=True)
    parser.add_argument("--check", action="store_true",
                        help="Verify only; never install or modify anything")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--install-dir", help="Install application at this location")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Accept the default install directory without prompting")
    parser.add_argument("--in-place", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    actual = {"Linux": "linux", "Darwin": "macos",
              "Windows": "windows"}.get(platform.system())
    if args.target != actual:
        parser.error(f"{args.target} setup cannot run on {platform.system()}")
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ is the initial prerequisite.")
    try:
        say(f"Operating system: {args.target}; bootstrap Python: {sys.version.split()[0]}")
        if args.in_place and args.install_dir:
            raise SetupError("--in-place and --install-dir are mutually exclusive")
        if not args.in_place:
            destination = install_location.select_directory(
                args.target, explicit=args.install_dir, yes=args.yes, check=args.check,
            )
            if destination.resolve() == ROOT.resolve():
                # The platform script may itself be run from an already installed
                # application. This is a safe repair, not a recursive copy.
                if not (ROOT / ".venv").exists():
                    raise SetupError("Use --in-place to install a source checkout in place")
                say("Repairing existing installation in place")
            else:
                install_location.validate_destination(ROOT, destination)
                child = [sys.executable, str(destination / "setup" / "bootstrap.py"),
                         "--target", args.target, "--in-place", "--yes"]
                if args.check:
                    if not (destination / "setup" / "bootstrap.py").is_file():
                        raise SetupError(f"No SmoothCast installation at {destination}")
                    checked_run([*child, "--check", "--no-shortcuts"])
                else:
                    with install_location.installed_sources(ROOT, destination):
                        checked_run([*child, *(["--no-shortcuts"] if args.no_shortcuts else [])])
                        install_location.remember_directory(args.target, destination)
                say(f"SmoothCast location: {destination}")
                return 0
        install = {"linux": install_linux, "macos": install_macos,
                   "windows": install_windows}[args.target]
        python, env = install(check=args.check)
        isolated = ensure_venv(python, env, check=args.check)
        if not args.check:
            native_runtime.save(VENV, target=args.target, native_python=python, env=env)
        if not args.check and not args.no_shortcuts:
            checked_run([str(isolated), str(ROOT / "setup" / "shortcuts.py"),
                         "--target", args.target], env=env)
        say(f"Verified Python/GTK4/libadwaita/catt/FFmpeg: {isolated}")
        if not args.check:
            say(f"Installed. Launch with: {isolated} {ROOT / 'setup' / 'launch.py'}")
        return 0
    except (SetupError, ValueError, OSError) as exc:
        print(f"[SmoothCast setup] FAILED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
