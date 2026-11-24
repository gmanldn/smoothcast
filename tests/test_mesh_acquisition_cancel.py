"""Cancel and completion revoke the worker's download ticket and drop its copy (#589)."""
from __future__ import annotations

import http.client

import mesh_acquisition_assignment as core
import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire
import mesh_acquisition_transfer as transfer

VIDEO = "abcdefghijk"
DATA = b"verified" * 64
NODE = "worker-a"


class Provider:
    def capabilities(self):
        return {"youtube": True}

    def acquire(self, source, directory, stage, progress, cancelled):
        stage("downloading")
        path = directory / "clip.mp4"
        path.write_bytes(DATA)
        return path


def rig(tmp_path):
    srv = transfer.TransferServer("127.0.0.1")
    ledger = core.AssignmentLedger()
    state = {}
    host = wire.HostCoordinator(ledger, lambda node, msg: state["w"].handle(msg, sender="host"))
    ex = executor.RemoteExecutor(tmp_path / "w", Provider(),
                                 lambda s, m: {"ok": host.on_message(NODE, m, 1.0)},
                                 server=srv, retry_wait=lambda s: None)
    worker = wire.WorkerService(ex.start, ex.stop, 1, ticket=ex.ticket, discard=ex.discard)
    ex.bind(worker)
    state["w"] = worker
    delivered = []
    th = transfer.TransferHost(host, tmp_path / "in", lambda n: "127.0.0.1",
                               lambda job, path: delivered.append(path))
    offers = [core.NodeOffer(NODE, trusted=True, live=True, opted_in=True, protocol=1,
                             providers=frozenset({"youtube"}), free_bytes=1 << 40, slots_free=1)]
    return srv, ledger, host, ex, worker, th, offers, delivered


def status(server, job, token):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    conn.request("GET", f"/acq/{job}/{token}")
    code = conn.getresponse().status
    conn.close()
    return code


def test_host_cancel_after_the_download_finished_revokes_ticket_and_deletes_file(tmp_path):
    srv, ledger, host, ex, worker, th, offers, delivered = rig(tmp_path)
    try:
        job, _, _ = host.submit("0123456789abcdef01234567", "youtube", VIDEO, offers, 10, 0.0)
        ex.join()
        ticket = ex.ticket(job, 1)
        assert status(srv, job, ticket["token"]) == 200 and (tmp_path / "w" / "remote" / job).exists()
        assert host.cancel(job) is True
        assert status(srv, job, ticket["token"]) == 404  # ticket revoked at once, not at expiry
        assert job not in ex.results and not (tmp_path / "w" / "remote" / job).exists()
        assert ex.ticket(job, 1) is None
    finally:
        srv.close()


def test_successful_collect_releases_the_workers_copy(tmp_path):
    srv, ledger, host, ex, worker, th, offers, delivered = rig(tmp_path)
    try:
        job, _, _ = host.submit("0123456789abcdef01234567", "youtube", VIDEO, offers, 10, 0.0)
        ex.join()
        token = ex.ticket(job, 1)["token"]
        assert th.collect(job) == "queued" and len(delivered) == 1 and delivered[0].read_bytes() == DATA
        assert status(srv, job, token) == 404 and job not in ex.results
        assert not (tmp_path / "w" / "remote" / job).exists()
        assert th.collect(job) == "not_ready" and len(delivered) == 1
    finally:
        srv.close()


def test_stale_generation_cancel_does_not_discard_the_current_download(tmp_path):
    srv, ledger, host, ex, worker, th, offers, delivered = rig(tmp_path)
    try:
        job, _, _ = host.submit("0123456789abcdef01234567", "youtube", VIDEO, offers, 10, 0.0)
        ex.join()
        worker.guard.highest[job] = 3  # a newer generation has been seen
        assert worker.handle(wire.build("cancel", job=job, gen=1))["ok"] is True
        assert job in ex.results  # stale cancel ignored
        assert (tmp_path / "w" / "remote" / job).exists()
    finally:
        srv.close()
