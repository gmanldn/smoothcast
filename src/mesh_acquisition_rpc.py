"""Transport-agnostic offer/report/cancel messages for mesh link acquisition (#589).

Builds on :mod:`mesh_acquisition_assignment`. ``HostCoordinator`` (room host,
sole queue authority) sends authenticated, idempotent, fenced messages through
a caller-supplied ``send(node_id, message) -> reply`` callable; ``WorkerService``
answers them. No sockets, files, subprocesses, GUI or receiver action here: the
real mesh RPC only has to carry these small dicts. The sender identity always
comes from the authenticated transport, never from the message body.

Messages are allow-listed, size-bounded and carry only a job id, generation,
provider kind and the source *digest*; never a URL, infohash, path or address.
"""
from __future__ import annotations

import re
from typing import Callable

import mesh_acquisition_assignment as core

WIRE_VERSION = 1
KINDS = ("youtube", "magnet")
MAX_FIELD = 128
_FIELDS = {
    "offer": {"job", "gen", "key", "kind", "src"},
    "cancel": {"job", "gen"},
    "report": {"job", "gen", "stage", "received", "total"},
    "finished": {"job", "gen", "content"},
    "failed": {"job", "gen"},
}


class WireError(ValueError):
    """Malformed or oversized message; never acted upon."""


def build(message_type: str, /, **fields) -> dict:
    return {"v": WIRE_VERSION, "t": message_type, **fields}


def parse(message: object) -> dict:
    """Strictly validate a message; unknown keys, types or sizes are refused."""
    if not isinstance(message, dict) or message.get("v") != WIRE_VERSION:
        raise WireError("unsupported message")
    kind = message.get("t")
    allowed = _FIELDS.get(kind) if isinstance(kind, str) else None
    if allowed is None or set(message) != allowed | {"v", "t"}:
        raise WireError("unexpected fields")
    for name, value in message.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise WireError("bad field type")
        if isinstance(value, str) and len(value) > MAX_FIELD:
            raise WireError("field too long")
    if not isinstance(message["job"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{8,64}", message["job"]):
        raise WireError("invalid job identity")
    if type(message["gen"]) is not int or not 1 <= message["gen"] <= (1 << 63) - 1:
        raise WireError("bad generation")
    if kind == "offer":
        if message["kind"] not in KINDS:
            raise WireError("unknown provider")
        # The canonical identity (11-char video id or 40-hex btih) travels only
        # on this authenticated RPC, never in telemetry, and must hash to the key.
        pattern = r"[A-Za-z0-9_-]{11}" if message["kind"] == "youtube" else r"[0-9a-f]{40}"
        if (not isinstance(message["src"], str) or not re.fullmatch(pattern, message["src"])
                or core.source_key(message["kind"], message["src"]) != message["key"]):
            raise WireError("source does not match its key")
    for name in ("key", "content"):
        if name in message and (not isinstance(message[name], str)
                                or not re.fullmatch(r"[0-9a-f]{64}", message[name])):
            raise WireError("invalid digest")
    if kind == "report":
        if message["stage"] not in core.STAGES[1:6]:
            raise WireError("invalid stage")
        for name in ("received", "total"):
            if type(message[name]) is not int or not 0 <= message[name] <= core.MAX_BYTES:
                raise WireError("invalid byte counter")
    return message


class WorkerService:
    """Executor side: fences offers/cancels and starts or stops the real worker."""

    def __init__(self, start: Callable[..., None],
                 stop: Callable[[str], None], slots: int = 1) -> None:
        self.guard = core.ExecutorGuard(slots)
        self._start, self._stop = start, stop

    def handle(self, message: object, sender: str | None = None) -> dict:
        try:
            msg = parse(message)
        except WireError:
            return {"ok": False, "verdict": "invalid"}
        if msg["t"] == "offer":
            verdict, superseded = self.guard.offer(msg["job"], msg["gen"], msg["key"])
            for job in superseded:
                self._stop(job)
            if verdict == "accepted":
                self._start(msg["job"], msg["gen"], msg["key"], msg["kind"], msg["src"], sender)
            return {"ok": verdict in ("accepted", "duplicate"), "verdict": verdict}
        if msg["t"] == "cancel":
            if self.guard.cancel(msg["job"], msg["gen"]):
                self._stop(msg["job"])
            return {"ok": True, "verdict": "cancelled"}
        return {"ok": False, "verdict": "invalid"}


class HostCoordinator:
    """Room-host side: owns the ledger; remote nodes only ever report to it."""

    def __init__(self, ledger: core.AssignmentLedger,
                 send: Callable[[str, dict], object]) -> None:
        self.ledger, self._send = ledger, send

    def submit(self, job_id: str, kind: str, identity: str, offers, needed: int,
               now: float, *, prefer_local: bool = True):
        """Dedupe, choose an executor and offer remotely. Returns
        ``(job_id, selection, outcome)``; outcome is ``local``, ``accepted``,
        ``refused``, ``ambiguous`` or ``no_executor``. A local selection is
        returned for the caller to run in-process; nothing is sent."""
        key = core.source_key(kind, identity)
        job = self.ledger.create(job_id, key, now)
        existing = self.ledger.jobs[job]
        if existing.state != "pending" or existing.ambiguous:
            return job, None, "duplicate"
        selection = core.select_executor(kind, needed, offers, prefer_local=prefer_local)
        if selection is None:
            return job, None, "no_executor"
        node, generation = self.ledger.assign(job, selection.node_id, now)
        if selection.local:
            return job, selection, "local"
        try:
            reply = self._send(node, build("offer", job=job, gen=generation, key=key, kind=kind, src=identity))
        except Exception:  # noqa: BLE001 - delivery unknown: it may be running
            self.ledger.mark_ambiguous(job, node, generation)
            return job, selection, "ambiguous"
        verdict = reply.get("verdict") if isinstance(reply, dict) else None
        if verdict in ("accepted", "duplicate"):
            return job, selection, "accepted"
        if verdict in ("busy", "fenced", "invalid", "declined"):
            self.ledger.refused(job, node, generation)
            return job, selection, "refused"
        self.ledger.mark_ambiguous(job, node, generation)
        return job, selection, "ambiguous"

    def on_message(self, sender: str, message: object, now: float) -> bool:
        """Apply a worker report. ``sender`` is the authenticated peer id."""
        try:
            msg = parse(message)
            if msg["t"] == "report":
                self.ledger.report(msg["job"], sender, msg["gen"], msg["stage"], now,
                                   msg["received"], msg["total"])
            elif msg["t"] == "finished":
                self.ledger.finished(msg["job"], sender, msg["gen"], msg["content"], now)
            elif msg["t"] == "failed":
                self.ledger.fail(msg["job"], sender, msg["gen"])
            else:
                return False
        except (WireError, core.LedgerError):
            return False
        return True

    def cancel(self, job_id: str) -> bool:
        """Cancel and tell the assigned owner; True if the owner acknowledged
        (or nothing was running remotely)."""
        target = self.ledger.cancel(job_id)
        if target is None:
            return True
        try:
            reply = self._send(target[0], build("cancel", job=job_id, gen=target[1]))
        except Exception:  # noqa: BLE001
            return False
        return isinstance(reply, dict) and bool(reply.get("ok"))
