"""Live Mesh shows who is really doing remote link work (#589)."""
from __future__ import annotations

from pathlib import Path
import threading

import mesh_acquisition_activity as activity
import mesh_acquisition_app as app
import mesh_acquisition_executor as executor
import mesh_acquisition_rpc as wire
import mesh_acquisition_assignment as core

ROOT = Path(__file__).resolve().parents[1]
JOB = "0123456789abcdef01234567"  # 24 hex, like every telemetry row id
VIDEO = "abcdefghijk"


class Slow:
    def __init__(self):
        self.go = threading.Event()
        self.started = threading.Event()

    def capabilities(self):
        return {"youtube": True}

    def acquire(self, source, directory, stage, progress, cancelled):
        stage("downloading")
        progress(5, 10)
        self.started.set()
        while not self.go.wait(0.01):
            if cancelled():
                raise RuntimeError("cancelled")
        path = directory / "c.mp4"
        path.write_bytes(b"x" * 10)
        return path


def test_worker_publishes_its_remote_job_with_a_remote_flag_and_clears_it(tmp_path):
    provider = Slow()
    ex = executor.RemoteExecutor(tmp_path, provider, lambda s, m: {"ok": True}, retry_wait=lambda s: None)
    worker = wire.WorkerService(ex.start, ex.stop, 1)
    ex.bind(worker)
    key = core.source_key("youtube", VIDEO)
    assert worker.handle(wire.build("offer", job=JOB, gen=1, key=key, kind="youtube", src=VIDEO),
                         sender="host")["ok"]
    assert provider.started.wait(2)
    rows = ex.rows()
    assert rows == [{"id": JOB, "kind": "youtube", "stage": "downloading", "received": 5,
                     "total": 10, "rate": None, "remote": True}]
    # the real telemetry filter keeps the flag and still strips everything else
    cleaned = activity.clean_jobs([{**rows[0], "url": "https://x", "owner": "o", "title": "t"}])
    assert cleaned == [{"id": JOB, "kind": "youtube", "stage": "downloading", "received": 5,
                        "total": 10, "rate": None, "remote": True}]
    provider.go.set()
    ex.join()
    assert ex.rows() == []


def test_flag_is_only_honoured_when_exactly_true():
    base = {"id": JOB, "kind": "magnet", "stage": "pending"}
    assert "remote" not in activity.clean_jobs([{**base, "remote": "yes"}])[0]
    assert "remote" not in activity.clean_jobs([{**base, "remote": 1}])[0]
    assert activity.clean_jobs([{**base, "remote": True}])[0]["remote"] is True


def test_host_shows_delegated_jobs_as_waiting_not_as_a_second_download(tmp_path):
    remote = app.RemoteAcquisition(tmp_path, bind_ip="127.0.0.1", local_provider=None)
    remote.executors["a" * 24] = "node-w"
    rows = [{"id": "a" * 24, "kind": "youtube", "stage": "downloading", "received": 4, "total": 9, "rate": 3},
            {"id": "b" * 24, "kind": "magnet", "stage": "downloading", "received": 1, "total": 2, "rate": 1}]
    shown = remote.activity(rows)
    assert shown[0]["stage"] == "pending" and shown[0]["received"] is None and shown[0]["rate"] is None
    assert shown[1] == rows[1]  # this node's own local download is untouched
    assert rows[0]["stage"] == "downloading"  # input not mutated


def test_job_ids_issued_to_workers_are_valid_telemetry_ids():
    assert activity.ID.fullmatch(app.secrets.token_hex(12))
    source = (ROOT / "src" / "mesh_acquisition_app.py").read_text()
    assert "secrets.token_hex(12)" in source


def test_panel_labels_remote_rows():
    panel = (ROOT / "src" / "portal_mesh_panel.py").read_text()
    assert "running for another room" in panel and "job.remote===true" in panel
