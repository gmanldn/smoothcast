"""Verified, per-user process identities for orphan recovery across operating systems.

A PID or executable name alone NEVER authorises a signal. psutil is used only
when installed; without it, restored PID termination fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import time

import streamer_generation

try:
    import psutil
except ImportError:  # Source-only portable tests need not install runtime deps.
    psutil = None


@dataclass(frozen=True)
class Identity:
    pid: int
    created_at: float
    argv: tuple[str, ...]
    username: str


def executable_name(text: str) -> str:
    """Handle both POSIX paths and Windows drive/backslash paths."""
    return text.replace("\\", "/").rsplit("/", 1)[-1].lower()


def role_of(argv: tuple[str, ...], *, server_script: str, progress_file: str) -> str | None:
    """Strict project-specific markers, not generic executable-name matching."""
    if not argv:
        return None
    executable = executable_name(argv[0])
    cache_root = progress_file.replace("\\", "/").rpartition("/")[0]
    if ((len(argv) >= 2
         and (argv[1] == server_script or streamer_generation.is_frozen_worker(
             argv[1], cache_root=cache_root))
         and executable.startswith(("python", "smoothcast")))
            or (executable.startswith("smoothcast")
                and "--_smoothcast-hls-server" in argv)):
        return "server"
    if executable in {"ffmpeg", "ffmpeg.exe"}:
        if "-progress" in argv:
            index = argv.index("-progress")
            if index + 1 < len(argv) and argv[index + 1] == progress_file:
                return "encoder"
        if "-filter_complex" in argv and any(
            "ametadata=mode=print:file=" in part and "cast-mon-" in part
            for part in argv
        ):
            return "monitor"
    if (executable in {"ffplay", "ffplay.exe"}
            and "SmoothCast — local playback" in argv):
        return "local"
    if ("-d" in argv and "cast" in argv
            and (any(executable_name(arg) in {"catt", "catt.exe"}
                     for arg in argv[:2])
                 or (executable.startswith("smoothcast")
                     and "--_smoothcast-catt" in argv))):
        return "caster"
    return None


def snapshot(pid: int | None) -> Identity | None:
    """Inspect command line, birth time and current-user ownership atomically enough
    to reject stale PIDs; a failed read never grants ownership.
    """
    if (psutil is None or type(pid) is not int or pid <= 1
            or pid == os.getpid()):
        return None
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            argv = tuple(process.cmdline())
            started = float(process.create_time())
            owner = process.username()
        user = psutil.Process(os.getpid()).username()
        if (not argv or not isinstance(owner, str) or owner != user
                or not math.isfinite(started) or started <= 0):
            return None
        return Identity(pid, started, argv, owner)
    except Exception:  # AccessDenied, NoSuchProcess, zombie, platform API error.
        return None


def start_time(pid: int | None) -> float:
    identity = snapshot(pid)
    return identity.created_at if identity else 0.0


def matches(
    identity: Identity | None, role: str, *, expected_start: float | None = None,
    server_script: str, progress_file: str,
    expected_argv: tuple[str, ...] | None = None,
) -> bool:
    if identity is None:
        return False
    if role_of(identity.argv, server_script=server_script,
               progress_file=progress_file) != role:
        return False
    if expected_argv is not None and identity.argv != expected_argv:
        return False
    if expected_start is not None:
        try:
            expected = float(expected_start)
        except (TypeError, ValueError, OverflowError):
            return False
        if (not math.isfinite(expected) or expected <= 0
                or abs(identity.created_at - expected) > 0.01):
            return False
    return True


def signal_verified(
    pid: int, role: str, *, expected_start: float,
    expected_argv: tuple[str, ...] | None = None,
    server_script: str, progress_file: str, force: bool = False,
) -> bool:
    """Check birth time, owner and *unchanged* argv directly before psutil signal.

    The same psutil Process object whose create_time was read handles the
    signal, so psutil's own PID-reuse guard also applies.
    """
    if psutil is None or type(pid) is not int or pid <= 1:
        return False
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            current = Identity(
                pid, float(process.create_time()), tuple(process.cmdline()),
                process.username(),
            )
        if current.username != psutil.Process(os.getpid()).username():
            return False
        if not matches(current, role, expected_start=expected_start,
                       expected_argv=expected_argv,
                       server_script=server_script, progress_file=progress_file):
            return False
        if force:
            process.kill()
        else:
            process.terminate()
        return True
    except Exception:
        return False


def stop_verified(
    pid: int | None, role: str, *, expected_start: float | None,
    server_script: str, progress_file: str, grace: float = 3.0,
) -> None:
    """Bounded TERM/KILL of a verified current-user process; no signal on guess."""
    identity = snapshot(pid)
    if not matches(identity, role, expected_start=expected_start,
                   server_script=server_script, progress_file=progress_file):
        return
    assert identity is not None
    kwargs = dict(expected_start=identity.created_at, expected_argv=identity.argv,
                  server_script=server_script, progress_file=progress_file)
    if not signal_verified(identity.pid, role, **kwargs):
        return
    deadline = time.monotonic() + max(0.0, grace)
    while time.monotonic() < deadline:
        now = snapshot(identity.pid)
        if not matches(now, role, **kwargs):
            return
        time.sleep(min(0.15, max(0.0, deadline - time.monotonic())))
    signal_verified(identity.pid, role, force=True, **kwargs)
