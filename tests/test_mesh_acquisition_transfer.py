"""Verified worker-to-host file transfer over real loopback HTTP (#589)."""
from __future__ import annotations

import hashlib
import http.client

import mesh_acquisition_assignment as core
import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire
import mesh_acquisition_transfer as transfer
import pytest

VIDEO = "abcdefghijk"
DATA = b"0123456789" * 5000
SHA = hashlib.sha256(DATA).hexdigest()
NODE = "worker-a"


@pytest.fixture
def server():
    srv = transfer.TransferServer("127.0.0.1")
    yield srv
    srv.close()


def served(server, tmp_path, data=DATA, job="job-00000001"):
    path = tmp_path / "src.mp4"
    path.write_bytes(data)
    return job, server.register(job, path, len(data)), path


def test_fetch_downloads_verifies_and_publishes_atomically(server, tmp_path):
    job, token, _ = served(server, tmp_path)
    out = transfer.fetch("127.0.0.1", server.port, job, token, tmp_path / "in" / "x.mp4",
                         expect_size=len(DATA), expect_sha=SHA)
    assert out.read_bytes() == DATA and not list((tmp_path / "in").glob("*.part"))
    assert (out.stat().st_mode & 0o777) == 0o600


def test_wrong_hash_or_size_is_never_published(server, tmp_path):
    job, token, _ = served(server, tmp_path)
    dest = tmp_path / "in" / "x.mp4"
    with pytest.raises(transfer.TransferError):
        transfer.fetch("127.0.0.1", server.port, job, token, dest,
                       expect_size=len(DATA), expect_sha="0" * 64)
    assert not dest.exists() and not list((tmp_path / "in").glob("*.part"))
    with pytest.raises(transfer.TransferError):
        transfer.fetch("127.0.0.1", server.port, job, token, dest,
                       expect_size=len(DATA) - 1, expect_sha=SHA)
    assert not dest.exists()


@pytest.mark.parametrize("bad", ["wrong-token-wrong-token", "x" * 24])
def test_wrong_token_unknown_job_and_revoked_tickets_get_404(server, tmp_path, bad):
    job, token, _ = served(server, tmp_path)
    for target in (f"/acq/{job}/{bad}", f"/acq/job-99999999/{token}", "/acq/../etc/passwd", "/"):
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
        conn.request("GET", target)
        assert conn.getresponse().status == 404
        conn.close()
    server.revoke(job)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    conn.request("GET", f"/acq/{job}/{token}")
    assert conn.getresponse().status == 404
    conn.close()


def test_ticket_expires_and_file_swap_is_refused(tmp_path):
    now = [0.0]
    srv = transfer.TransferServer("127.0.0.1", clock=lambda: now[0])
    try:
        job, token, path = served(srv, tmp_path)
        path.write_bytes(b"short")  # file changed after verification
        with pytest.raises(transfer.TransferError):
            transfer.fetch("127.0.0.1", srv.port, job, token, tmp_path / "o.mp4",
                           expect_size=len(DATA), expect_sha=SHA, attempts=1)
        path.write_bytes(DATA)
        now[0] = transfer.TICKET_SECONDS + 1
        with pytest.raises(transfer.TransferError):
            transfer.fetch("127.0.0.1", srv.port, job, token, tmp_path / "o.mp4",
                           expect_size=len(DATA), expect_sha=SHA, attempts=1)
    finally:
        srv.close()


def test_resume_continues_from_a_partial_file(server, tmp_path):
    job, token, _ = served(server, tmp_path)
    dest = tmp_path / "in" / "x.mp4"
    dest.parent.mkdir()
    dest.with_name("x.mp4.part").write_bytes(DATA[:12345])
    out = transfer.fetch("127.0.0.1", server.port, job, token, dest,
                         expect_size=len(DATA), expect_sha=SHA)
    assert out.read_bytes() == DATA


def test_oversized_stream_is_cut_off(server, tmp_path):
    job, token, _ = served(server, tmp_path, data=DATA * 2)
    with pytest.raises(transfer.TransferError):
        transfer.fetch("127.0.0.1", server.port, job, token, tmp_path / "o.mp4",
                       expect_size=len(DATA), expect_sha=SHA, attempts=1)
    assert not (tmp_path / "o.mp4").exists()


def test_non_lan_endpoint_is_refused_before_any_connection(tmp_path):
    with pytest.raises(transfer.TransferError):
        transfer.fetch("8.8.8.8", 80, "job-00000001", "t" * 24, tmp_path / "o.mp4",
                       expect_size=1, expect_sha=SHA)
    with pytest.raises(ValueError):
        transfer.TransferServer("8.8.8.8")


class Provider:
    def capabilities(self):
        return {"youtube": True}

    def acquire(self, source, directory, stage, progress, cancelled):
        stage("downloading")
        path = directory / "clip.mp4"
        path.write_bytes(DATA)
        return path


def rig(tmp_path, deliver=None, fetcher=None):
    srv = transfer.TransferServer("127.0.0.1")
    ledger = core.AssignmentLedger()
    delivered = []
    state = {}
    host = wire.HostCoordinator(ledger, lambda node, msg: state["worker"].handle(msg, sender="host"))
    ex = executor.RemoteExecutor(tmp_path / "w", Provider(),
                                 lambda sender, msg: {"ok": host.on_message(NODE, msg, 1.0)},
                                 server=srv, retry_wait=lambda s: None)
    worker = wire.WorkerService(ex.start, ex.stop, 1, ticket=ex.ticket)
    ex.bind(worker)
    state["worker"] = worker
    th = transfer.TransferHost(host, tmp_path / "host", lambda node: "127.0.0.1",
                               deliver or (lambda job, path: delivered.append((job, path))),
                               **({"fetcher": fetcher} if fetcher else {}))
    offers = [core.NodeOffer(NODE, trusted=True, live=True, opted_in=True, protocol=1,
                             providers=frozenset({"youtube"}), free_bytes=1 << 40, slots_free=1)]
    return srv, ledger, host, ex, th, offers, delivered


def test_end_to_end_worker_download_transfer_and_exactly_one_queue_add(tmp_path):
    srv, ledger, host, ex, th, offers, delivered = rig(tmp_path)
    try:
        job, _, outcome = host.submit("job-00000001", "youtube", VIDEO, offers, 10, 0.0)
        assert outcome == "accepted"
        ex.join()
        assert th.collect(job) == "queued"
        assert len(delivered) == 1 and delivered[0][1].read_bytes() == DATA
        assert th.collect(job) == "not_ready" and len(delivered) == 1  # replay: no second add
        assert ledger.jobs[job].state == "queued"
    finally:
        srv.close()


def test_failed_transfer_queues_nothing_and_can_be_retried(tmp_path):
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise transfer.TransferError("network dropped")
        return transfer.fetch(*args, **kwargs)

    srv, ledger, host, ex, th, offers, delivered = rig(tmp_path, fetcher=flaky)
    try:
        job, _, _ = host.submit("job-00000001", "youtube", VIDEO, offers, 10, 0.0)
        ex.join()
        assert th.collect(job) == "failed" and delivered == []
        assert ledger.jobs[job].state == "transfer" and not ledger.jobs[job].enqueued
        assert th.collect(job) == "queued" and len(delivered) == 1
    finally:
        srv.close()


def test_unreachable_worker_or_wrong_generation_gives_no_ticket(tmp_path):
    srv, ledger, host, ex, th, offers, delivered = rig(tmp_path)
    try:
        job, _, _ = host.submit("job-00000001", "youtube", VIDEO, offers, 10, 0.0)
        ex.join()
        assert ex.ticket(job, 99) is None
        th._address_of = lambda node: None
        assert th.collect(job) == "unavailable" and delivered == []
        assert th.collect("job-unknown01") == "not_ready"
    finally:
        srv.close()
