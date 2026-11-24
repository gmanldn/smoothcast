"""Application glue: use trusted mesh workers as a link-acquisition provider (#589).

Both halves are OFF unless the operator opts in (``mesh_remote_acquisition`` to
use workers, ``mesh_accept_acquisition`` to be one). The room's existing
``LinkJobs`` keeps sole ownership of the queue, journal and guest status: remote
work is just another *provider*. ``acquire`` assigns the source to a live
worker through the fenced ledger, mirrors its stage/bytes, pulls the verified
file over the one-job ticket transfer, and returns a local path that LinkJobs
then verifies, journals and queues exactly as for a local download. A lost or
restarted worker is *ambiguous* and fails the job; it is never reassigned
automatically, so the external download cannot be duplicated.

GTK-free. Never touches the queue, the player or a receiver.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import secrets
import shutil
import threading
import time

import link_acquisition as links
import mesh_acquisition_assignment as core
import mesh_acquisition_bridge as bridge_mod
import mesh_acquisition_executor as executor_mod
import mesh_acquisition_rpc as wire
import mesh_acquisition_store as store_mod
import mesh_acquisition_transfer as transfer
import mesh_membership as membership

POLL_SECONDS = 0.5
MAX_WAIT_SECONDS = links.MAX_SECONDS + 600
_STAGE = {"resolving": "resolving", "metadata": "resolving", "downloading": "downloading",
          "verifying": "verifying", "transfer": "verifying"}


class RemoteAcquisition:
    def __init__(self, state_dir: Path, *, bind_ip: str, local_provider,
                 use_workers: Callable[[], bool] = lambda: False,
                 accept_work: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.state_dir = Path(state_dir)
        self.local_provider, self.use_workers, self.accept_work = local_provider, use_workers, accept_work
        self._clock, self._sleep = clock, sleep
        self.bridge: bridge_mod.AcquisitionBridge | None = None
        self.ledger: core.AssignmentLedger | None = None
        self.host: wire.HostCoordinator | None = None
        self.collector: transfer.TransferHost | None = None
        self.store = store_mod.LedgerStore(self.state_dir)
        self.paths: dict[str, Path] = {}
        self.executors: dict[str, str] = {}  # LinkJobs job id -> mesh node doing the work
        self._lock = threading.Lock()
        self.server: transfer.TransferServer | None = None
        self.executor: executor_mod.RemoteExecutor | None = None
        self.worker: wire.WorkerService | None = None
        if local_provider is not None and any(local_provider.capabilities().values()):
            try:
                self.server = transfer.TransferServer(bind_ip)
                self.executor = executor_mod.RemoteExecutor(
                    self.state_dir / "worker", local_provider,
                    lambda node, message: self._bridge().send(node, message), server=self.server)
                self.worker = wire.WorkerService(self.executor.start, self.executor.stop, 1,
                                                 discard=self.executor.discard,
                                                 ticket=self.executor.ticket)
                self.executor.bind(self.worker)
            except (OSError, ValueError):
                self.server = self.executor = self.worker = None

    def _bridge(self) -> bridge_mod.AcquisitionBridge:
        if self.bridge is None:
            raise ConnectionError("mesh is not running")
        return self.bridge

    def close(self) -> None:
        if self.server is not None:
            self.server.close()

    # -- MeshConfig hooks ---------------------------------------------------------
    def attach(self, bridge: bridge_mod.AcquisitionBridge) -> None:
        self.bridge = bridge
        try:
            self.ledger = self.store.load() or core.AssignmentLedger()
        except core.LedgerError:
            self.ledger = None  # damaged: never guess which node may still be downloading
            return
        self.host = wire.HostCoordinator(self.ledger, bridge.send)
        bridge.host = self.host
        self.collector = transfer.TransferHost(
            self.host, self.state_dir / "incoming", self._address,
            lambda job, path: self.paths.__setitem__(job, path))

    def _address(self, node: str) -> str | None:
        member = next((m for m in self._bridge().members()
                       if m.node_id == node and m.status == membership.ALIVE), None)
        return member.address if member else None

    # -- provider interface used by LinkJobs ---------------------------------------
    def offers(self, kind: str) -> list[core.NodeOffer]:
        bridge = self.bridge
        if bridge is None or not self.use_workers():
            return []
        offers = []
        for member in bridge.members():
            record = bridge.record(member.node_id)
            caps = getattr(record, "capabilities", ()) or ()
            if (member.status == membership.ALIVE and record is not None
                    and record.boot_id == member.boot_id and bridge_mod.HINT in caps
                    and "acquire-" + kind + "-local" in caps
                    and bridge_mod.CAPABILITY not in bridge.disabled(member.node_id)):
                # Space and slots are enforced by the worker, which refuses when full.
                offers.append(core.NodeOffer(member.node_id, trusted=True, live=True, opted_in=True,
                                             protocol=1, providers=frozenset({kind}),
                                             free_bytes=1 << 40, slots_free=1))
        return offers

    def capabilities(self) -> dict:
        local = self.local_provider.capabilities() if self.local_provider is not None else {}
        usable = self.host is not None
        # The owner enables each kind explicitly; mesh workers never widen that.
        allowed = getattr(self.local_provider, "kinds", None)
        return {kind: bool(local.get(kind)) or (usable and (allowed is None or kind in allowed)
                                                and bool(self.offers(kind)))
                for kind in ("youtube", "magnet")}

    def acquire(self, source, directory: Path, stage, progress, cancelled) -> Path:
        host, ledger, collector = self.host, self.ledger, self.collector
        if host is None or ledger is None or collector is None:
            raise links.LinkError(503, "No trusted worker is available.")
        job_id = secrets.token_hex(12)  # 24 hex: also a valid telemetry row id
        with self._lock:
            _, selection, outcome = host.submit(
                job_id, source.kind, source.identity, self.offers(source.kind), 0, self._clock())
            self.store.save(ledger)
        if outcome != "accepted":
            if outcome != "duplicate":
                with self._lock:  # never leave an unassigned job that blocks the next attempt
                    ledger.cancel(job_id)
                    self.store.save(ledger)
            if outcome in {"no_executor", "refused", "duplicate"}:
                raise links.LinkError(503, "No trusted worker is free right now.")
            raise links.LinkError(502, "The worker did not confirm the assignment.")
        deadline, shown, last = self._clock() + MAX_WAIT_SECONDS, "", None
        room_job = Path(directory).name  # LinkJobs names each job's directory by its id
        self.executors[room_job] = selection.node_id
        try:
            while True:
                if cancelled():
                    host.cancel(job_id)
                    raise links.LinkError(409, "Acquisition cancelled.")
                now = self._clock()
                with self._lock:
                    ledger.tick(now)
                    job = ledger.jobs[job_id]
                    state, ambiguous = job.state, job.ambiguous
                    counters = (job.received, job.total)
                    self.store.save(ledger)
                if ambiguous:
                    raise links.LinkError(502, "The remote worker stopped answering; not retried.")
                if state in {"failed", "cancelled"}:
                    raise links.LinkError(502, "The remote worker could not finish the download.")
                mapped = _STAGE.get(state)
                if mapped and mapped != shown:
                    shown = mapped
                    stage(mapped)
                if state == "downloading" and counters != last:
                    last = counters
                    progress(counters[0], counters[1])
                if state == "transfer":
                    result = collector.collect(job_id)
                    if result == "queued":
                        return self._adopt(job_id, Path(directory))
                    if result == "failed":
                        raise links.LinkError(502, "The file could not be transferred intact.")
                if now > deadline:
                    host.cancel(job_id)
                    raise links.LinkError(504, "The remote acquisition took too long.")
                self._sleep(POLL_SECONDS)
        finally:
            self.executors.pop(room_job, None)
            with self._lock:
                self.store.save(ledger)

    def activity(self, rows: list) -> list:
        """Telemetry for this node: rows handed to a mesh worker are shown as
        waiting here (the worker publishes the real progress, marked remote),
        plus whatever this node is executing for other rooms."""
        delegated = set(self.executors)
        out = []
        for row in rows:
            if isinstance(row, dict) and row.get("id") in delegated and row.get("stage") in {
                    "resolving", "downloading", "verifying"}:
                row = {**row, "stage": "pending", "received": None, "total": None, "rate": None}
            out.append(row)
        if self.executor is not None:
            out.extend(self.executor.rows())
        return out

    def _adopt(self, job_id: str, directory: Path) -> Path:
        """Move the verified incoming file into the job's own directory."""
        source = self.paths.pop(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ("remote" + source.suffix)
        shutil.move(str(source), str(target))
        return links._safe_media(directory, target)

    # -- startup reconciliation ---------------------------------------------------------
    def reconcile(self) -> list[str]:
        """After a restart, ask each possibly-running worker to stop; only an
        acknowledged stop resolves the job (no duplicate download). Returns the
        job ids still unresolved."""
        host, ledger = self.host, self.ledger
        if host is None or ledger is None:
            return []
        unresolved = []
        with self._lock:
            for job in list(ledger.jobs.values()):
                if not job.ambiguous or job.state in core.TERMINAL:
                    continue
                target = ledger.cancel(job.job_id)
                acknowledged = True
                if target is not None:
                    try:
                        reply = host._send(target[0], wire.build("cancel", job=job.job_id, gen=target[1]))
                        acknowledged = isinstance(reply, dict) and bool(reply.get("ok"))
                    except Exception:  # noqa: BLE001
                        acknowledged = False
                if not acknowledged:
                    unresolved.append(job.job_id)
            self.store.save(ledger)
        return unresolved


class CompositeProvider:
    """Local worker when this host has one for the kind, otherwise a mesh worker."""

    def __init__(self, local, remote: RemoteAcquisition) -> None:
        self.local, self.remote = local, remote

    def __getattr__(self, name):  # readiness, search, etc. stay local
        return getattr(self.local, name)

    def capabilities(self) -> dict:
        return self.remote.capabilities()

    def acquire(self, source, directory, stage, progress, cancelled):
        if self.local is not None and self.local.capabilities().get(source.kind):
            return self.local.acquire(source, directory, stage, progress, cancelled)
        return self.remote.acquire(source, directory, stage, progress, cancelled)


def ensure_jobs(portal, cfg: dict):
    """Give a room whose owner enabled a link kind a ``LinkJobs`` even when this
    machine has no local worker, so mesh workers can serve it (#587/#589).

    Nothing external runs until a provider reports a capability. Returns the
    room's ``LinkJobs`` or None; never raises."""
    try:
        server = getattr(portal, "server", None)
        if server is None:
            return None
        if getattr(server, "link_jobs", None) is not None:
            return server.link_jobs
        kinds = tuple(k for k in ("youtube", "magnet") if cfg.get("portal_link_" + k) is True)
        if not kinds:
            return None

        def deliver(owner, path):
            server.dispatch("queue_add", {"path": str(path), "name": Path(path).name,
                                          "_portal_auth_key": owner})

        server.link_jobs = links.LinkJobs(Path(portal.uploads.root) / "link-acquisitions",
                                          links.CommandProvider(kinds), deliver,
                                          server.session_key_active)
        return server.link_jobs
    except Exception:  # noqa: BLE001 - optional convenience, never affects the room
        return None
