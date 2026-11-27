"""Per-attempt cast artifacts and redaction (ARCH-10, #698 first slice).

Each cast attempt gets its own folder under ``<root>/attempts/`` holding argv,
the ffmpeg stderr tail, the plan reason, timings and the outcome, so a retry
never overwrites an earlier attempt. Only the newest ``keep`` folders survive and
each file is size-capped. ``redact`` strips media paths and tokens before any
bundle leaves the machine. Stdlib only; never raises into the caller.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

KEEP = 20
MAX_FILE = 64 * 1024

_TOKEN = re.compile(r"(?i)\b(token|csrf|pin|authorization|cookie|secret|password)(=|:)\s*\S+")
_PATH = re.compile(r"(?:(?<=\s)|^|(?<=[=\"']))/(?:[^\s\"':]+/)*[^\s\"':]+")
_WIN = re.compile(r"\b[A-Za-z]:\\(?:[^\s\\\"']+\\)*[^\s\\\"']+")


def redact(text: str) -> str:
    """Remove secrets and filesystem paths (media names can identify people)."""
    text = _TOKEN.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)
    text = _WIN.sub("<path>", text)
    return _PATH.sub("<path>", text)


def _active_trace_id() -> str | None:
    try:
        import command_trace
        return command_trace.current_id()
    except Exception:  # noqa: BLE001 - tracing must never break an attempt
        return None


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


class Attempt:
    def __init__(self, folder: Path, correlation_id: str):
        self.folder, self.correlation_id = folder, correlation_id
        self._started = time.monotonic()

    def write(self, name: str, content: str | bytes) -> None:
        data = content.encode("utf-8", "replace") if isinstance(content, str) else content
        try:
            (self.folder / name).write_bytes(data[-MAX_FILE:])   # keep the tail: that is the failure
        except OSError:
            pass

    def finish(self, outcome: str, reason: str = "") -> None:
        self.write("outcome.json", json.dumps({
            "correlation_id": self.correlation_id, "outcome": outcome, "reason": reason,
            "seconds": round(time.monotonic() - self._started, 3)}))


def begin(root: Path, *, argv: list[str] | None = None, plan_reason: str = "",
          correlation_id: str | None = None, keep: int = KEEP) -> Attempt:
    """Create a fresh attempt folder and prune old ones."""
    # Default to the active command trace so an attempt folder matches its trace (#698).
    cid = correlation_id or _active_trace_id() or new_correlation_id()
    cid = re.sub(r"[^A-Za-z0-9_-]", "", str(cid))[:32] or new_correlation_id()
    base = Path(root) / "attempts"
    stamp = f"{int(time.time() * 1000):013d}-{cid}"
    folder = base / stamp
    try:
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
    except OSError:
        pass
    attempt = Attempt(folder, cid)
    attempt.write("argv.json", json.dumps(argv or []))
    attempt.write("plan.txt", plan_reason)
    _prune(base, keep)
    return attempt


def _prune(base: Path, keep: int) -> None:
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return
    for old in folders[:-keep] if keep > 0 else folders:
        shutil.rmtree(old, ignore_errors=True)


def bundle(root: Path) -> dict[str, dict[str, str]]:
    """Redacted view of the retained attempts, ready to write out on user request."""
    out: dict[str, dict[str, str]] = {}
    base = Path(root) / "attempts"
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return out
    for folder in folders:
        files = {}
        for item in sorted(folder.iterdir()):
            try:
                files[item.name] = redact(item.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        out[folder.name] = files
    return out
