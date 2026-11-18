"""Safely recover orphaned SmoothCast processes before the primary GTK window.

Python threads die with their interpreter, but FFmpeg/ffplay/HLS subprocesses
can survive a crash. Never signal by executable name alone: require the same
user, a SmoothCast-specific command signature and matching /proc starttime.
Keep-streaming sessions are left for normal Chromecast session adoption.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import platform
import shutil
import signal
import tempfile
import time

import streamer


@dataclass(frozen=True)
class Process:
    pid: int
    kind: str
    start_ticks: int
    argv: tuple[str, ...]


@dataclass
class CleanupReport:
    stopped: list[int] = field(default_factory=list)
    preserved: list[int] = field(default_factory=list)
    files_removed: int = 0
    temp_dirs_removed: int = 0
    errors: list[str] = field(default_factory=list)
    retained_stream: bool = False


def process_kind(argv: tuple[str, ...]) -> str | None:
    """Match only project-owned subprocesses; never a generic ffmpeg/catt."""
    if not argv:
        return None
    executable = Path(argv[0]).name
    if len(argv) >= 2 and argv[1] == str(streamer.SERVER_SCRIPT) and executable.startswith("python"):
        return "server"
    if executable == "ffmpeg":
        if "-progress" in argv and str(streamer.PROGRESS_FILE) in argv:
            return "encoder"
        if "-filter_complex" in argv and any(
            "ametadata=mode=print:file=" in arg and "cast-mon-" in arg
            for arg in argv
        ):
            return "monitor"
    if executable == "ffplay" and "SmoothCast — local playback" in argv:
        return "local"
    return None


def _start_ticks(stat_text: str) -> int:
    # /proc/<pid>/stat field 2 (comm) can contain whitespace/parentheses.
    # Fields following the final ')' start at field 3. Starttime is field 22.
    return int(stat_text.rsplit(")", 1)[1].split()[19])


def inspect_process(pid: int, proc_root: Path = Path("/proc")) -> Process | None:
    if pid <= 1 or pid == os.getpid():
        return None
    location = proc_root / str(pid)
    try:
        if location.stat().st_uid != os.getuid():
            return None
        argv = tuple(
            part.decode("utf-8", "replace")
            for part in (location / "cmdline").read_bytes().split(b"\0") if part
        )
        kind = process_kind(argv)
        if kind is None:
            return None
        start_ticks = _start_ticks((location / "stat").read_text())
        return Process(pid, kind, start_ticks, argv)
    except (OSError, ValueError, IndexError):
        return None


def discover(proc_root: Path = Path("/proc")) -> list[Process]:
    try:
        ids = [int(entry.name) for entry in proc_root.iterdir()
               if entry.name.isdecimal()]
    except OSError:
        return []
    return [process for pid in ids
            if (process := inspect_process(pid, proc_root)) is not None]


def _same_process(process: Process, proc_root: Path) -> bool:
    current = inspect_process(process.pid, proc_root)
    return bool(current and current.kind == process.kind
                and current.start_ticks == process.start_ticks
                and current.argv == process.argv)


def _stop_orphans(processes: list[Process], proc_root: Path,
                  report: CleanupReport, grace: float) -> None:
    pending = []
    for process in processes:
        if not _same_process(process, proc_root):
            continue
        try:
            os.kill(process.pid, signal.SIGTERM)
            pending.append(process)
            report.stopped.append(process.pid)
        except OSError as exc:
            report.errors.append(f"SIGTERM {process.pid}: {exc}")
    deadline = time.monotonic() + max(0.0, grace)
    while pending and time.monotonic() < deadline:
        pending = [p for p in pending if _same_process(p, proc_root)]
        if pending:
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    for process in pending:
        # Recheck identity immediately before escalation; PIDs may be reused.
        if _same_process(process, proc_root):
            try:
                os.kill(process.pid, signal.SIGKILL)
            except OSError as exc:
                report.errors.append(f"SIGKILL {process.pid}: {exc}")


def cleanup_before_window(
    *, keep_streaming: bool, proc_root: Path = Path("/proc"),
    temp_root: Path | None = None, grace: float = 1.0,
) -> CleanupReport:
    """Run exactly once in the primary GApplication startup, before the UI.

    Never send a stop command to a Chromecast or touch other users' processes.
    Preserve a session explicitly kept streaming so it can be re-adopted.
    """
    report = CleanupReport()
    # /proc and UID-owned process inspection are Linux-specific. Never try
    # scanning/killing helpers on macOS or Windows using a Linux PID model.
    if platform.system() != "Linux":
        return report
    processes = discover(proc_root)
    state = streamer.load_session()
    by_pid = {p.pid: p for p in processes}
    saved_server = by_pid.get(state.server_pid) if state else None
    has_server = bool(saved_server and saved_server.kind == "server")
    # An already-running HLS server may have been reused, without recording
    # its PID on the subsequent Session instance.
    if state and state.mode == "transcode" and not has_server:
        has_server = any(p.kind == "server" for p in processes)
    report.retained_stream = bool(keep_streaming and state and (
        state.mode == "direct" or
        (state.mode == "transcode" and has_server)
    ))
    protected: set[int] = set()
    if report.retained_stream and state and state.mode == "transcode":
        protected.update(p.pid for p in processes if p.kind == "server")
        if (saved_encoder := by_pid.get(state.ffmpeg_pid)) and saved_encoder.kind == "encoder":
            protected.add(saved_encoder.pid)
    report.preserved = sorted(protected)
    _stop_orphans([p for p in processes if p.pid not in protected],
                  proc_root, report, grace)

    if not report.retained_stream or (state is not None and state.mode == "direct"):
        # A retained direct cast needs session.json, but none of the obsolete
        # HLS artefacts. Leave diagnostic logs and all user media untouched.
        root = streamer.ROOT
        files = [streamer.PROGRESS_FILE, root / streamer.HLS_NAME,
                 *root.glob(streamer.SEGMENT_GLOB)]
        if not report.retained_stream:
            files.insert(0, streamer.SESSION_FILE)
        for file in files:
            try:
                if file.is_file():
                    file.unlink()
                    report.files_removed += 1
            except OSError as exc:
                report.errors.append(f"cleanup {file.name}: {exc}")

    # A crash seconds before startup must not leave temporary meter debris.
    # Only remove our own directories, never those referenced by a still-live
    # monitor; never follow symlinks.
    scratch_root = temp_root if temp_root is not None else Path(tempfile.gettempdir())
    surviving = [p for p in processes if p.kind == "monitor"
                 and p.pid not in report.stopped]
    try:
        candidates = list(scratch_root.glob("cast-mon-*"))[:256]
    except OSError:
        candidates = []
    for folder in candidates:
        try:
            stat = folder.lstat()
            if (not folder.is_dir() or folder.is_symlink()
                    or stat.st_uid != os.getuid()):
                continue
            if any(str(folder) in " ".join(p.argv) for p in surviving):
                continue
            shutil.rmtree(folder)
            report.temp_dirs_removed += 1
        except OSError as exc:
            report.errors.append(f"cleanup {folder.name}: {exc}")
    return report
