"""Launch-time activation wiring: settle, honour the generation, ack (#581)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import managed_activation as ma
import managed_generations as mg
import managed_startup as ms
import version

pytestmark = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"), reason="No race-safe staging primitive")

A, B = "a" * 40, "b" * 40


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def stage(root, commit, tmp_path, files):
    source = tmp_path / f"src-{commit[:2]}"
    source.mkdir(exist_ok=True)
    manifest = {}
    for name, data in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    mg.stage_local_snapshot(root, source, commit, manifest)


def launcher_files(commit):
    return {"src/cast_control.py": f"# {commit[:4]}\n".encode(),
            ".venv/bin/python": b"#!/bin/sh\n"}


def ok(_path):
    return True


@pytest.fixture
def root(tmp_path):
    install = tmp_path / "install"
    install.mkdir(mode=0o700)
    stage(install, A, tmp_path, launcher_files(A))
    stage(install, B, tmp_path, launcher_files(B))
    return install


def activate_a(root, clock):
    txn = ma.activate(root, A, probe=ok, clock=clock)
    ma.acknowledge(root, txn, A, clock=clock)


def test_flat_install_has_no_activation_and_settles_idle(tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    assert ms.activated(flat) is False
    assert ms.settle(flat) == "idle"
    assert ms.pending(flat) is None
    assert ms.active_launch(flat) is None


def test_active_launch_honours_verified_generation(root, monkeypatch):
    clock = Clock()
    activate_a(root, clock)
    monkeypatch.setattr(ms.managed_probe, "default_probe", ok)
    target = ms.active_launch(root)
    assert target == (root / "releases" / A / ".venv" / "bin" / "python",
                      root / "releases" / A / "src" / "cast_control.py")


def test_active_launch_falls_back_when_probe_rejects(root, monkeypatch):
    clock = Clock()
    activate_a(root, clock)
    monkeypatch.setattr(ms.managed_probe, "default_probe", lambda _path: False)
    assert ms.active_launch(root) is None


def test_active_launch_falls_back_when_release_is_dirty(root, monkeypatch):
    clock = Clock()
    activate_a(root, clock)
    monkeypatch.setattr(ms.managed_probe, "default_probe", ok)
    (root / "releases" / A / "src" / "cast_control.py").write_bytes(b"# tampered\n")
    assert ms.active_launch(root) is None


def test_pending_tracks_switched_then_clears_on_ack(root):
    clock = Clock()
    activate_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    assert ms.pending(root) == (txn, B)
    ma.acknowledge(root, txn, B, clock=clock)
    assert ms.pending(root) is None


def test_settle_rolls_back_a_crashed_switch(root):
    clock = Clock()
    activate_a(root, clock)
    ma.activate(root, B, probe=ok, clock=clock)  # switched, never acknowledged
    clock.now += 10_000  # the lease has expired
    assert ms.settle(root) == "rolled_back"
    assert ma.read_active(root)["current"] == A


def test_read_ready_requires_an_exact_regular_file(tmp_path):
    path = tmp_path / "ready"
    assert ms.read_ready(path) is None
    path.write_text(B.upper())
    assert ms.read_ready(path) == B
    path.write_text("not-a-commit")
    assert ms.read_ready(path) is None


def test_await_acknowledgement_confirms_the_published_commit(root, tmp_path):
    clock = Clock()
    activate_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    ready = tmp_path / "ready"
    ready.write_text(B)
    assert ms.await_acknowledgement(root, txn, B, ready, clock=clock) is True
    assert ma.read_active(root)["current"] == B


def test_await_acknowledgement_times_out_without_a_commit(root, tmp_path):
    clock = Clock()
    activate_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    advance = lambda seconds: setattr(clock, "now", clock.now + seconds)  # noqa: E731
    assert ms.await_acknowledgement(
        root, txn, B, tmp_path / "ready", timeout=1.0, clock=clock, sleep=advance) is False
    assert ma.read_active(root)["current"] == B  # still awaiting, not rolled back


def test_staged_generation_reports_its_own_commit(root):
    # The primary proves the commit it loaded from the generation it runs.
    assert version.read_checkout_revision(root / "releases" / A) == A
