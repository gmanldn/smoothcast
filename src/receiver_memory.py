"""Bounded receiver-specific playback outcomes (issue #514, slice 1).

GTK-free, no media names/paths or raw network identities on disk. The data is
advisory only: a later planner must still enforce hard capability constraints.
Receiver keys and source codec signatures are SHA-256 digests, not user labels.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Callable

SCHEMA = 1
MAX_AGE_SECONDS = 90 * 24 * 3600
MAX_RECEIVERS = 200
MAX_SIGNATURES = 50
MAX_OUTCOMES = 8
MAX_FILE_BYTES = 4 * 1024 * 1024
STATE_NAME = "receiver_memory.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CODEC_PART = re.compile(r"[A-Za-z0-9_.+-]{1,48}\Z")
_UUID = re.compile(r"[A-Za-z0-9-]{1,128}\Z")


@dataclass(frozen=True)
class Outcome:
    mode: str
    ok: bool
    at: float


Store = dict[str, dict[str, list[Outcome]]]


def receiver_key(*, uuid: str = "", host: str = "", port: int = 0) -> str:
    """Hash stable receiver UUID, or a validated IP:port when UUID is missing."""
    if uuid:
        if not _UUID.fullmatch(uuid):
            raise ValueError("Receiver UUID is invalid")
        identifier = "uuid:" + uuid.lower()
    else:
        try:
            ip = str(ipaddress.ip_address(host))
        except ValueError as exc:
            raise ValueError("A receiver IP address or UUID is required") from exc
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Receiver port is invalid")
        identifier = f"endpoint:{ip}:{port}"
    return hashlib.sha256(identifier.encode("ascii")).hexdigest()


def codec_signature(*, container: str, video: str, profile: str = "none",
                    level: str = "none", audio: str, subtitle: str = "none") -> str:
    """Digest only bounded codec descriptors: never a filename or file path."""
    parts = (container, video, profile, level, audio, subtitle)
    if not all(isinstance(p, str) and _CODEC_PART.fullmatch(p) for p in parts):
        raise ValueError("Codec signature must use bounded codec descriptors")
    return hashlib.sha256("|".join(p.lower() for p in parts).encode("ascii")).hexdigest()


def _digest(value: str) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _trim(store: Store, now: float) -> Store:
    """Prune expired/future outcomes and least-recently-used nested records."""
    cleaned: Store = {}
    for receiver, signatures in store.items():
        valid: dict[str, list[Outcome]] = {}
        for signature, records in signatures.items():
            recent = [item for item in records[-MAX_OUTCOMES:]
                      if 0 <= now - item.at <= MAX_AGE_SECONDS]
            if recent:
                valid[signature] = recent
        if valid:
            ranked = sorted(valid, key=lambda key: (valid[key][-1].at, key), reverse=True)
            cleaned[receiver] = {key: valid[key] for key in ranked[:MAX_SIGNATURES]}
    ranked_receivers = sorted(
        cleaned, key=lambda key: (max(items[-1].at for items in cleaned[key].values()), key),
        reverse=True,
    )
    return {key: cleaned[key] for key in ranked_receivers[:MAX_RECEIVERS]}


class ReceiverMemory:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.RLock()

    def _quarantine(self) -> None:
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".corrupt"))
        except OSError:
            pass

    def _read(self) -> Store:
        try:
            with self.path.open("rb") as stream:
                payload = stream.read(MAX_FILE_BYTES + 1)
            if len(payload) > MAX_FILE_BYTES:
                raise ValueError("Receiver memory exceeds safety cap")
            root = json.loads(payload)
            if not isinstance(root, dict) or type(root.get("schema")) is not int:
                raise ValueError("Unknown receiver memory format")
            if root["schema"] != SCHEMA or not isinstance(root.get("receivers"), dict):
                raise ValueError("Unknown receiver memory schema")
            raw: dict = root["receivers"]
            if len(raw) > MAX_RECEIVERS:
                raise ValueError("Receiver memory exceeds capacity")
            result: Store = {}
            for receiver, signatures in raw.items():
                if not _digest(receiver) or not isinstance(signatures, dict):
                    raise ValueError("Malformed receiver identity")
                if len(signatures) > MAX_SIGNATURES:
                    raise ValueError("Receiver signatures exceed capacity")
                entries: dict[str, list[Outcome]] = {}
                for signature, outcomes in signatures.items():
                    if (not _digest(signature) or not isinstance(outcomes, list)
                            or len(outcomes) > MAX_OUTCOMES):
                        raise ValueError("Malformed codec history")
                    records: list[Outcome] = []
                    for item in outcomes:
                        if not isinstance(item, dict):
                            raise ValueError("Malformed outcome")
                        mode, ok, at = item.get("mode"), item.get("ok"), item.get("at")
                        if (mode not in ("direct", "hls") or type(ok) is not bool
                                or type(at) not in (int, float) or not math.isfinite(at)
                                or at < 0):
                            raise ValueError("Malformed outcome fields")
                        records.append(Outcome(mode, ok, float(at)))
                    entries[signature] = records
                result[receiver] = entries
            return result
        except FileNotFoundError:
            return {}
        except OSError:
            return {}  # Unreadable state is not evidence against a receiver.
        except (ValueError, TypeError, KeyError, UnicodeError):
            self._quarantine()
            return {}

    def _write(self, state: Store) -> bool:
        temp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(prefix="." + self.path.name + ".",
                                        suffix=".tmp", dir=self.path.parent)
            temp = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({
                    "schema": SCHEMA,
                    "receivers": {
                        key: {sig: [{"mode": row.mode, "ok": row.ok, "at": row.at}
                                   for row in rows]
                              for sig, rows in signatures.items()}
                        for key, signatures in state.items()
                    },
                }, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            return True
        except OSError:
            return False
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    def record(self, key: str, signature: str, mode: str, ok: bool) -> bool:
        """Persist one *confirmed* result; never infer success from CLI exit."""
        if not _digest(key) or not _digest(signature):
            raise ValueError("Receiver identity and codec signature must be digests")
        if mode not in ("direct", "hls") or type(ok) is not bool:
            raise ValueError("Invalid playback outcome")
        now = self.clock()
        if not math.isfinite(now) or now < 0:
            raise ValueError("Invalid clock")
        with self._lock:
            state = _trim(self._read(), now)
            records = state.setdefault(key, {}).setdefault(signature, [])
            records.append(Outcome(mode, ok, now))
            return self._write(_trim(state, now))

    def advice(self, key: str, signature: str) -> str | None:
        """A hint, never a codec override: two direct failures => HLS.

        Three consecutive confirmed direct successes => direct preference.
        HLS attempts do not count as evidence that direct casting works.
        """
        if not _digest(key) or not _digest(signature):
            return None
        now = self.clock()
        if not math.isfinite(now):
            return None
        with self._lock:
            direct = [row for row in _trim(self._read(), now)
                      .get(key, {}).get(signature, []) if row.mode == "direct"]
        if len(direct) >= 2 and not direct[-1].ok and not direct[-2].ok:
            return "hls"
        if len(direct) >= 3 and all(row.ok for row in direct[-3:]):
            return "direct"
        return None

    def explanation(self, key: str, signature: str) -> str:
        choice = self.advice(key, signature)
        if choice == "hls":
            return "Using HLS because direct play failed twice on this receiver."
        if choice == "direct":
            return "Preferring direct play because it succeeded three times on this receiver."
        return "No reliable receiver playback preference has been learned."

    def forget(self, key: str) -> bool:
        """Forget a receiver without affecting any current playback session."""
        if not _digest(key):
            return False
        with self._lock:
            state = self._read()
            if key not in state:
                return False
            del state[key]
            return self._write(state)
