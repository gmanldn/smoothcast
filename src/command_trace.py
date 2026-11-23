"""Bounded, privacy-safe command timing across portal, GTK and receiver workers.

Trace identifiers are opaque. Untrusted client IDs are HMACed, never exported;
media titles, file paths, device names, payloads and exception strings are not
stored. The ring is deliberately memory-only and does not start background IO.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import hmac
import re
import secrets
import threading
import time
from typing import Callable, Iterator

MAX_TRACES = 96
MAX_STAGES = 24
MAX_EXPORT = 32
_ID_KEY = secrets.token_bytes(32)
_ALLOWED_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_STAGE_NAMES = frozenset({
    "received", "fenced", "dispatched", "worker_queued", "receiver_call",
    "receiver_ack", "receiver_failed", "receiver_confirmed", "unconfirmed",
    "rejected", "completed", "replayed", "status_observed",
})
_LOCK = threading.RLock()
_RECORDS: OrderedDict[str, Trace] = OrderedDict()
_ACTIVE: ContextVar[Trace | None] = ContextVar("smoothcast_command_trace", default=None)


def _label(value: str) -> str:
    return value if isinstance(value, str) and _ALLOWED_NAME.fullmatch(value) else "other"


@dataclass
class Trace:
    id: str
    source: str
    action: str
    started: float = field(default_factory=time.monotonic)
    stages: list[dict] = field(default_factory=list)

    def mark(self, name: str, *, code: int | None = None) -> None:
        if name not in _STAGE_NAMES:
            return
        elapsed = max(0, min(3_600_000, round((time.monotonic() - self.started) * 1000)))
        event: dict = {"stage": name, "elapsed_ms": elapsed}
        if type(code) is int and 0 <= code <= 999:
            event["code"] = code
        with _LOCK:
            self.stages.append(event)
            if len(self.stages) > MAX_STAGES:
                del self.stages[:len(self.stages) - MAX_STAGES]


def current_id() -> str | None:
    record = _ACTIVE.get()
    return record.id if record is not None else None


def stage(name: str, *, code: int | None = None) -> None:
    record = _ACTIVE.get()
    if record is not None:
        record.mark(name, code=code)


@contextmanager
def scope(source: str, action: str, *, command_id: str | None = None,
          client_id: str | None = None) -> Iterator[Trace]:
    """Keep a single identity for duplicate commands and nested operations."""
    active = _ACTIVE.get()
    if active is not None:
        yield active
        return
    if command_id is not None and client_id is not None:
        digest = hmac.new(_ID_KEY, (client_id + "\0" + command_id).encode("utf-8"),
                          hashlib.sha256).hexdigest()[:24]
    else:
        digest = secrets.token_hex(12)
    with _LOCK:
        record = _RECORDS.get(digest)
        if record is None:
            record = Trace(digest, _label(source), _label(action))
            _RECORDS[digest] = record
        else:
            _RECORDS.move_to_end(digest)
        while len(_RECORDS) > MAX_TRACES:
            _RECORDS.popitem(last=False)
    token = _ACTIVE.set(record)
    record.mark("replayed" if record.stages else "received")
    try:
        yield record
    except Exception as exc:
        status = getattr(exc, "status", None)
        record.mark("rejected", code=status if type(status) is int else None)
        raise
    finally:
        record.mark("completed")
        _ACTIVE.reset(token)


def propagate(callback: Callable | None) -> Callable | None:
    """Explicitly preserve the current trace through a worker/GLib handoff."""
    if callback is None or _ACTIVE.get() is None:
        return callback
    context = copy_context()

    @wraps(callback)
    def wrapped(*args, **kwargs):
        return context.copy().run(callback, *args, **kwargs)

    return wrapped


def recent(limit: int = MAX_EXPORT) -> list[dict]:
    """Return detached, bounded, data-minimised traces for support bundles."""
    bounded = min(MAX_EXPORT, max(0, limit)) if type(limit) is int else 0
    with _LOCK:
        return [{"id": rec.id, "source": rec.source, "action": rec.action,
                 "stages": [dict(e) for e in rec.stages]}
                for rec in list(_RECORDS.values())[-bounded:]] if bounded else []


def traced(source: str, action: str):
    """Decorate a desktop handler without disturbing an existing portal trace."""
    def decorator(callback: Callable) -> Callable:
        @wraps(callback)
        def wrapped(*args, **kwargs):
            with scope(source, action):
                return callback(*args, **kwargs)
        return wrapped
    return decorator
