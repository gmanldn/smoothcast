"""Replace a hung or stale SmoothCast process so a launch is always consistent.

A Python process cannot relaunch its own threads; only a new process resets
them. This module stops a primary that no longer answers (or any primary when
`--fresh` is given) and then reaps every helper and stale stream file through
`startup_cleanup`. It never contacts a receiver and only signals same-user
processes whose birth time and command line are unchanged since inspection,
using the same psutil handle for the signal so PID reuse cannot redirect it.
"""
from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import sys
import time

try:  # psutil is a runtime dependency; without it we fail closed.
    import psutil
except ImportError:  # pragma: no cover - exercised through the None branch
    psutil = None  # type: ignore[assignment]

FRESH_ARG = "--fresh"


def take_flag(args: list[str]) -> tuple[bool, list[str]]:
    """Remove `--fresh` from the launch arguments; report whether it was given."""
    rest = [arg for arg in args if arg != FRESH_ARG]
    return len(rest) != len(args), rest


def stop_processes(pids: list[int], *, grace: float = 4.0,
                   process_factory: Callable[[int], object] | None = None,
                   clock: Callable[[], float] = time.monotonic,
                   sleep: Callable[[float], None] = time.sleep) -> list[int]:
    """TERM then KILL each verified process; return the PIDs that are gone."""
    factory = process_factory or (psutil.Process if psutil is not None else None)
    if factory is None:
        return []
    own = os.getpid()
    handles = []
    for pid in pids:
        if type(pid) is not int or pid <= 1 or pid == own:
            continue
        try:
            handle = factory(pid)
            handles.append((pid, handle, handle.create_time(), tuple(handle.cmdline())))
        except Exception:  # already gone or not ours to inspect
            continue

    def unchanged(handle, created, argv) -> bool:
        try:
            return (handle.is_running() and handle.create_time() == created
                    and getattr(handle, "status", lambda: "")() != "zombie"
                    and tuple(handle.cmdline()) == argv)
        except Exception:
            return False

    for _pid, handle, created, argv in handles:
        if unchanged(handle, created, argv):
            try:
                handle.terminate()
            except Exception:
                pass
    deadline = clock() + max(0.0, grace)
    while clock() < deadline and any(unchanged(h, c, a) for _p, h, c, a in handles):
        sleep(0.05)
    for _pid, handle, created, argv in handles:
        if unchanged(handle, created, argv):
            try:
                handle.kill()
            except Exception:
                pass
    sleep(0.05)
    return [pid for pid, handle, created, argv in handles
            if not unchanged(handle, created, argv)]


def reap_helpers(src_dir: Path, *, keep_streaming: bool):
    """Run the shared helper/stale-file cleanup (an explicit reset keeps nothing)."""
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import startup_cleanup
    return startup_cleanup.cleanup_before_window(keep_streaming=keep_streaming)


def reset(pids: list[int], src_dir: Path, *, keep_streaming: bool = False,
          say: Callable[[str], None] = lambda text: print(text, file=sys.stderr)) -> bool:
    """Stop `pids`, then clean helpers. True when no listed process survives."""
    if pids and psutil is None:
        say("SmoothCast: cannot verify or stop old processes without psutil; leaving them untouched.")
        return False
    gone = set(stop_processes(pids))
    survivors = [pid for pid in pids if pid not in gone and _alive(pid)]
    if survivors:
        say(f"SmoothCast: could not stop process(es) {survivors}; leaving them untouched.")
        return False
    try:
        report = reap_helpers(src_dir, keep_streaming=keep_streaming)
        say(f"SmoothCast fresh start: stopped {len(gone)} stale window(s), "
            f"{len(report.stopped)} helper(s), removed {report.files_removed} stream file(s).")
    except Exception as exc:  # cleanup trouble must never block starting
        say(f"SmoothCast fresh start: helper cleanup failed: {exc}")
    return True


def _alive(pid: int) -> bool:
    if psutil is None:
        return True  # cannot inspect: assume it survives (fail closed)
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return True
