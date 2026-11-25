"""Kill-at-every-journal-write recovery matrix for link acquisition (#590).

A crash is simulated by freezing the room's whole private directory (journal and
staged media) after *each* journal write a real job performs, then starting a
fresh ``LinkJobs`` on each frozen copy. Whatever instant the process died, a
restart must never download, deliver or queue anything by itself, must never
expose a session secret, and must leave exactly one safe way forward.
No network, GTK or receiver is involved.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import pytest

import link_acquisition as acquisition

YOUTUBE = "https://www.youtube.com/watch?v=abcdefghijk"
JOURNAL = "acquisition-journal.json"
SAFE_AFTER_RESTART = {"failed", "cancelled", "ready", "delivery_uncertain"}


class Provider:
    def __init__(self):
        self.calls = []

    def capabilities(self):
        return {"youtube": True, "magnet": False}

    def acquire(self, source, root, stage, progress, cancelled):
        self.calls.append(source)
        stage("downloading")
        progress(4, 8)
        stage("verifying")
        path = root / "sample.mp4"
        path.write_bytes(b"testdata")
        return path


def _wait(predicate, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _record_every_journal_write(monkeypatch, root: Path, frozen: list[Path]):
    original = acquisition._JobJournal.save
    lock = threading.Lock()

    def save(self, jobs):
        original(self, jobs)
        with lock:                                   # the file is durable: the process may die now
            target = root.parent / f"frozen-{len(frozen)}"
            shutil.copytree(root, target, ignore=shutil.ignore_patterns(".acquisition.lock"))
            frozen.append(target)

    monkeypatch.setattr(acquisition._JobJournal, "save", save)


def _run_one_job(monkeypatch, tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    frozen: list[Path] = []
    _record_every_journal_write(monkeypatch, root, frozen)
    provider, deliveries = Provider(), []
    jobs = acquisition.LinkJobs(root, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    try:
        jobs.submit("guest-session-secret", YOUTUBE, "guest-request-secret")
        _wait(lambda: jobs.snapshot()[0]["stage"] == "ready")
    finally:
        jobs.close()
        monkeypatch.undo()                           # recovery runs must not keep recording
    assert len(provider.calls) == 1 and len(deliveries) == 1
    return list(frozen)


def _stages(directory: Path) -> list[str]:
    return [row["stage"] for row in json.loads((directory / JOURNAL).read_text())["jobs"]]


def test_every_durable_instant_is_observed_and_never_contains_secrets(monkeypatch, tmp_path):
    frozen = _run_one_job(monkeypatch, tmp_path)
    seen = [_stages(path)[-1] for path in frozen]
    # pending receipt, in-flight stage, delivery intent (queueing) and the final receipt.
    assert seen[0] == "pending" and "queueing" in seen and seen[-1] == "ready"
    for path in frozen:
        text = (path / JOURNAL).read_text()
        assert "guest-session-secret" not in text and "guest-request-secret" not in text
        assert str(tmp_path) not in text and "sample.mp4" not in text


def test_restart_after_a_crash_at_any_write_never_acts_alone(monkeypatch, tmp_path):
    frozen = _run_one_job(monkeypatch, tmp_path)
    assert len(frozen) >= 4
    for index, directory in enumerate(frozen):
        before = _stages(directory)[-1]
        provider, deliveries = Provider(), []
        jobs = acquisition.LinkJobs(directory, provider, lambda owner, path: deliveries.append(path),
                                    lambda owner: True)
        try:
            row = jobs.snapshot("a-new-session")[0]
            time.sleep(0.05)                          # a stray worker would have started by now
            assert provider.calls == [] and deliveries == [], (index, before)
            assert row["stage"] in SAFE_AFTER_RESTART, (index, before, row)
            assert row["can_cancel"] is False
            if before in {"queueing", "delivery_uncertain"}:
                assert row["stage"] == "delivery_uncertain"   # may already be in Up Next
            if before in {"pending", "resolving", "downloading", "verifying"}:
                assert row["stage"] == "failed"
            assert row["error"] and str(directory) not in json.dumps(row)
        finally:
            jobs.close()


def test_the_only_way_forward_after_each_crash_is_one_explicit_safe_action(monkeypatch, tmp_path):
    frozen = _run_one_job(monkeypatch, tmp_path)
    for index, directory in enumerate(frozen):
        before = _stages(directory)[-1]
        provider, deliveries = Provider(), []
        jobs = acquisition.LinkJobs(directory, provider, lambda owner, path: deliveries.append(path),
                                    lambda owner: True)
        try:
            known = jobs.snapshot()[0]["id"]
            new = jobs.submit("fresh-session", YOUTUBE, f"request-{index}")
            if before in {"queueing", "delivery_uncertain"}:
                # Delivery may already have happened: join it, never download or queue again.
                assert new == known
                time.sleep(0.05)
                assert provider.calls == [] and deliveries == []
            elif before == "ready" and (directory / known).is_dir():
                # Verified retained media: deliberate re-queue, one delivery, no second download.
                _wait(lambda: any(r["id"] == new and r["stage"] == "ready" for r in jobs.snapshot()))
                assert provider.calls == [] and len(deliveries) == 1
            else:
                # Interrupted/failed: an explicit new request downloads exactly once, delivers once.
                assert new != known
                _wait(lambda: any(r["id"] == new and r["stage"] == "ready" for r in jobs.snapshot()))
                assert len(provider.calls) == 1 and len(deliveries) == 1
            assert len([r for r in jobs.snapshot() if r["stage"] in {"pending", "resolving",
                        "downloading", "verifying", "queueing"}]) == 0
        finally:
            jobs.close()


def test_a_crash_never_deletes_media_that_may_be_queued(monkeypatch, tmp_path):
    frozen = _run_one_job(monkeypatch, tmp_path)
    for directory in frozen:
        media = list(directory.glob("*/sample.mp4"))
        before = _stages(directory)[-1]
        jobs = acquisition.LinkJobs(directory, Provider(), lambda owner, path: None, lambda owner: True)
        try:
            jobs.snapshot()
        finally:
            jobs.close()
        if before in {"queueing", "delivery_uncertain", "ready"} and media:
            assert all(path.is_file() and path.read_bytes() == b"testdata" for path in media)


@pytest.mark.parametrize("stage", ["pending", "resolving", "downloading", "verifying", "queueing",
                                   "ready", "failed", "cancelled", "delivery_uncertain"])
def test_every_journal_stage_recovers_deterministically_twice(tmp_path, stage):
    payload = {"schema": acquisition.JOURNAL_SCHEMA, "jobs": [
        {"id": "c" * 24, "kind": "youtube", "identity": "abcdefghijk", "stage": stage}]}
    (tmp_path / JOURNAL).write_text(json.dumps(payload), encoding="utf-8")
    outcomes = []
    for _ in range(2):
        jobs = acquisition.LinkJobs(tmp_path, Provider(), lambda owner, path: None, lambda owner: True)
        try:
            row = jobs.snapshot()[0]
            outcomes.append((row["stage"], row["error"]))
        finally:
            jobs.close()
    # The first restart may explain an interruption; the stage itself must never drift.
    assert outcomes[0][0] == outcomes[1][0] and outcomes[0][0] in SAFE_AFTER_RESTART


class FullDiskProvider(Provider):
    """Writes a partial file, then the filesystem runs out of space."""

    def __init__(self):
        super().__init__()
        self.full = True

    def acquire(self, source, root, stage, progress, cancelled):
        if self.full:
            self.calls.append(source)
            stage("downloading")
            (root / "partial.mp4").write_bytes(b"part")
            raise OSError(28, "No space left on device")
        return super().acquire(source, root, stage, progress, cancelled)


def test_disk_full_during_download_cleans_staging_and_retries_exactly_once(tmp_path):
    provider = FullDiskProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    try:
        ident = jobs.submit("owner", YOUTUBE, "request-1")
        _wait(lambda: any(r["id"] == ident and r["stage"] == "failed" for r in jobs.snapshot()))
        row = next(r for r in jobs.snapshot("owner") if r["id"] == ident)
        assert row["error"] == "Acquisition could not finish on this host." and row["can_retry"] is True
        assert deliveries == [] and not (tmp_path / ident).exists()  # abandoned staging is cleaned
        saved = (tmp_path / JOURNAL).read_text()
        assert "partial.mp4" not in saved and str(tmp_path) not in saved
        assert json.loads(saved)["jobs"][0]["stage"] == "failed"
        provider.full = False
        retry = jobs.retry("owner", ident)
        _wait(lambda: any(r["id"] == retry and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 2 and len(deliveries) == 1
        assert deliveries[0].read_bytes() == b"testdata"
    finally:
        jobs.close()


def test_disk_full_while_cleaning_staging_keeps_the_room_usable(monkeypatch, tmp_path):
    host_os = acquisition.os
    frozen = {"full": True}
    real_unlink, real_rmdir = host_os.unlink, host_os.rmdir

    def full_unlink(*args, **kwargs):
        if frozen["full"]:
            raise OSError(28, "No space left on device")
        return real_unlink(*args, **kwargs)

    def full_rmdir(*args, **kwargs):
        if frozen["full"]:
            raise OSError(28, "No space left on device")
        return real_rmdir(*args, **kwargs)

    monkeypatch.setattr(host_os, "unlink", full_unlink)
    monkeypatch.setattr(host_os, "rmdir", full_rmdir)
    provider = FullDiskProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    try:
        ident = jobs.submit("owner", YOUTUBE, "request-1")
        _wait(lambda: any(r["id"] == ident and r["stage"] == "failed" for r in jobs.snapshot()))
        assert (tmp_path / ident).exists()  # cleanup could not run; nothing unsafe was deleted
        assert json.loads((tmp_path / JOURNAL).read_text())["jobs"][0]["stage"] == "failed"
        frozen["full"] = False
        provider.full = False
        retry = jobs.retry("owner", ident)
        _wait(lambda: any(r["id"] == retry and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(deliveries) == 1  # the worker survived the ENOSPC cleanup and still delivers
    finally:
        jobs.close()


def test_disk_full_before_staging_preserves_existing_media_and_retries(tmp_path, monkeypatch):
    provider = Provider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    try:
        first = jobs.submit("owner", YOUTUBE, "request-1")
        _wait(lambda: any(r["id"] == first and r["stage"] == "ready" for r in jobs.snapshot()))
        real_mkdir = Path.mkdir

        def full_mkdir(self, *args, **kwargs):
            if kwargs.get("exist_ok"):  # room bookkeeping may ensure an existing directory
                return real_mkdir(self, *args, **kwargs)
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(Path, "mkdir", full_mkdir)
        other = "https://www.youtube.com/watch?v=zzzzzzzzzzz"  # different source: no reuse
        second = jobs.submit("owner", other, "request-2")
        _wait(lambda: any(r["id"] == second and r["stage"] == "failed" for r in jobs.snapshot()))
        assert not (tmp_path / second).exists()
        assert (tmp_path / first / "sample.mp4").read_bytes() == b"testdata"
        assert len(deliveries) == 1
        monkeypatch.setattr(Path, "mkdir", real_mkdir)
        retry = jobs.retry("owner", second)
        _wait(lambda: any(r["id"] == retry and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 2 and len(deliveries) == 2
        assert deliveries[1].read_bytes() == b"testdata"
    finally:
        jobs.close()
