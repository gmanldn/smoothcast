"""Pure assignment, fencing and exactly-once rules for mesh link acquisition (#589).

Transport-free and I/O-free: no sockets, files, subprocesses, GUI or receiver
action. The room host owns an :class:`AssignmentLedger` (sole queue authority);
a worker node owns an :class:`ExecutorGuard`. A later RPC layer only carries
these calls and replies.

Safety rules encoded here:

* One live external download per canonical source: duplicate submissions map to
  the existing job, across retries and restarts (``snapshot``/``restore``).
* Every assignment carries a monotonically increasing **generation** (fence).
  An executor rejects any generation lower than one it has seen, and the ledger
  rejects reports from a superseded generation.
* An expired lease is **ambiguous**, never silently reassigned: the remote node
  may still be downloading. A new generation needs an explicit resolution.
* Completed media is enqueued at most once (``enqueue_once``).
* Nothing public carries URLs, infohashes, paths or peer addresses.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Iterable

PROTOCOL_VERSION = 1  # 0 or absent on a peer means "no acquisition extension"
STAGES = ("pending", "resolving", "metadata", "downloading", "verifying", "transfer", "queued")
TERMINAL = frozenset({"queued", "cancelled", "failed"})
MAX_JOBS = 256
MAX_BYTES = 1 << 40
_ID = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
_NODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_KEY = re.compile(r"[0-9a-f]{64}\Z")


def source_key(kind: str, identity: str) -> str:
    """Stable digest of a canonical source; the only form that crosses nodes."""
    return hashlib.sha256(f"{kind}:{identity}".encode()).hexdigest()


def negotiate(local: int, peer: object) -> int:
    """Highest shared protocol version; 0 means the peer cannot take jobs."""
    if type(peer) is not int or peer < 1 or type(local) is not int or local < 1:
        return 0
    return min(local, peer)


@dataclass(frozen=True)
class NodeOffer:
    node_id: str
    local: bool = False
    trusted: bool = False
    live: bool = False
    opted_in: bool = False
    protocol: int = 0
    providers: frozenset[str] = frozenset()
    free_bytes: int = 0
    slots_free: int = 0


@dataclass(frozen=True)
class Selection:
    node_id: str
    local: bool
    reason: str


def select_executor(kind: str, needed_bytes: int, offers: Iterable[NodeOffer], *,
                    prefer_local: bool = True, headroom: int = 1 << 30) -> Selection | None:
    """Pick a trusted, live, opted-in node with the provider, space and a free slot.

    The local node needs no protocol negotiation. Ties go to the most free
    space, then node id, so the choice is deterministic.
    """
    need = max(0, needed_bytes) if type(needed_bytes) is int else MAX_BYTES
    eligible = []
    for offer in offers:
        if not _NODE.fullmatch(offer.node_id or "") or not (offer.trusted and offer.live and offer.opted_in):
            continue
        if not offer.local and negotiate(PROTOCOL_VERSION, offer.protocol) == 0:
            continue
        if kind not in offer.providers or offer.slots_free < 1 or offer.free_bytes < need + headroom:
            continue
        eligible.append(offer)
    if not eligible:
        return None
    local = [o for o in eligible if o.local]
    pool = local if (local and prefer_local) else eligible
    best = min(pool, key=lambda o: (-o.free_bytes, o.node_id))
    return Selection(best.node_id, best.local,
                     "local node preferred" if best.local and prefer_local else "most free space")


@dataclass
class Job:
    job_id: str
    key: str
    state: str = "pending"
    node: str | None = None
    generation: int = 0
    lease_until: float = 0.0
    seen_at: float = 0.0
    received: int = 0
    total: int = 0
    content_key: str | None = None
    ambiguous: bool = False
    enqueued: bool = False


class LedgerError(ValueError):
    """Refused request; the ledger is unchanged."""


class AssignmentLedger:
    """Room-host record of who owns each acquisition and under which fence."""

    def __init__(self, lease_seconds: float = 60.0, stale_seconds: float = 30.0) -> None:
        self.lease_seconds, self.stale_seconds = lease_seconds, stale_seconds
        self.jobs: dict[str, Job] = {}

    # -- creation / dedupe ---------------------------------------------------
    def create(self, job_id: str, key: str, now: float) -> str:
        if not _ID.fullmatch(job_id or "") or not _KEY.fullmatch(key or ""):
            raise LedgerError("invalid job or source identity")
        for job in self.jobs.values():
            if job.key == key and job.state not in TERMINAL:
                return job.job_id  # one download per source, however often submitted
        if job_id in self.jobs:
            raise LedgerError("job id already used")
        if sum(j.state not in TERMINAL for j in self.jobs.values()) >= MAX_JOBS:
            raise LedgerError("too many active jobs")
        self.jobs[job_id] = Job(job_id, key, seen_at=now)
        return job_id

    def _job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise LedgerError("unknown job")
        return job

    # -- assignment ----------------------------------------------------------
    def assign(self, job_id: str, node_id: str, now: float) -> tuple[str, int]:
        """Start a new generation on *node_id*; returns (node, generation)."""
        job = self._job(job_id)
        if not _NODE.fullmatch(node_id or ""):
            raise LedgerError("invalid node")
        if job.state != "pending" or job.ambiguous:
            raise LedgerError("job is not assignable (running, ambiguous or finished)")
        job.generation += 1
        job.node, job.state = node_id, "resolving"
        job.lease_until, job.seen_at = now + self.lease_seconds, now
        return node_id, job.generation

    def _fenced(self, job: Job, node_id: str, generation: int) -> None:
        if job.state in TERMINAL:
            raise LedgerError("job already finished")
        if job.node != node_id or generation != job.generation or job.ambiguous:
            raise LedgerError("stale fence: superseded assignment")

    def report(self, job_id: str, node_id: str, generation: int, stage: str, now: float,
               received: int = 0, total: int = 0) -> None:
        """Executor progress/heartbeat. Renews the lease; stages never regress."""
        job = self._job(job_id)
        self._fenced(job, node_id, generation)
        if stage not in STAGES[1:6]:
            raise LedgerError("invalid stage")
        if STAGES.index(stage) >= STAGES.index(job.state):
            job.state = stage
        clean = lambda v: v if type(v) is int and 0 <= v <= MAX_BYTES else 0  # noqa: E731
        total = clean(total)
        received = min(clean(received), total) if total else clean(received)
        job.received, job.total = max(job.received, received), total
        job.lease_until, job.seen_at = now + self.lease_seconds, now

    def tick(self, now: float) -> list[str]:
        """Expired leases become AMBIGUOUS (remote may still be running)."""
        marked = []
        for job in self.jobs.values():
            if job.state not in TERMINAL and job.state != "pending" and not job.ambiguous \
                    and job.lease_until <= now:
                job.ambiguous = True
                marked.append(job.job_id)
        return marked

    def resolve_ambiguous(self, job_id: str, *, executor_confirmed_stopped: bool,
                          accept_duplicate_risk: bool = False) -> int:
        """Allow a new generation. Needs proof the old executor stopped, or an
        explicit acceptance that the download may be duplicated."""
        job = self._job(job_id)
        if not job.ambiguous:
            raise LedgerError("job is not ambiguous")
        if not (executor_confirmed_stopped or accept_duplicate_risk):
            raise LedgerError("ownership unresolved: confirm the old executor stopped")
        job.ambiguous, job.state, job.node = False, "pending", None
        job.received = job.total = 0
        return job.generation  # next assign() fences this one out

    # -- completion ----------------------------------------------------------
    def finished(self, job_id: str, node_id: str, generation: int, content_key: str, now: float) -> None:
        job = self._job(job_id)
        self._fenced(job, node_id, generation)
        if not _KEY.fullmatch(content_key or ""):
            raise LedgerError("invalid content key")
        job.state, job.content_key, job.seen_at = "transfer", content_key, now

    def enqueue_once(self, job_id: str, verified_content_key: str) -> bool:
        """True exactly once, and only if the transferred bytes match the key."""
        job = self._job(job_id)
        if job.state != "transfer" or job.enqueued or job.ambiguous:
            return False
        if job.content_key is None or verified_content_key != job.content_key:
            raise LedgerError("transferred content does not match the executor's key")
        job.enqueued, job.state = True, "queued"
        return True

    def cancel(self, job_id: str) -> tuple[str, int] | None:
        """Cancel; returns (node, generation) to notify, or None if nothing runs."""
        job = self._job(job_id)
        if job.state in TERMINAL:
            return None
        target = (job.node, job.generation) if job.node else None
        job.state = "cancelled"
        return target

    def fail(self, job_id: str, node_id: str, generation: int) -> None:
        job = self._job(job_id)
        self._fenced(job, node_id, generation)
        job.state = "failed"

    # -- views / persistence -------------------------------------------------
    def public_view(self, now: float) -> list[dict]:
        """Redacted: no source, key, content key, path or address."""
        rows = []
        for job in self.jobs.values():
            stale = (job.state not in TERMINAL and job.state != "pending"
                     and (job.ambiguous or now - job.seen_at > self.stale_seconds))
            rows.append({"id": job.job_id, "stage": job.state, "executor": job.node,
                         "received": job.received, "total": job.total,
                         "stale": bool(stale), "ambiguous": job.ambiguous})
        return rows

    def snapshot(self) -> dict:
        return {"v": PROTOCOL_VERSION, "jobs": [vars(j).copy() for j in self.jobs.values()]}

    @classmethod
    def restore(cls, data: object, **kwargs) -> "AssignmentLedger":
        """Rebuild after a reboot. Anything running becomes ambiguous: never
        assume the remote worker survived or died."""
        ledger = cls(**kwargs)
        if not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION \
                or not isinstance(data.get("jobs"), list) or len(data["jobs"]) > MAX_JOBS * 4:
            raise LedgerError("unreadable ledger snapshot")
        for row in data["jobs"]:
            try:
                job = Job(**row)
            except TypeError:
                raise LedgerError("unreadable ledger snapshot") from None
            if not (_ID.fullmatch(str(job.job_id)) and _KEY.fullmatch(str(job.key))
                    and job.state in STAGES + ("cancelled", "failed")
                    and type(job.generation) is int and job.generation >= 0
                    and all(isinstance(v, (int, float)) and math.isfinite(v)
                            for v in (job.lease_until, job.seen_at))):
                raise LedgerError("unreadable ledger snapshot")
            if job.state not in TERMINAL and job.state != "pending":
                job.ambiguous = True
            ledger.jobs[job.job_id] = job
        return ledger


class ExecutorGuard:
    """Worker-side fence: never run two generations of a job, never go backwards."""

    def __init__(self, slots: int = 1) -> None:
        self.slots = slots
        self.highest: dict[str, int] = {}
        self.running: dict[str, tuple[int, str]] = {}  # job -> (generation, source key)
        self.cancelled: dict[str, int] = {}

    def offer(self, job_id: str, generation: int, key: str) -> tuple[str, list[str]]:
        """Returns (verdict, superseded_job_ids_to_stop)."""
        if not _ID.fullmatch(job_id or "") or not _KEY.fullmatch(key or "") \
                or type(generation) is not int or generation < 1:
            return "invalid", []
        if generation < self.highest.get(job_id, 0) or generation <= self.cancelled.get(job_id, 0):
            return "fenced", []
        running = self.running.get(job_id)
        if running and running == (generation, key):
            return "duplicate", []  # replayed request: idempotent
        if running and running[1] != key:
            return "invalid", []  # a job id can never change its source
        stop = [job_id] if running and generation > running[0] else []
        if not running and len(self.running) >= self.slots:
            return "busy", []
        self.highest[job_id] = generation
        self.running[job_id] = (generation, key)
        return "accepted", stop

    def cancel(self, job_id: str, generation: int) -> bool:
        """Stop if the fence is current or newer; a stale cancel is ignored."""
        if generation < self.highest.get(job_id, 0):
            return False
        self.cancelled[job_id] = max(generation, self.cancelled.get(job_id, 0))
        self.highest[job_id] = max(generation, self.highest.get(job_id, 0))
        return self.running.pop(job_id, None) is not None

    def done(self, job_id: str, generation: int) -> bool:
        running = self.running.get(job_id)
        if running and running[0] == generation:
            del self.running[job_id]
            return True
        return False
