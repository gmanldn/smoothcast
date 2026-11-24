"""Crash-safe switch of ONE current-generation reference, with rollback (#581).

A staged, hash-verified ``releases/<commit>`` (see ``managed_generations``) is
made current by atomically replacing a single owner-only file, ``active.json``
(``{"current", "previous", "seq"}``). Release directories are never renamed,
deleted or modified, so a running primary keeps its modules. Every step is
recorded in an fsynced ``journal.json`` guarded by a per-install, per-user lease
so ``recover`` can replay after a crash at ANY point and reach a coherent state.

This module starts and stops nothing: no process is signalled (PIDs are never
trusted), no GTK, network, pip or user-data access. The caller supplies the
GUI-free health ``probe`` and later reports the new primary's exact-commit
acknowledgement. Without one before the lease expires, recovery rolls back.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Callable

import managed_generations as mg

ACTIVE, JOURNAL, LEASE = "active.json", "journal.json", "activation.lease"
TERMINAL = {"acked", "rolled_back", "aborted"}
MAX_JSON = 1 << 20
DEFAULT_ACK_SECONDS = 300.0


class ActivationError(RuntimeError):
    """Activation refused or rolled back; the previous generation still runs."""


def _noop(_step: str) -> None:
    """Crash-injection point; tests raise from here."""


def _atomic_write(path: Path, payload: dict, hook: Callable[[str], None]) -> None:
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        hook(f"{path.name}:tmp_written")
        os.replace(tmp, path)
        hook(f"{path.name}:replaced")
        mg._sync_dir(path.parent)
    except OSError as exc:
        raise ActivationError(f"Cannot persist {path.name}: {exc.strerror or exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def _read(path: Path, *, single_link: bool = False) -> dict | None:
    try:
        # A malicious/corrupt FIFO must not hang startup before fstat.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or (single_link and info.st_nlink != 1):
                raise ActivationError(f"{path.name} is not an ordinary private file")
            raw = handle.read(MAX_JSON + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ActivationError(f"Cannot read {path.name}: {exc.strerror or exc}") from exc
    try:
        value = json.loads(raw) if len(raw) <= MAX_JSON else None
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ActivationError(f"{path.name} is corrupt; refusing to guess")
    return value


def _commit(value: object, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not mg._COMMIT.fullmatch(value):
        raise ActivationError("Invalid generation commit in activation state")
    return value


STATES = TERMINAL | {"planned", "probed", "switched"}


def _load_journal(root: Path) -> dict | None:
    """Strictly validated journal; a malformed one is never interpreted."""
    data = _read(Path(root) / JOURNAL)
    if data is None:
        return None
    txn = data.get("txn")
    if (data.get("state") not in STATES or not isinstance(txn, str)
            or not txn.isalnum() or len(txn) > 64):
        raise ActivationError("journal.json is corrupt; refusing to guess")
    _commit(data.get("to"))
    _commit(data.get("from"), True)
    _commit(data.get("prev_before"), True)
    return data


def read_active(root: Path) -> dict:
    """Return ``{"current","previous","seq"}``; a flat install has all-empty."""
    data = _read(Path(root) / ACTIVE)
    if data is None:
        return {"current": None, "previous": None, "seq": 0}
    seq = data.get("seq")
    if type(seq) is not int or seq < 0:
        raise ActivationError("Invalid activation sequence")
    return {"current": _commit(data.get("current"), True),
            "previous": _commit(data.get("previous"), True), "seq": seq}


def verify_release(root: Path, commit: str) -> None:
    """Re-hash a staged generation; any dirty/missing/extra/linked file fails."""
    _commit(commit)
    root = Path(root)
    release = root / "releases" / commit
    if not hasattr(os, "O_NOFOLLOW"):
        raise ActivationError("Secure release verification requires no-follow file handles")
    if any(path.is_symlink() for path in (root, release.parent, release)) or not release.is_dir():
        raise ActivationError("Generation is not staged in an ordinary release directory")
    meta = _read(release / "stage-manifest.json", single_link=True)
    if meta is None or meta.get("commit") != commit:
        raise ActivationError("Generation manifest is missing or for another commit")
    try:
        planned = mg._manifest(meta.get("files"))
    except mg.StageError as exc:
        raise ActivationError("Generation manifest has invalid file metadata or paths") from exc
    try:
        seen = set()
        for path in release.rglob("*"):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ActivationError("Generation contains a link or special file")
            seen.add(path.relative_to(release).as_posix())
        if seen != {name for name, _size, _sha in planned} | {"stage-manifest.json"}:
            raise ActivationError("Generation has missing or unexpected files (dirty source)")
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        for name, expected_size, expected_hash in planned:
            digest, size = hashlib.sha256(), 0
            path = release.joinpath(*name.split("/"))
            with os.fdopen(os.open(path, flags), "rb") as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_size != expected_size):
                    raise ActivationError(f"Generation file failed verification: {name}")
                while block := handle.read(min(mg.BUFFER, expected_size + 1 - size)):
                    size += len(block)
                    if size > expected_size:
                        raise ActivationError(f"Generation file grew during verification: {name}")
                    digest.update(block)
            if size != expected_size or not hmac.compare_digest(digest.hexdigest(), expected_hash):
                raise ActivationError(f"Generation file failed verification: {name}")
    except OSError as exc:
        raise ActivationError("Cannot safely read staged generation") from exc


def _lease_live(root: Path, now: float) -> bool:
    """True while another owner's lease is unexpired. Liveness is by expiry, never PID."""
    path = Path(root) / LEASE
    lease = _read(path)
    if lease is None:
        return False
    if os.name != "nt" and (path.lstat().st_uid != os.getuid() or lease.get("uid") != os.getuid()):
        raise ActivationError("Activation lease belongs to another user")
    expires = lease.get("expires")
    if type(expires) not in (int, float):
        raise ActivationError("Activation lease is corrupt")
    return expires > now


def _take_lease(root: Path, txn: str, now: float, ttl: float, hook) -> None:
    """Exclusive acquire: a complete lease file is hard-linked into place, so
    exactly one concurrent caller wins and no reader sees a partial lease. An
    EXPIRED lease is first renamed away (only one caller can win that rename)."""
    lease = {"txn": txn, "uid": os.getuid() if os.name != "nt" else 0, "expires": now + ttl}
    scratch = root / f".{LEASE}.{secrets.token_hex(6)}.tmp"
    _atomic_write(scratch, lease, hook)
    try:
        for _attempt in range(3):
            try:
                os.link(scratch, root / LEASE)
                mg._sync_dir(root)
                return
            except FileExistsError:
                if _lease_live(root, now):
                    raise ActivationError("Another activation holds this installation's lease") from None
                try:
                    os.rename(root / LEASE, root / f".{LEASE}.{secrets.token_hex(6)}.tmp")
                except FileNotFoundError:
                    pass
            except OSError as exc:
                raise ActivationError(f"Cannot take activation lease: {exc.strerror or exc}") from exc
        raise ActivationError("Another activation holds this installation's lease")
    finally:
        scratch.unlink(missing_ok=True)


def _save(root: Path, journal: dict, state: str, hook) -> dict:
    journal = {**journal, "state": state}
    _atomic_write(root / JOURNAL, journal, hook)
    hook(f"state:{state}")
    return journal


def _finish(root: Path, journal: dict, state: str, hook) -> str:
    _save(root, journal, state, hook)
    lease = _read(root / LEASE)
    if lease and lease.get("txn") == journal["txn"]:
        (root / LEASE).unlink(missing_ok=True)
        mg._sync_dir(root)
    return state


def _rollback(root: Path, journal: dict, hook) -> str:
    """Idempotent: restore the pre-activation reference, keep every release."""
    active = read_active(root)
    if active["current"] == journal["to"]:
        _atomic_write(root / ACTIVE, {"current": journal["from"],
                                      "previous": journal["prev_before"],
                                      "seq": active["seq"] + 1}, hook)
    return _finish(root, journal, "rolled_back", hook)


def activate(root: Path, commit: str, *, probe: Callable[[Path], bool],
             clock: Callable[[], float] = time.time, ack_seconds: float = DEFAULT_ACK_SECONDS,
             hook: Callable[[str], None] = _noop) -> str:
    """Make *commit* current. Returns the transaction id awaiting acknowledgement.

    Any failure before the single switch leaves ``active.json`` untouched.
    """
    root = Path(root)
    mg._directory(root)
    commit = str(_commit(commit))
    now = clock()
    txn = secrets.token_hex(8)
    _take_lease(root, txn, now, ack_seconds, hook)  # excludes every other activator
    try:
        prior = _load_journal(root)
        if prior is not None and prior.get("state") not in TERMINAL:
            _settle(root, prior, hook)  # we hold the lease, so its owner's has expired
        active = read_active(root)
        if active["current"] == commit:
            raise ActivationError("Generation is already current")
    except Exception:  # a simulated hard crash (BaseException) must leave state as-is
        (root / LEASE).unlink(missing_ok=True)
        raise
    journal = {"txn": txn, "to": commit, "from": active["current"],
               "prev_before": active["previous"], "state": "planned"}
    try:
        _save(root, journal, "planned", hook)
        verify_release(root, commit)
        if probe(root / "releases" / commit) is not True:
            raise ActivationError("Health probe rejected the staged generation")
        journal = _save(root, journal, "probed", hook)
        hook("before_switch")
        _atomic_write(root / ACTIVE, {"current": commit, "previous": active["current"],
                                      "seq": active["seq"] + 1}, hook)
        hook("after_switch")
        _save(root, journal, "switched", hook)
    except ActivationError:
        _abort_or_rollback(root, journal, hook)
        raise
    except Exception as exc:
        _abort_or_rollback(root, journal, hook)
        raise ActivationError(f"Activation failed safely: {type(exc).__name__}") from exc
    return txn


def _abort_or_rollback(root: Path, journal: dict, hook) -> None:
    try:
        if read_active(root)["current"] == journal["to"]:
            _rollback(root, journal, hook)
        else:
            _finish(root, journal, "aborted", hook)
    except Exception:  # noqa: BLE001 - the lease expiry + recover() settle it later
        pass


def acknowledge(root: Path, txn: str, commit: str, *,
                clock: Callable[[], float] = time.time, hook: Callable[[str], None] = _noop) -> str:
    """The NEW primary reports its exact commit; anything else rolls back."""
    root = Path(root)
    journal = _load_journal(root)
    if journal is None or journal.get("txn") != txn or journal.get("state") != "switched":
        raise ActivationError("No matching activation awaits acknowledgement")
    if not _lease_live(root, clock()):
        _rollback(root, journal, hook)
        raise ActivationError("Acknowledgement arrived after the lease expired; rolled back")
    if commit != journal["to"] or read_active(root)["current"] != journal["to"]:
        _rollback(root, journal, hook)
        raise ActivationError("Primary acknowledged the wrong generation; rolled back")
    return _finish(root, journal, "acked", hook)


def rollback(root: Path, txn: str, *, hook: Callable[[str], None] = _noop) -> str:
    """Explicit rollback of an unacknowledged activation (e.g. failed launch)."""
    root = Path(root)
    journal = _load_journal(root)
    if journal is None or journal.get("txn") != txn or journal.get("state") in TERMINAL:
        raise ActivationError("No open activation to roll back")
    return _rollback(root, journal, hook)


def recover(root: Path, *, clock: Callable[[], float] = time.time,
            hook: Callable[[str], None] = _noop) -> str:
    """Replay after a crash. Idempotent; returns idle|busy|aborted|rolled_back|acked."""
    root = Path(root)
    journal = _load_journal(root)
    terminal = journal is not None and journal.get("state") in TERMINAL
    if terminal:
        lease = _read(root / LEASE)
        if lease and lease.get("txn") == journal.get("txn"):
            (root / LEASE).unlink(missing_ok=True)  # crashed between journal and unlink
    if _lease_live(root, clock()):
        return "busy"  # its owner may still be working or awaiting acknowledgement
    for stale in root.glob(".*.tmp"):  # leftovers of a crashed atomic write
        stale.unlink(missing_ok=True)
    if journal is None:
        return "idle"
    return journal["state"] if terminal else _settle(root, journal, hook)


def _settle(root: Path, journal: dict, hook) -> str:
    if read_active(root)["current"] == journal["to"]:
        return _rollback(root, journal, hook)  # switched but never acknowledged
    return _finish(root, journal, "aborted", hook)


def staged_notice(root: Path, running_commit: str | None) -> str | None:
    """User-facing text when the current reference is not what is running."""
    current = read_active(Path(root))["current"]
    if current is None or current == running_commit:
        return None
    return "An update is staged but not yet running. Restart SmoothCast when you are ready."
