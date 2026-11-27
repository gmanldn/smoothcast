"""Growing-file reader for streaming ingest (#572): upload thread appends, playback thread reads up to a watermark.

Condition-based wake-ups (no busy loop), bounded reads, honest EOF, cancellation, stall and source-identity checks.
Also ``mp4_early_ready``: bounded top-level atom scan that refuses non-faststart MP4.
"""
from __future__ import annotations

import os
import struct
import threading
import time

MIN_READ, MAX_READ = 256 * 1024, 8 * 1024 * 1024


class Cancelled(Exception):
    pass


class Stalled(Exception):
    """Source device went quiet longer than the bounded wait."""


class Superseded(Exception):
    """The source file changed or a newer session replaced this one."""


class Growing:
    def __init__(self, path: str, total: int, identity: str, *, clock=time.monotonic) -> None:
        self.path, self.total, self.identity, self.clock = path, int(total), identity, clock
        self.mark = 0
        self.cancelled = False
        self.superseded = False
        self.complete = False
        self.last_write = clock()
        self.cv = threading.Condition()
        open(path, "ab").close()

    # ---- producer
    def append(self, data: bytes, offset: int, identity: str) -> int:
        """Append at the exact watermark; duplicate/overlapping retries are trimmed, gaps refused."""
        with self.cv:
            if identity != self.identity:
                self.superseded = True
                self.cv.notify_all()
                raise Superseded("source changed")
            if self.cancelled:
                raise Cancelled()
            if offset > self.mark:
                raise ValueError(f"gap: have {self.mark}, got offset {offset}")
            skip = self.mark - offset
            data = data[skip:]
            if self.mark + len(data) > self.total:
                raise ValueError("past declared size")
            if data:
                with open(self.path, "r+b") as f:
                    f.seek(self.mark)
                    f.write(data)
                self.mark += len(data)
            self.last_write = self.clock()
            self.complete = self.mark == self.total
            self.cv.notify_all()
            return self.mark

    def cancel(self) -> None:
        with self.cv:
            self.cancelled = True
            self.cv.notify_all()

    # ---- consumer
    def read(self, pos: int, n: int, *, wait: float = 10.0, stall: float = 30.0) -> bytes:
        """Block until bytes at ``pos`` exist, up to ``wait`` per call. b'' only at the true end of the file.
        Raises Stalled when the source has been silent for ``stall`` seconds, so the UI can say 'Waiting for source device'."""
        n = max(1, min(int(n), MAX_READ))
        deadline = self.clock() + wait
        with self.cv:
            while True:
                if self.cancelled:
                    raise Cancelled()
                if self.superseded:
                    raise Superseded("source changed")
                if pos >= self.total:
                    return b""
                if pos < self.mark:
                    n = min(n, self.mark - pos)
                    break
                if self.clock() - self.last_write >= stall:
                    raise Stalled()
                left = deadline - self.clock()
                if left <= 0:
                    raise Stalled()
                self.cv.wait(min(left, 0.25))
        with open(self.path, "rb") as f:
            f.seek(pos)
            return f.read(n)

    def seekable_to(self, pos: int) -> bool:
        """Honest seek: only within what has arrived (or after completion)."""
        return self.complete or 0 <= pos < self.mark

    def state(self) -> dict:
        return {"received": self.mark, "total": self.total, "complete": self.complete,
                "waiting_for_source": not self.complete and self.clock() - self.last_write > 10}


def mp4_early_ready(head: bytes, have: int, limit: int = 16 * 1024 * 1024) -> str:
    """'ready' when moov precedes mdat inside the bytes received; 'wait' if undecided; 'finish_first' otherwise."""
    pos = 0
    while pos + 8 <= len(head) and pos < limit:
        size, kind = struct.unpack(">I4s", head[pos:pos + 8])
        if size == 1:
            if pos + 16 > len(head):
                return "wait"
            size = struct.unpack(">Q", head[pos + 8:pos + 16])[0]
        elif size == 0:
            size = None
        if kind == b"moov":
            return "ready" if size is not None and pos + size <= have else "wait"
        if kind == b"mdat":
            return "finish_first"
        if size is None or size < 8:
            return "finish_first"
        pos += size
    return "wait" if have < limit else "finish_first"


def cleanup(g: Growing, consumers: int) -> bool:
    """Remove the file only after active consumers release it."""
    if consumers > 0:
        return False
    try:
        os.unlink(g.path)
    except FileNotFoundError:
        pass
    return True


def recover(path: str, total: int, mark_known: int) -> str:
    """After restart a partial file is never republished as complete."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    return "complete" if size == total and mark_known == total else "partial"
