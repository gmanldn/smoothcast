"""Two real mesh nodes (UDP discovery, HTTP RPC, ticketed HTTP transfer) hand off a link download.

Hermetic by default: both nodes run in this process on loopback with a fake
provider, so nothing external is downloaded. Set ``SMOOTHCAST_LAN_SMOKE`` to a
private IPv4 address of this computer to bind the same two nodes to that LAN
address instead (exercises the real interface, still one machine). The true
two-computer procedure is in docs/MESH_LAN_SMOKE.md.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import link_acquisition as links  # noqa: E402
import mesh_acquisition_app as app  # noqa: E402
import mesh_acquisition_bridge as bridge_mod  # noqa: E402
import mesh_service as svc  # noqa: E402
from test_mesh_service import wait_for  # noqa: E402

BIND = os.environ.get("SMOOTHCAST_LAN_SMOKE", "127.0.0.1")
VIDEO = "abcdefghijk"
PAYLOAD = (b"smoothcast-lan-smoke" * 4096) + b"end"


class FakeWorkerProvider:
    """Stands in for the isolated yt-dlp/torrent worker: no external traffic."""

    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {"youtube": True, "magnet": False}

    def acquire(self, source, directory, stage, progress, cancelled):
        self.calls.append(source)
        stage("downloading")
        progress(len(PAYLOAD) // 2, len(PAYLOAD))
        path = directory / "smoke.mp4"
        path.write_bytes(PAYLOAD)
        return path


def node(tmp_path, name, *, worker):
    provider = FakeWorkerProvider() if worker else None
    remote = app.RemoteAcquisition(
        tmp_path / name / "acq", bind_ip=BIND, local_provider=provider,
        use_workers=lambda: not worker, accept_work=lambda: worker)
    cfg = svc.MeshConfig(
        bind_ip=BIND, name=name, version="1.2.0", enabled=True, multicast=False,
        beacon_port=0, state_dir=tmp_path / name,
        link_acquisition_sources=("youtube",) if worker else (),
        acquisition_worker=remote.worker, acquisition_accept=lambda: worker,
        acquisition_attach=remote.attach)
    return svc.MeshService(cfg), remote, provider


@pytest.fixture
def nodes(tmp_path):
    host, host_remote, _ = node(tmp_path, "host", worker=False)
    worker, worker_remote, provider = node(tmp_path, "worker", worker=True)
    assert host.start() and worker.start()
    host._udp.stand_in_peers = [f"{BIND}:{worker._udp.port}"]
    worker._udp.stand_in_peers = [f"{BIND}:{host._udp.port}"]
    yield host, worker, host_remote, worker_remote, provider
    host.stop()
    worker.stop()
    host_remote.close()
    worker_remote.close()


def test_real_nodes_discover_each_other_and_complete_a_verified_remote_acquisition(nodes, tmp_path):
    host, worker, host_remote, worker_remote, provider = nodes

    def ready():
        offers = host_remote.offers("youtube")
        return bool(offers) and offers[0].node_id == worker.node_id

    assert wait_for(ready, 15), "host never saw an opted-in worker advertising youtube"
    assert host_remote.capabilities()["youtube"] is True
    assert bridge_mod.HINT in host.mesh_state.get(worker.node_id).capabilities

    stages, progress = [], []
    started = time.monotonic()
    path = host_remote.acquire(links.Source("youtube", VIDEO), tmp_path / "job" / "0123456789abcdef01234567",
                               stages.append, lambda r, t: progress.append((r, t)), lambda: False)
    assert time.monotonic() - started < 30
    # exact bytes, via the real RPC + ticketed HTTP transfer
    assert path.read_bytes() == PAYLOAD
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(PAYLOAD).hexdigest()
    assert len(provider.calls) == 1  # exactly one external download, on the worker
    assert [j.state for j in host_remote.ledger.jobs.values()] == ["queued"]
    # worker released its copy and ticket after the verified hand-over
    assert wait_for(lambda: not worker_remote.executor.results, 5)
    assert not list((worker_remote.state_dir / "worker" / "remote").glob("*"))
    assert stages  # stage mirroring reached the room


def test_worker_that_withdraws_opt_in_is_declined_without_a_download(nodes, tmp_path):
    host, worker, host_remote, worker_remote, provider = nodes
    assert wait_for(lambda: bool(host_remote.offers("youtube")), 15)
    worker.config.acquisition_accept = lambda: False
    worker.acquisition_bridge.accept = lambda: False
    with pytest.raises(links.LinkError):
        host_remote.acquire(links.Source("youtube", VIDEO), tmp_path / "j2" / "fedcba987654321001234567",
                            lambda s: None, lambda r, t: None, lambda: False)
    assert provider.calls == []
    assert all(j.state == "cancelled" for j in host_remote.ledger.jobs.values())
