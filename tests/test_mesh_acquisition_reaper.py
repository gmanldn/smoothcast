"""Worker disk is reclaimed: stale uncollected copies and orphan directories (#589)."""
from __future__ import annotations

import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire
import mesh_acquisition_assignment as core
import mesh_acquisition_transfer as transfer

VIDEO = "abcdefghijk"
JOB = "0123456789abcdef01234567"


class Provider:
    def capabilities(self):
        return {"youtube": True}

    def acquire(self, source, directory, stage, progress, cancelled):
        path = directory / "c.mp4"
        path.write_bytes(b"x" * 32)
        return path


def make(tmp_path):
    now = [100.0]
    srv = transfer.TransferServer("127.0.0.1", clock=lambda: now[0])
    ex = executor.RemoteExecutor(tmp_path, Provider(), lambda s, m: {"ok": True}, server=srv,
                                 clock=lambda: now[0], retry_wait=lambda s: None)
    worker = wire.WorkerService(ex.start, ex.stop, 1, ticket=ex.ticket, discard=ex.discard)
    ex.bind(worker)
    worker.handle(wire.build("offer", job=JOB, gen=1, key=core.source_key("youtube", VIDEO),
                             kind="youtube", src=VIDEO), sender="host")
    ex.join()
    return ex, srv, now


def test_uncollected_copy_is_reaped_after_the_ttl_but_not_before(tmp_path):
    ex, srv, now = make(tmp_path)
    try:
        directory = tmp_path / "remote" / JOB
        assert JOB in ex.results and directory.exists()
        now[0] += executor.RESULT_TTL - 1
        assert ex.reap() == [] and directory.exists()
        now[0] += executor.REAP_EVERY + 2
        assert ex.reap() == [JOB]
        assert JOB not in ex.results and not directory.exists()
        assert ex.ticket(JOB, 1) is None
    finally:
        srv.close()


def test_reaping_is_rate_limited_and_piggybacks_on_telemetry_rows(tmp_path):
    ex, srv, now = make(tmp_path)
    try:
        now[0] += executor.RESULT_TTL + 1
        assert ex.rows() == []  # reads the rows and reaps as a side effect
        assert JOB not in ex.results
        # a second call inside REAP_EVERY does no work
        (tmp_path / "remote" / "leftover").mkdir()
        assert ex.reap() == [] and (tmp_path / "remote" / "leftover").exists()
        now[0] += executor.REAP_EVERY + 1
        ex.reap()
        assert not (tmp_path / "remote" / "leftover").exists()
    finally:
        srv.close()


def test_orphan_directories_are_swept_but_owned_ones_survive(tmp_path):
    ex, srv, now = make(tmp_path)
    try:
        orphan = tmp_path / "remote" / "abandoned"
        orphan.mkdir()
        (orphan / "f.mp4").write_bytes(b"1")
        outside = tmp_path / "keep"
        outside.mkdir()
        link = tmp_path / "remote" / "link"
        link.symlink_to(outside)
        assert ex.sweep_orphans() == 1
        assert not orphan.exists() and (tmp_path / "remote" / JOB).exists()
        assert outside.exists() and link.is_symlink()  # symlinks are never followed or removed
    finally:
        srv.close()


def test_startup_sweep_clears_a_previous_runs_leftovers(tmp_path):
    (tmp_path / "state" / "worker" / "remote" / "crashed").mkdir(parents=True)
    (tmp_path / "state" / "worker" / "remote" / "crashed" / "f.mp4").write_bytes(b"1")
    import mesh_acquisition_app as app

    class Local:
        def capabilities(self):
            return {"youtube": True}

    remote = app.RemoteAcquisition(tmp_path / "state", bind_ip="127.0.0.1", local_provider=Local())
    try:
        assert not (tmp_path / "state" / "worker" / "remote" / "crashed").exists()
    finally:
        remote.close()
