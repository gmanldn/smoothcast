"""Local playback: play a file on this machine with ffplay before casting.

ffplay is part of ffmpeg (already a hard dependency) and opens its own local
window with native playback controls.  The app tracks the process so local
playback and casting never run at the same time.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LocalPlayback:
    """Track a locally playing ffplay process for the selected file."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    @property
    def player(self) -> str | None:
        return shutil.which("ffplay")

    def is_active(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def available(self) -> bool:
        return self.player is not None

    def start(self, path: str | Path) -> None:
        """Start playing *path* locally.

        Raises FileNotFoundError when ffplay is missing or the file does not
        exist.  A second start while already playing is a no-op.
        """
        if self.is_active():
            return
        if not self.available():
            raise FileNotFoundError("ffplay is not installed (part of ffmpeg)")
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"no such file: {file_path}")
        self.proc = subprocess.Popen(
            [
                self.player,
                "-loglevel",
                "warning",
                "-window_title",
                "SmoothCast — local playback",
                str(file_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def stop(self) -> None:
        """Stop and reap ffplay; do not leave a zombie after forced termination."""
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass  # The process may have exited between checks.
            try:
                proc.wait(timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                pass
        finally:
            self.proc = None
