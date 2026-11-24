"""Mesh workers as a LinkJobs provider: end to end on loopback (#589)."""
from __future__ import annotations

from types import SimpleNamespace as NS

import link_acquisition as links
import mesh_acquisition_app as app
import mesh_acquisition_assignment as core
import mesh_acquisition_bridge as bridge_mod
import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire
import mesh_acquisition_transfer as transfer
import mesh_membership as membership
import pytest

VIDEO = "abcdefghijk"
DATA = b"verified-media" * 100
WORKER = "w" * 32
BOOT = "b" * 32


class WorkerProvider:
    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {"youtube": True, "magnet": False}

    def acquire(self, source, directory, stage, progress, cancelled):
        self.calls.append(source)
        stage("downloading")
        progress(7, 14)
        (directory / "clip.mp4").write_bytes(DATA)
        return directory / "clip.mp4"


class Stage:
    def __init__(self):
        self.stages, self.progress = [], []

    def __call__(self, value):
        self.stages.append(value)


def make(tmp_path, *, use=True, hint=True, caps=("acquire-youtube-local",)):
    srv = transfer.TransferServer("127.0.0.1")
    provider = WorkerProvider()
    box = {"now": [1.0]}
    ex = executor.RemoteExecutor(tmp_path / "wk", provider,
                                 lambda sender, msg: {"ok": box["host"].on_message(WORKER, msg, box["now"][0])},
                                 server=srv, retry_wait=lambda s: None)
    worker = wire.WorkerService(ex.start, ex.stop, 1, ticket=ex.ticket)
    ex.bind(worker)
    member = NS(node_id=WORKER, boot_id=BOOT, address="127.0.0.1", endpoint="127.0.0.1:1",
                status=membership.ALIVE)
    record = NS(boot_id=BOOT, capabilities=((bridge_mod.HINT,) if hint else ()) + tuple(caps))
    bridge = NS(members=lambda: [member], record=lambda n: record if n == WORKER else None,
                disabled=lambda n: frozenset(), host=None,
                send=lambda node, msg: worker.handle(msg, sender="host"))
    remote = app.RemoteAcquisition(tmp_path / "state", bind_ip="127.0.0.1", local_provider=None,
                                   use_workers=lambda: use, sleep=lambda s: None,
                                   clock=lambda: box["now"][0])
    remote.attach(bridge)
    box["host"] = remote.host
    remote.now = box["now"]
    return remote, provider, ex, srv


def test_remote_provider_downloads_via_worker_and_returns_a_local_verified_path(tmp_path):
    remote, provider, ex, srv = make(tmp_path)
    try:
        assert remote.capabilities() == {"youtube": True, "magnet": False}
        stage = Stage()
        directory = tmp_path / "job"
        path = remote.acquire(links.Source("youtube", VIDEO), directory, stage, lambda r, t: None,
                              lambda: False)
        ex.join()
        assert path.read_bytes() == DATA and path.parent == directory
        assert provider.calls == [links.Source("youtube", VIDEO)]
        assert stage.stages and "verifying" in stage.stages
        ledger = remote.ledger
        assert [j.state for j in ledger.jobs.values()] == ["queued"]
        assert (tmp_path / "state" / "acquisition-ledger.json").is_file()
    finally:
        srv.close()


def test_without_opt_in_or_hint_there_is_no_remote_capability(tmp_path):
    for kwargs in ({"use": False}, {"hint": False}, {"caps": ()}):
        remote, _, _, srv = make(tmp_path / str(len(kwargs)), **kwargs)
        try:
            assert remote.capabilities() == {"youtube": False, "magnet": False}
            with pytest.raises(links.LinkError):
                remote.acquire(links.Source("youtube", VIDEO), tmp_path / "j", lambda s: None,
                               lambda r, t: None, lambda: False)
            # the failed attempt must not block a later one for the same source
            assert all(j.state == "cancelled" for j in remote.ledger.jobs.values())
        finally:
            srv.close()


def test_cancel_while_remote_work_is_running_stops_the_worker(tmp_path):
    remote, provider, ex, srv = make(tmp_path)
    try:
        states = iter([False, False, True])
        remote.use_workers = lambda: True
        original = remote.collector.collect
        remote.collector.collect = lambda job: "unavailable"  # keep it from completing
        with pytest.raises(links.LinkError) as err:
            remote.acquire(links.Source("youtube", VIDEO), tmp_path / "j", lambda s: None,
                           lambda r, t: None, lambda: next(states, True))
        assert err.value.status == 409
        remote.collector.collect = original
        ex.join()
        assert all(j.state == "cancelled" for j in remote.ledger.jobs.values())
    finally:
        srv.close()


def test_lost_worker_is_ambiguous_and_fails_without_reassignment(tmp_path):
    remote, provider, ex, srv = make(tmp_path)
    now = remote.now
    try:
        remote.use_workers = lambda: True
        remote.collector.collect = lambda job: "unavailable"
        calls = []

        def sleep(seconds):
            calls.append(seconds)
            now[0] += 120.0  # lease (60s) lapses while we wait

        remote._sleep = sleep
        with pytest.raises(links.LinkError) as err:
            remote.acquire(links.Source("youtube", VIDEO), tmp_path / "j", lambda s: None,
                           lambda r, t: None, lambda: False)
        assert "not retried" in err.value.message or err.value.status in (502, 504)
        assert len(provider.calls) == 1  # never assigned a second time
    finally:
        srv.close()


def test_reconcile_after_restart_resolves_only_acknowledged_stops(tmp_path):
    remote, provider, ex, srv = make(tmp_path)
    try:
        ledger = remote.ledger
        ledger.create("job-restart1", core.source_key("youtube", VIDEO), 0.0)
        ledger.assign("job-restart1", WORKER, 0.0)
        ledger.jobs["job-restart1"].ambiguous = True  # as restore() would mark it
        remote.host._send = lambda node, msg: {"ok": False}
        assert remote.reconcile() == ["job-restart1"]
        remote.host._send = lambda node, msg: {"ok": True}
        ledger.jobs["job-restart1"].state = "resolving"
        assert remote.reconcile() == []
        assert ledger.jobs["job-restart1"].state == "cancelled"
    finally:
        srv.close()


def test_damaged_ledger_disables_remote_use_instead_of_guessing(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "acquisition-ledger.json").write_text("{not json")
    remote = app.RemoteAcquisition(tmp_path / "state", bind_ip="127.0.0.1", local_provider=None,
                                   use_workers=lambda: True)
    remote.attach(NS(members=lambda: [], record=lambda n: None, disabled=lambda n: frozenset(),
                     host=None, send=lambda *a: {}))
    assert remote.host is None and remote.capabilities() == {"youtube": False, "magnet": False}


def test_composite_prefers_a_local_worker_and_otherwise_uses_the_mesh(tmp_path):
    remote, provider, ex, srv = make(tmp_path)
    try:
        class Local:
            def capabilities(self):
                return {"youtube": True, "magnet": False}

            def acquire(self, *a):
                return "local-path"

        composite = app.CompositeProvider(Local(), remote)
        assert composite.acquire(links.Source("youtube", VIDEO), None, None, None, None) == "local-path"
        assert composite.capabilities()["youtube"] is True
        magnet = links.Source("magnet", "a" * 40)
        with pytest.raises(links.LinkError):
            composite.acquire(magnet, tmp_path / "m", lambda s: None, lambda r, t: None, lambda: False)
    finally:
        srv.close()


class _Server:
    def __init__(self):
        self.link_jobs = None
        self.dispatched = []

    def dispatch(self, op, payload):
        self.dispatched.append((op, payload))

    def session_key_active(self, key):
        return True


def test_ensure_jobs_needs_an_owner_enabled_kind_and_is_idempotent(tmp_path):
    portal = NS(server=_Server(), uploads=NS(root=tmp_path))
    assert app.ensure_jobs(portal, {}) is None and portal.server.link_jobs is None
    jobs = app.ensure_jobs(portal, {"portal_link_youtube": True})
    try:
        assert jobs is portal.server.link_jobs and app.ensure_jobs(portal, {}) is jobs
        assert jobs.provider.kinds == frozenset({"youtube"})
        assert app.ensure_jobs(NS(server=None), {"portal_link_youtube": True}) is None
    finally:
        jobs.close()


def test_mesh_workers_never_widen_the_owner_enabled_kinds(tmp_path):
    remote, *_ = make(tmp_path)
    remote.local_provider = links.CommandProvider(("magnet",))   # owner enabled only magnets
    remote.host = object()
    assert remote.capabilities()["youtube"] is False
    remote.local_provider = links.CommandProvider(("youtube",))
    assert remote.capabilities()["youtube"] is True


def test_gui_owner_without_a_local_worker_adds_a_video_through_a_mesh_worker(tmp_path):
    """GUI add on a machine with no yt-dlp: mesh worker downloads, GUI queues it once."""
    import time

    import gui_link_add

    remote, provider, ex, srv = make(tmp_path)
    portal = NS(server=_Server(), uploads=NS(root=tmp_path / "room"))
    jobs = app.ensure_jobs(portal, {"portal_link_youtube": True})
    queued = []
    try:
        remote.local_provider = jobs.provider           # the owner-enabled, tool-less provider
        jobs.provider = app.CompositeProvider(jobs.provider, remote)
        assert jobs.capabilities()["youtube"] is True
        assert gui_link_add.attach(jobs, queued.append)
        result = gui_link_add.submit(jobs, "https://youtu.be/" + VIDEO)
        assert result.ok
        end = time.monotonic() + 8
        while time.monotonic() < end and not gui_link_add.describe(jobs, result.job_id)[1]:
            time.sleep(0.02)
        ex.join()
        assert gui_link_add.describe(jobs, result.job_id) == ("Added to Up Next", True)
        assert len(queued) == 1 and queued[0].read_bytes() == DATA
        assert provider.calls == [links.Source("youtube", VIDEO)]
        assert portal.server.dispatched == []           # GUI owner never uses the guest path
    finally:
        jobs.close()
        srv.close()
