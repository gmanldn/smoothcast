"""Explicit node pairing and scoped trust (#358). Pure core; JSON persistence is atomic.

Durable peer identity is a public-key fingerprint, never an IP or room PIN.
Pairing shows both hosts the same short authentication string (``sas``) derived
from both fingerprints; the host approves only after confirming it out of band.
Scopes (media_read, incoming_copy, receiver_control) are independently
revocable. ``authorise`` checks the peer, scope, pinned endpoint and a
single-use nonce, so replays, spoofed identities and moved endpoints fail.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

SCOPES = ("media_read", "incoming_copy", "receiver_control")
MAX_NONCES = 512


def sas(fp_a: str, fp_b: str) -> str:
    """Same 6-digit code on both sides regardless of who initiated."""
    lo, hi = sorted((fp_a, fp_b))
    n = int.from_bytes(hashlib.sha256(f"{lo}|{hi}".encode()).digest()[:4], "big") % 1_000_000
    return f"{n:06d}"


class Trust:
    def __init__(self, own_fp: str, path: Path | None = None) -> None:
        self.own_fp = own_fp
        self.path = Path(path) if path else None
        self.peers: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}
        self._nonces: list[str] = []
        if self.path:
            try:
                data = json.loads(self.path.read_text("utf-8"))
                for fp, p in data.get("peers", {}).items():
                    self.peers[fp] = {"name": str(p.get("name", ""))[:40], "endpoint": str(p.get("endpoint", "")),
                                      "scopes": [s for s in p.get("scopes", []) if s in SCOPES]}
            except (OSError, ValueError, AttributeError):
                pass

    # ---- pairing -------------------------------------------------------
    def begin(self, peer_fp: str, name: str, endpoint: str) -> dict | None:
        """A discovery record is only a hint; this starts the handshake."""
        if not peer_fp or peer_fp == self.own_fp:
            return None
        self._pending[peer_fp] = {"name": name[:40], "endpoint": endpoint}
        return {"peer": peer_fp, "sas": sas(self.own_fp, peer_fp), "name": name[:40]}

    def approve(self, peer_fp: str, entered_sas: str, scopes: list[str]) -> tuple[bool, str]:
        pend = self._pending.get(peer_fp)
        if pend is None:
            return False, "No pairing in progress for that device."
        if entered_sas != sas(self.own_fp, peer_fp):
            return False, "The codes don't match. Do not approve."
        self.peers[peer_fp] = {"name": pend["name"], "endpoint": pend["endpoint"],
                               "scopes": [s for s in scopes if s in SCOPES]}
        del self._pending[peer_fp]
        self._save()
        return True, ""

    # ---- ongoing ---------------------------------------------------------
    def authorise(self, peer_fp: str, scope: str, source_endpoint: str, nonce: str) -> tuple[bool, str]:
        peer = self.peers.get(peer_fp)
        if peer is None:
            return False, "Unknown or revoked device."
        if scope not in peer["scopes"]:
            return False, "That device isn't allowed to do this."
        if source_endpoint != peer["endpoint"]:
            return False, "The device moved. Pair it again to confirm."
        if not nonce or nonce in self._nonces:
            return False, "Repeated request."
        self._nonces.append(nonce)
        del self._nonces[:-MAX_NONCES]
        return True, ""

    def set_scope(self, peer_fp: str, scope: str, allowed: bool) -> bool:
        peer = self.peers.get(peer_fp)
        if peer is None or scope not in SCOPES:
            return False
        has = scope in peer["scopes"]
        if allowed and not has:
            peer["scopes"].append(scope)
        elif not allowed and has:
            peer["scopes"].remove(scope)
        self._save()
        return True

    def revoke(self, peer_fp: str) -> bool:
        gone = self.peers.pop(peer_fp, None) is not None
        self._pending.pop(peer_fp, None)
        if gone:
            self._save()
        return gone

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".trust")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"peers": self.peers}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
