"""Run an accepted remote acquisition on this node and report to the room host (#589).

``WorkerService`` fences offers; this executor is its ``start``/``stop`` target.
It re-validates the canonical source locally (identity shape, canonical URL,
hash equals the offered key), runs the *same* isolated provider the local room
uses, hashes the verified media and reports ``report``/``finished``/``failed``
to the host through ``send_to_host``. It never queues anything itself and never
transfers the file: the host pulls verified media later by content key.

GTK-free; no network beyond the injected provider. Egress policy is the
provider's, unchanged.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import threading
import time

import link_acquisition as links
import mesh_acquisition_assignment as core
import mesh_acquisition_rpc as wire

REPORT_INTERVAL = 1.0
FINAL_ATTEMPTS = 3
FINAL_RETRY_SECONDS = 1.0


class RemoteExecutor:
    def __init__(self, root: Path, provider, send_to_host: Callable[[str, dict], object], *,
                 server=None, clock: Callable[[], float] = time.monotonic,
                 retry_wait: Callable[[float], None] = time.sleep) -> None:
        self.server = server  # mesh_acquisition_transfer.TransferServer or None
        self.root = Path(root) / "remote"
        self.provider, self._send, self._clock, self._wait = provider, send_to_host, clock, retry_wait
        self.worker: wire.WorkerService | None = None
        self._lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.results: dict[str, tuple[int, Path, str, int]] = {}  # job -> (gen, file, sha256, size)

    def bind(self, worker: wire.WorkerService) -> None:
        self.worker = worker

    # -- WorkerService callbacks ---------------------------------------------
    def start(self, job: str, gen: int, key: str, kind: str, src: str, sender: str | None) -> None:
        cancel = threading.Event()
        with self._lock:
            self._cancel[job] = cancel
            thread = threading.Thread(target=self._run, args=(job, gen, key, kind, src, sender, cancel),
                                      name="mesh-remote-acquisition", daemon=True)
            self._threads[job] = thread
        thread.start()

    def ticket(self, job: str, gen: int) -> dict | None:
        """One-job download ticket for the host, only for the current verified result."""
        result = self.results.get(job)
        if self.server is None or result is None or result[0] != gen:
            return None
        _, path, _digest, size = result
        return {"port": self.server.port, "token": self.server.register(job, path, size),
                "size": size, "ext": path.suffix.lower()}

    def stop(self, job: str) -> None:
        if self.server is not None:
            self.server.revoke(job)
        with self._lock:
            event = self._cancel.get(job)
        if event is not None:
            event.set()

    def join(self, timeout: float = 5.0) -> None:
        for thread in list(self._threads.values()):
            thread.join(timeout)

    # -- internals -----------------------------------------------------------
    def _notify(self, sender: str | None, message: dict, *, final: bool = False) -> bool:
        if not sender:
            return False
        for attempt in range(FINAL_ATTEMPTS if final else 1):
            try:
                reply = self._send(sender, message)
                if isinstance(reply, dict) and reply.get("ok"):
                    return True
            except Exception:  # noqa: BLE001 - host unreachable: lease expiry covers it
                pass
            if final and attempt + 1 < FINAL_ATTEMPTS:
                self._wait(FINAL_RETRY_SECONDS)
        return False

    def _run(self, job, gen, key, kind, src, sender, cancel) -> None:
        directory = self.root / job
        last = [0.0]

        def cancelled() -> bool:
            return cancel.is_set()

        def report(stage: str, received: int = 0, total: int = 0) -> None:
            clean = lambda v: v if type(v) is int and 0 <= v <= core.MAX_BYTES else 0  # noqa: E731
            self._notify(sender, wire.build("report", job=job, gen=gen, stage=stage,
                                            received=clean(received), total=clean(total)))

        def stage(value: str) -> None:
            if cancelled():
                raise links.LinkError(409, "Acquisition cancelled.")
            if value in core.STAGES[1:6]:
                last[0] = self._clock()
                report(value)

        def progress(received, total) -> None:
            now = self._clock()
            if now - last[0] >= REPORT_INTERVAL:
                last[0] = now
                report("downloading", received, total or 0)

        try:
            source = links.Source(kind, src)
            if core.source_key(kind, src) != key or links.parse_link(source.url) != source:
                raise links.LinkError(422, "Offered source is not canonical.")
            if not self.provider.capabilities().get(kind):
                raise links.LinkError(503, "This node has not enabled that worker.")
            report("resolving")
            self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            links._reserve_cache_capacity(self.root.parent)
            shutil.rmtree(directory, ignore_errors=True)  # an earlier generation's leftovers
            directory.mkdir(parents=True, mode=0o700)
            path = links._safe_media(directory, Path(self.provider.acquire(
                source, directory, stage, progress, cancelled)))
            report("verifying")
            digest = links._sha256(path, cancelled)
            if cancelled():
                raise links.LinkError(409, "Acquisition cancelled.")
            self.results[job] = (gen, path, digest, path.stat().st_size)
            self._notify(sender, wire.build("finished", job=job, gen=gen, content=digest), final=True)
        except Exception as exc:  # noqa: BLE001
            self.results.pop(job, None)
            shutil.rmtree(directory, ignore_errors=True)
            if not cancelled() and not (isinstance(exc, links.LinkError) and exc.status == 409):
                self._notify(sender, wire.build("failed", job=job, gen=gen), final=True)
        finally:
            if cancelled():
                shutil.rmtree(directory, ignore_errors=True)
                self.results.pop(job, None)
            if self.worker is not None:
                self.worker.guard.done(job, gen)
            with self._lock:
                self._cancel.pop(job, None)
                self._threads.pop(job, None)
