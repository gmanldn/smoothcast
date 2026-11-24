"""Durable, crash-safe storage for the acquisition assignment ledger (#589).

Pure file I/O around ``AssignmentLedger.snapshot()/restore()``: owner-only
file, temp + fsync + atomic replace + directory fsync, bounded size, strict
validation on load. A crash at any point leaves the previous complete snapshot
or the new one, never a torn file. ``restore`` already marks every running job
ambiguous, so a reboot can never cause a second download by itself.

An unreadable file is never silently replaced with an empty ledger (that would
forget which node may still be downloading): ``load`` raises, and
``load_or_quarantine`` moves the bad file aside and starts empty only when the
caller explicitly asks for that.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from typing import Callable

from mesh_acquisition_assignment import AssignmentLedger, LedgerError

MAX_BYTES = 4 << 20
NAME = "acquisition-ledger.json"


def _noop(_step: str) -> None:
    """Crash-injection point for tests."""


class LedgerStore:
    def __init__(self, directory: Path, *, hook: Callable[[str], None] = _noop) -> None:
        self.directory = Path(directory)
        self.path = self.directory / NAME
        self._hook = hook

    def save(self, ledger: AssignmentLedger) -> None:
        data = json.dumps(ledger.snapshot(), sort_keys=True).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise LedgerError("ledger is too large to persist")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.directory / f".{NAME}.{secrets.token_hex(6)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            with os.fdopen(os.open(tmp, flags, 0o600), "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            self._hook("tmp_written")
            os.replace(tmp, self.path)
            self._hook("replaced")
            self._sync_directory()
        except OSError as exc:
            raise LedgerError(f"cannot persist ledger: {exc.strerror or exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)

    def _sync_directory(self) -> None:
        if os.name == "nt":
            return
        fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def load(self, **kwargs) -> AssignmentLedger | None:
        """The stored ledger, None if never saved. Raises on any damage."""
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(self.path, flags), "rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LedgerError(f"cannot read ledger: {exc.strerror or exc}") from exc
        if len(raw) > MAX_BYTES:
            raise LedgerError("ledger file is oversized")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise LedgerError("ledger file is corrupt") from None
        return AssignmentLedger.restore(data, **kwargs)

    def load_or_quarantine(self, **kwargs) -> tuple[AssignmentLedger, str | None]:
        """Explicit recovery: keep a damaged file for inspection, start empty."""
        try:
            ledger = self.load(**kwargs)
        except LedgerError as exc:
            aside = self.directory / f"{NAME}.corrupt-{secrets.token_hex(4)}"
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            return AssignmentLedger(**kwargs), str(exc)
        return ledger or AssignmentLedger(**kwargs), None
