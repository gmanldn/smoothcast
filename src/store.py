"""Atomic, schema-versioned JSON store (ARCH-13, #701).

``Store(path, schema)`` replaces ad-hoc ``json.dump``/``os.replace`` pairs:
writes go to a temp file in the same directory, are fsynced, then renamed over
the target, so a crash leaves the old or the new file and never a torn one.
Reads never raise: a missing, corrupt, non-object or foreign-schema file reads
as the default, so a bad file can never block start-up.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable


class Store:
    def __init__(self, path: Path | str, schema: int = 1, *,
                 migrate: Callable[[dict, int], dict | None] | None = None) -> None:
        self.path = Path(path)
        self.schema = int(schema)
        self._migrate = migrate
        self._lock = threading.Lock()

    def read(self, default: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback = dict(default or {})
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except OSError:
            return fallback
        except ValueError:
            self._quarantine()  # unparseable: keep it for the owner, start clean
            return fallback
        if not isinstance(raw, dict):
            self._quarantine()
            return fallback
        found = raw.get("_schema", 1)
        data = {k: v for k, v in raw.items() if k != "_schema"}
        if found == self.schema:
            return data
        if self._migrate is not None and isinstance(found, int) and found < self.schema:
            try:
                migrated = self._migrate(data, found)
            except Exception:  # noqa: BLE001 - a bad migration reads as default
                return fallback
            return migrated if isinstance(migrated, dict) else fallback
        return fallback  # written by a newer or unknown schema: do not guess

    def _quarantine(self) -> None:
        """Move a corrupt file aside (never delete user data) so it is not re-read."""
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".corrupt"))
        except OSError:
            pass

    def write(self, data: dict[str, Any]) -> bool:
        """Atomically replace the file. Returns False (never raises) on I/O failure."""
        payload = json.dumps({**data, "_schema": self.schema}, indent=2, sort_keys=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Owner-only: these files hold local state, never shared data.
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                return False
        return True

    def update(self, change: Callable[[dict], None], default: dict[str, Any] | None = None) -> bool:
        """Read-modify-write under the store's lock (one process)."""
        with self._lock:
            data = self.read(default)
        change(data)
        return self.write(data)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass
