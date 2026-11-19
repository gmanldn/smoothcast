#!/usr/bin/env python3
"""Install FFmpeg in GitHub CI without depending on one slow Ubuntu mirror.

Primary path uses the signed official Ubuntu archive; bounded fallback uses
the runner's configured mirrors. Never skip actual decoder/caption tests.
No external Python dependencies. Injectable functions support offline tests.
"""
from __future__ import annotations

from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

# Keep within media-integration job's 15 minute overall budget.
ARCHIVE_UPDATE_SECONDS = 90
ARCHIVE_INSTALL_SECONDS = 360
RUNNER_MIRROR_SECONDS = 180


def ubuntu_codename(release: dict[str, str] | None = None) -> str:
    if release is None:
        release = platform.freedesktop_os_release()
    codename = release.get("VERSION_CODENAME", "")
    if not re.fullmatch(r"[a-z][a-z0-9]{2,19}", codename):
        raise RuntimeError("Cannot identify the Ubuntu release for signed FFmpeg packages")
    if release.get("ID") != "ubuntu":
        raise RuntimeError("This FFmpeg CI installer only supports Ubuntu runners")
    return codename


def official_sources(codename: str) -> str:
    """APT retains Ubuntu's signed archive verification, not remote scripts."""
    if not re.fullmatch(r"[a-z][a-z0-9]{2,19}", codename):
        raise ValueError("Invalid Ubuntu codename")
    key = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
    return (
        f"deb [signed-by={key}] https://archive.ubuntu.com/ubuntu/ "
        f"{codename} main restricted universe multiverse\n"
        f"deb [signed-by={key}] https://archive.ubuntu.com/ubuntu/ "
        f"{codename}-updates main restricted universe multiverse\n"
        f"deb [signed-by={key}] https://security.ubuntu.com/ubuntu/ "
        f"{codename}-security main restricted universe multiverse\n"
    )


def ensure_ffmpeg(
    *, which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    release: dict[str, str] | None = None,
) -> str:
    if which("ffmpeg") and which("ffprobe"):
        print("FFmpeg/ffprobe already installed; using runner binaries.", flush=True)
        return "preinstalled"

    codename = ubuntu_codename(release)
    with tempfile.TemporaryDirectory(prefix="smoothcast-ffmpeg-ci-") as tempdir:
        directory = Path(tempdir)
        # APT can use unprivileged _apt workers; allow them to traverse
        # this directory while preserving the temporary source's integrity.
        directory.chmod(0o755)
        sources = directory / "ubuntu.list"
        sources.write_text(official_sources(codename), encoding="utf-8")
        sources.chmod(0o644)
        selection = [
            "-o", f"Dir::Etc::sourcelist={sources}",
            "-o", "Dir::Etc::sourceparts=-",
            "-o", "Acquire::Retries=1",
            "-o", "Acquire::https::Timeout=25",
        ]
        try:
            print("Using official signed Ubuntu archive for FFmpeg.", flush=True)
            run(["sudo", "timeout", str(ARCHIVE_UPDATE_SECONDS),
                 "apt-get", *selection, "update"], check=True)
            run(["sudo", "timeout", str(ARCHIVE_INSTALL_SECONDS),
                 "apt-get", *selection, "install", "-y",
                 "--no-install-recommends", "ffmpeg"], check=True)
            chosen = "official-archive"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            print(
                f"::warning::Official archive unavailable ({exc}); "
                "retrying with runner apt mirrors.", flush=True,
            )
            # Fresh runner package indices still exist. Bound the last
            # attempt and avoid repeated slow mirror retries.
            run(["sudo", "timeout", str(RUNNER_MIRROR_SECONDS),
                 "apt-get", "-o", "Acquire::Retries=0",
                 "-o", "Acquire::http::Timeout=20",
                 "install", "-y", "--no-install-recommends", "ffmpeg"],
                check=True)
            chosen = "runner-mirror"

    # A command returning zero isn't enough: both executables must resolve.
    if not which("ffmpeg") or not which("ffprobe"):
        raise RuntimeError("FFmpeg package installation did not provide ffmpeg and ffprobe")
    print(f"Installed FFmpeg via {chosen}.", flush=True)
    return chosen


if __name__ == "__main__":
    try:
        ensure_ffmpeg()
    except (RuntimeError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"::error::FFmpeg CI installation failed: {exc}", file=sys.stderr)
        sys.exit(1)
