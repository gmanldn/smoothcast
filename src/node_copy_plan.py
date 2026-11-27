"""Receiver-side state for a "Send a copy" between paired nodes (#357). Pure bookkeeping.

``Incoming`` tracks one transfer: consent, quota, contiguous resume offset,
chunk validation, and final size+digest verification before the caller does the
atomic rename. A duplicate (same digest already saved) is detected up front.
No file IO happens here, so the caller keeps playback and disk work separate.
"""
from __future__ import annotations

import hashlib

CHUNK_MAX = 4 * 1024 * 1024
QUEUED, RECEIVING, VERIFYING, DONE, FAILED, CANCELLED = "queued", "receiving", "verifying", "done", "failed", "cancelled"


class Incoming:
    def __init__(self, transfer_id: str, size: int, sha256: str, *, consent: bool, free_bytes: int,
                 reserve_bytes: int = 512 * 1024 * 1024, known_digests: set[str] | None = None) -> None:
        self.id, self.size, self.sha256 = transfer_id, size, sha256.lower()
        self.offset = 0
        self.state = QUEUED
        self.reason = ""
        self._hash = hashlib.sha256()
        if not consent:
            self._fail("The receiving computer has not allowed copies from this device.")
        elif not isinstance(size, int) or size <= 0 or len(self.sha256) != 64:
            self._fail("Invalid transfer details.")
        elif size + reserve_bytes > free_bytes:
            self._fail("Not enough free space on the receiving computer.")
        elif known_digests and self.sha256 in known_digests:
            self.state, self.reason = DONE, "Already saved on this computer."

    def _fail(self, why: str) -> None:
        self.state, self.reason = FAILED, why

    def resume_from(self) -> int:
        """Where the sender should continue: always the verified contiguous offset."""
        return self.offset

    def chunk(self, offset: int, data: bytes) -> tuple[bool, str]:
        if self.state not in (QUEUED, RECEIVING):
            return False, "Transfer is not active."
        if offset != self.offset:
            return False, f"Expected offset {self.offset}."        # sender re-syncs; nothing is skipped
        if not data or len(data) > CHUNK_MAX or self.offset + len(data) > self.size:
            return False, "Bad chunk."
        self._hash.update(data)
        self.offset += len(data)
        self.state = RECEIVING
        return True, ""

    def progress(self) -> float:
        return self.offset / self.size if isinstance(self.size, int) and self.size > 0 else 0.0

    def finish(self) -> tuple[bool, str]:
        """True only when size and digest match; the caller then renames atomically."""
        if self.state != RECEIVING:
            return False, self.reason or "Nothing received."
        self.state = VERIFYING
        if self.offset != self.size:
            self._fail("The copy is incomplete.")
        elif self._hash.hexdigest() != self.sha256:
            self._fail("The copy didn't match the original and was discarded.")
        else:
            self.state = DONE
            return True, ""
        return False, self.reason

    def cancel(self, why: str = "Cancelled.") -> None:
        if self.state in (QUEUED, RECEIVING):
            self.state, self.reason = CANCELLED, why

    def revoke(self) -> None:
        if self.state in (QUEUED, RECEIVING):
            self._fail("Permission was withdrawn. The partial copy was discarded.")

    def restart_after_crash(self, verified_prefix: bytes) -> None:
        """Rebuild from a persisted partial file: re-hash what's on disk, resume there."""
        self._hash, self.offset = hashlib.sha256(verified_prefix), len(verified_prefix)
        self.state = RECEIVING if self.offset else QUEUED
