"""Remote worker runs the isolated provider and reports to the host ledger (#589)."""
from __future__ import annotations

import hashlib
import threading

import link_acquisition as links
import mesh_acquisition_assignment as core
import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire

VIDEO = "abcdefghijk"
JOB = "job-00000001"
NODE = "worker-a"


class Provider:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail
        self.release = threading.Event()
        self.started = threading.Event()
        self.release.set()

    def capabilities(self):
        return {"youtube": True, "magnet": False}

    def acquire(self, source, directory, stage, progress, cancelled):
        self.calls.append(source)
        stage("downloading")
        progress(5, 10)
        self.started.set()
        while not self.release.wait(0.01):
            if cancelled():
                raise links.LinkError(409, "Acquisition cancelled.")
        if self.fail:
            raise self.fail
        stage("verifying")
        path = directory / "clip.mp4"
        path.write_bytes(b"testdata")
        return path


class Rig:
    def __init__(self, tmp_path, provider=None, slots=1):
        self.provider = provider or Provider()
        self.ledger = core.AssignmentLedger()
        self.clock = [1.0]
        self.host = wire.HostCoordinator(self.ledger, self._to_worker)
        self.executor = executor.RemoteExecutor(tmp_path, self.provider, self._to_host,
                                                clock=lambda: self.clock[0], retry_wait=lambda s: None)
        self.worker = wire.WorkerService(self.executor.start, self.executor.stop, slots)
        self.executor.bind(self.worker)

    def _to_worker(self, node, message):
        return self.worker.handle(message, sender="host")

    def _to_host(self, sender, message):
        return {"ok": self.host.on_message(NODE, message, self.clock[0])}

    def offers(self):
        return [core.NodeOffer(NODE, trusted=True, live=True, opted_in=True, protocol=1,
                               providers=frozenset({"youtube"}), free_bytes=1 << 40, slots_free=1)]

    def submit(self, job=JOB):
        return self.host.submit(job, "youtube", VIDEO, self.offers(), 10, 0.0)


def test_remote_download_reports_stages_and_a_verified_content_key(tmp_path):
    rig = Rig(tmp_path)
    job, _, outcome = rig.submit()
    assert outcome == "accepted"
    rig.executor.join()
    row = rig.ledger.jobs[job]
    assert row.state == "transfer" and row.content_key == hashlib.sha256(b"testdata").hexdigest()
    gen, path, digest, size = rig.executor.results[job]
    assert path.read_bytes() == b"testdata" and size == 8 and digest == row.content_key
    # host ledger accepts it exactly once, only for the executor's key
    assert rig.ledger.enqueue_once(job, row.content_key) is True
    assert rig.ledger.enqueue_once(job, row.content_key) is False
    assert rig.worker.guard.running == {}  # slot freed


def test_replayed_offer_never_starts_a_second_download(tmp_path):
    rig = Rig(tmp_path)
    rig.provider.release.clear()
    job, _, _ = rig.submit()
    assert rig.provider.started.wait(2)
    offer = wire.build("offer", job=job, gen=1, key=core.source_key("youtube", VIDEO),
                       kind="youtube", src=VIDEO)
    assert rig.worker.handle(offer, sender="host")["verdict"] == "duplicate"
    rig.provider.release.set()
    rig.executor.join()
    assert len(rig.provider.calls) == 1


def test_provider_failure_is_reported_failed_and_cleaned_up(tmp_path):
    rig = Rig(tmp_path, Provider(fail=links.LinkError(502, "boom")))
    job, _, _ = rig.submit()
    rig.executor.join()
    assert rig.ledger.jobs[job].state == "failed"
    assert not (tmp_path / "remote" / job).exists() and job not in rig.executor.results


def test_cancel_stops_the_worker_without_a_failed_report(tmp_path):
    rig = Rig(tmp_path)
    rig.provider.release.clear()
    job, _, _ = rig.submit()
    assert rig.provider.started.wait(2)
    assert rig.host.cancel(job) is True
    rig.executor.join()
    assert rig.ledger.jobs[job].state == "cancelled"
    assert not (tmp_path / "remote" / job).exists() and rig.worker.guard.running == {}


def test_worker_rejects_a_non_canonical_or_mismatched_source(tmp_path):
    rig = Rig(tmp_path)
    reports = []
    rig.executor._send = lambda sender, message: reports.append(message) or {"ok": True}
    # key that does not hash from the identity cannot even be parsed on the wire
    bad = wire.build("offer", job=JOB, gen=1, key=core.source_key("youtube", "zzzzzzzzzzz"),
                     kind="youtube", src=VIDEO)
    assert rig.worker.handle(bad, sender="host")["ok"] is False and rig.provider.calls == []
    # a source the provider cannot run is reported failed, never executed
    rig.provider.capabilities = lambda: {"youtube": False}
    ok = wire.build("offer", job=JOB, gen=1, key=core.source_key("youtube", VIDEO),
                    kind="youtube", src=VIDEO)
    rig.worker.handle(ok, sender="host")
    rig.executor.join()
    assert rig.provider.calls == [] and reports[-1]["t"] == "failed"


def test_final_report_retries_but_unreachable_host_leaves_lease_to_expire(tmp_path):
    rig = Rig(tmp_path)
    attempts = []

    def flaky(sender, message):
        attempts.append(message["t"])
        raise ConnectionError("host unreachable")

    rig.executor._send = flaky
    rig.submit()
    rig.executor.join()
    assert attempts.count("finished") == executor.FINAL_ATTEMPTS
    assert rig.ledger.jobs[JOB].state == "resolving"  # host never heard: ambiguity handles it


def test_one_slot_means_a_second_job_is_refused(tmp_path):
    rig = Rig(tmp_path)
    rig.provider.release.clear()
    rig.submit()
    assert rig.provider.started.wait(2)
    job2, _, outcome = rig.host.submit("job-00000002", "youtube", "bbbbbbbbbbb", rig.offers(), 10, 0.0)
    assert outcome == "refused" and rig.ledger.jobs[job2].state == "pending"
    rig.provider.release.set()
    rig.executor.join()
