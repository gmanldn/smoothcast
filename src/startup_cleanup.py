"""Safely recover orphaned SmoothCast processes before the primary GTK window.

Python threads die with their interpreter, but FFmpeg/ffplay/HLS subprocesses
can survive a crash. Never signal by executable name alone: require the same
user, a SmoothCast-specific command signature and matching process birth time.
Keep-streaming sessions are left for normal Chromecast session adoption.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import platform
import re
import shutil
import signal
import tempfile
import time

import cache_policy
import streamer
import process_identity


@dataclass(frozen=True)
class Process:
    pid: int
    kind: str
    start_ticks: int
    argv: tuple[str, ...]


@dataclass
class CleanupReport:
    stopped: list[int] = field(default_factory=list)
    unresolved: list[int] = field(default_factory=list)
    preserved: list[int] = field(default_factory=list)
    files_removed: int = 0
    temp_dirs_removed: int = 0
    errors: list[str] = field(default_factory=list)
    retained_stream: bool = False


def process_kind(argv: tuple[str, ...]) -> str | None:
    """Only helper roles with project-specific markers, not generic catt."""
    kind = process_identity.role_of(
        argv, server_script=str(streamer.SERVER_SCRIPT),
        progress_file=str(streamer.PROGRESS_FILE),
    )
    return kind if kind in {"server", "encoder", "monitor", "local"} else None

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


def inspect_portable(pid: int) -> Process | None:
    """Cross-platform same-user process snapshot, with OS birth time."""
    identity = process_identity.snapshot(pid)
    if identity is None:
        return None
    kind = process_kind(identity.argv)
    if kind is None:
        return None
    return Process(identity.pid, kind, round(identity.created_at * 1_000_000),
                   identity.argv)


def discover_portable() -> list[Process]:
    """Enumerate only same-user helpers on macOS/Windows, never by name alone."""
    if process_identity.psutil is None:
        return []
    try:
        result = []
        for candidate in process_identity.psutil.process_iter():
            if (info := inspect_portable(candidate.pid)) is not None:
                result.append(info)
        return result
    except Exception:  # Permission failures cannot authorise termination.
        return []


def discover(proc_root: Path = Path("/proc")) -> list[Process]:
    if platform.system() != "Linux":
        return discover_portable()
    try:
        ids = [int(entry.name) for entry in proc_root.iterdir()
               if entry.name.isdecimal()]
    except OSError:
        return []
    return [process for pid in ids
            if (process := inspect_process(pid, proc_root)) is not None]


def _same_process(process: Process, proc_root: Path) -> bool:
    current = (inspect_process(process.pid, proc_root)
               if platform.system() == "Linux" else inspect_portable(process.pid))
    return bool(current and current.kind == process.kind
                and current.start_ticks == process.start_ticks
                and current.argv == process.argv)


def _stop_orphans(processes: list[Process], proc_root: Path,
                  report: CleanupReport, grace: float) -> None:
    """Check start time and exact argv immediately before each signal."""
    def send(process: Process, force: bool) -> bool:
        if platform.system() != "Linux":
            # os.kill(pid, SIGTERM) on Windows is unsafe (TerminateProcess).
            return process_identity.signal_verified(
                process.pid, process.kind,
                expected_start=process.start_ticks / 1_000_000,
                expected_argv=process.argv,
                server_script=str(streamer.SERVER_SCRIPT),
                progress_file=str(streamer.PROGRESS_FILE),
                force=force,
            )
        try:
            os.kill(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            return True
        except OSError as exc:
            report.errors.append(f"signal {process.pid}: {exc}")
            return False

    def wait_for_exit(pending: list[Process], timeout: float) -> list[Process]:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = []
            for process in pending:
                if _same_process(process, proc_root):
                    remaining.append(process)
                else:
                    report.stopped.append(process.pid)
            delay = deadline - time.monotonic()
            if not remaining or delay <= 0:
                return remaining
            pending = remaining
            time.sleep(min(0.05, delay))

    pending = []
    for process in processes:
        if _same_process(process, proc_root):
            send(process, False)
            pending.append(process)
    pending = wait_for_exit(pending, grace)
    for process in pending:
        if _same_process(process, proc_root):
            send(process, True)
    for process in wait_for_exit(pending, min(grace, 0.25)):
        report.unresolved.append(process.pid)
        report.errors.append(f"{process.kind} helper {process.pid} still running after cleanup")


def cleanup_before_window(
    *, keep_streaming: bool, proc_root: Path = Path("/proc"),
    temp_root: Path | None = None, grace: float = 1.0,
) -> CleanupReport:
    """Run exactly once in the primary GApplication startup, before the UI.

    Never send a stop command to a Chromecast or touch other users' processes.
    Preserve a session explicitly kept streaming so it can be re-adopted.
    """
    report = CleanupReport()
    # Windows/macOS require psutil. Without it, fail closed; never probe or
    # signal arbitrary saved PIDs with Windows os.kill semantics.
    if platform.system() != "Linux" and process_identity.psutil is None:
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
        (state.mode == "transcode" and
         (has_server or platform.system() != "Linux"))
    ))
    # On macOS/Windows a missed/inaccessible process inventory cannot prove
    # that the receiver has stopped consuming this HLS playlist. Fail safe:
    # preserve kept-stream media rather than deleting it on uncertain recovery.
    protected: set[int] = set()
    if report.retained_stream and state and state.mode == "transcode":
        protected.update(p.pid for p in processes if p.kind == "server")
        if (saved_encoder := by_pid.get(state.ffmpeg_pid)) and saved_encoder.kind == "encoder":
            protected.add(saved_encoder.pid)
    report.preserved = sorted(protected)
    _stop_orphans([p for p in processes if p.pid not in protected],
                  proc_root, report, grace)

    hls_busy = any(by_pid[pid].kind in {"server", "encoder"} for pid in report.unresolved)
    if not hls_busy and (not report.retained_stream or (state and state.mode == "direct")):
        # A retained direct cast needs session.json, but none of the obsolete
        # HLS artefacts. Leave diagnostic logs and all user media untouched.
        root = streamer.ROOT
        files = [streamer.PROGRESS_FILE, root / streamer.HLS_NAME,
                 *root.glob(streamer.SEGMENT_GLOB), *root.glob("movie-*.m3u8")]
        files.extend(path for path in root.glob("segment-*.m4s")
                     if re.fullmatch(r"segment-[0-9a-f]{32}-[0-9]+\.m4s", path.name))
        files.extend(path for path in root.glob("init-*.mp4")
                     if re.fullmatch(r"init-[0-9a-f]{32}\.mp4", path.name))
        if not report.retained_stream:
            files.insert(0, streamer.SESSION_FILE)
            # Never remove the captions from a deliberately retained cast;
            # otherwise remove only SmoothCast's own staged names, not user SRTs.
            files.extend([root / "receiver_subs.srt",
                          *(root / f"burned_subs{ext}" for ext in streamer.SUBTITLE_EXTS)])
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
    safe_windows_temp = (
        platform.system() != "Windows"
        or cache_policy.current_user_temp_root(scratch_root)
    )
    surviving = [p for p in processes if p.kind == "monitor"
                 and p.pid not in report.stopped]
    try:
        # DLNA conversions leave a multi-GB scratch MP4 if the app is killed;
        # sweep those too, but only once old enough not to be in preparation.
        candidates = [(f, 0.0) for f in list(scratch_root.glob("cast-mon-*"))[:256]]
        candidates += [(f, cache_policy.MIN_STALE_AGE_SECONDS) for f in
                       list(scratch_root.glob(cache_policy.SCRATCH_PREFIX + "*"))[:256]]
    except OSError:
        candidates = []
    for folder, min_age in candidates:
        try:
            stat = folder.lstat()
            if not folder.is_dir() or folder.is_symlink():
                continue
            if platform.system() == "Windows":
                if not safe_windows_temp:
                    continue
            elif stat.st_uid != os.getuid():
                continue
            if min_age and time.time() - stat.st_mtime < min_age:
                continue
            if any(str(folder) in " ".join(p.argv) for p in surviving):
                continue
            # Age is insufficient proof: a live conversion does not update its
            # parent directory's mtime while FFmpeg writes movie.mp4.
            # Claim a kernel lease and hold it across rmtree. Legacy scratch
            # without a verifiable lease stays untouched (fail closed).
            lease = cache_policy.claim_abandoned_scratch(folder) if min_age else None
            if min_age and lease is None:
                continue
            try:
                if lease is not None and cache_policy.msvcrt is not None:
                    # The Windows CRT handle disallows delete sharing. Release
                    # it only after claiming the age-qualified unique directory,
                    # then atomically rename before recursive removal.
                    lease.close()
                    tombstone = folder.with_name(folder.name + ".smoothcast-reap")
                    folder.rename(tombstone)
                    shutil.rmtree(tombstone)
                else:
                    shutil.rmtree(folder)
                report.temp_dirs_removed += 1
            finally:
                if lease is not None:
                    lease.close()
        except OSError as exc:
            report.errors.append(f"cleanup {folder.name}: {exc}")
    return report
