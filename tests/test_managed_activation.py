"""Atomic single-reference activation survives a crash at every transition (#581)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import managed_activation as ma
import managed_generations as mg

pytestmark = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"), reason="No race-safe staging primitive")

A, B, C = "a" * 40, "b" * 40, "c" * 40


class Crash(BaseException):
    """Simulated power loss: nothing after the raise point runs."""


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def stage(root: Path, commit: str, tmp_path: Path) -> None:
    source = tmp_path / f"src-{commit[:2]}"
    source.mkdir(exist_ok=True)
    data = f"print('{commit[:4]}')\n".encode()
    (source / "main.py").write_bytes(data)
    mg.stage_local_snapshot(root, source, commit, {
        "main.py": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}})


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "releases").rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def root(tmp_path):
    install = tmp_path / "install"
    install.mkdir(mode=0o700)
    for commit in (A, B, C):
        stage(install, commit, tmp_path)
    return install


def ok(_path):
    return True


def settle_into_a(root, clock):
    txn = ma.activate(root, A, probe=ok, clock=clock)
    ma.acknowledge(root, txn, A, clock=clock)
    return ma.read_active(root)


def test_first_activation_then_upgrade_keeps_previous_and_every_release(root):
    clock, before = Clock(), tree_digest(root)
    settle_into_a(root, clock)
    assert ma.read_active(root) == {"current": A, "previous": None, "seq": 1}
    txn = ma.activate(root, B, probe=ok, clock=clock)
    assert ma.read_active(root)["current"] == B  # switched, awaiting acknowledgement
    assert ma.acknowledge(root, txn, B, clock=clock) == "acked"
    assert ma.read_active(root) == {"current": B, "previous": A, "seq": 2}
    assert tree_digest(root) == before  # live module trees never touched
    assert not (root / ma.LEASE).exists()
    if os.name != "nt":
        for name in (ma.ACTIVE, ma.JOURNAL):
            assert (root / name).stat().st_mode & 0o777 == 0o600


def test_crash_at_every_activation_step_recovers_to_the_old_generation(root, tmp_path):
    clock = Clock()
    settle_into_a(root, clock)
    steps = []
    txn = ma.activate(root, B, probe=ok, clock=clock, hook=steps.append)
    ma.rollback(root, txn)
    assert len(steps) >= 8
    checked = 0
    for index in range(len(steps)):
        clock.now += 10_000
        ma.recover(root, clock=clock)  # settle anything left from the last run
        count = [0]

        def crash_here(_name, index=index, count=count):
            if count[0] == index:
                raise Crash(_name)
            count[0] += 1

        before = tree_digest(root)
        with pytest.raises(Crash):
            ma.activate(root, B, probe=ok, clock=clock, hook=crash_here)
        # Whatever the instant of the crash, the reference is old-or-new, whole.
        assert ma.read_active(root)["current"] in (A, B)
        journal = ma._load_journal(root)
        open_txn = journal is not None and journal["state"] not in ma.TERMINAL
        if open_txn:  # its lease is live: nobody may settle it from under the owner
            assert ma.recover(root, clock=clock) == "busy"
        clock.now += 10_000  # owner is gone and its lease expired
        outcome = ma.recover(root, clock=clock)
        assert outcome in ("aborted", "rolled_back", "idle") if open_txn else outcome == journal["state"]
        assert ma.read_active(root)["current"] == A, f"step {index}: never acknowledged"
        assert ma.recover(root, clock=clock) == outcome  # idempotent replay
        assert tree_digest(root) == before and not list(root.glob(".*.tmp"))
        checked += 1
    assert checked == len(steps)
    # After all that, a clean activation still works.
    clock.now += 10_000
    ma.recover(root, clock=clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    assert ma.acknowledge(root, txn, B, clock=clock) == "acked"


def test_crash_at_every_acknowledge_step_is_consistent_with_the_journal(root):
    clock = Clock()
    settle_into_a(root, clock)
    steps = []
    txn = ma.activate(root, B, probe=ok, clock=clock)
    ma.acknowledge(root, txn, B, clock=clock, hook=steps.append)
    assert steps
    for index in range(len(steps)):
        clock.now += 10_000
        ma.recover(root, clock=clock)
        target, other = (B, A) if ma.read_active(root)["current"] == A else (A, B)
        txn = ma.activate(root, target, probe=ok, clock=clock)
        count = [0]

        def crash_here(_name, index=index, count=count):
            if count[0] == index:
                raise Crash(_name)
            count[0] += 1

        with pytest.raises(Crash):
            ma.acknowledge(root, txn, target, clock=clock, hook=crash_here)
        clock.now += 10_000
        outcome = ma.recover(root, clock=clock)
        current = ma.read_active(root)["current"]
        assert (outcome, current) in {("acked", target), ("rolled_back", other)}
        assert ma.recover(root, clock=clock) == outcome


@pytest.mark.parametrize("failure", ["probe_false", "probe_raises", "dirty", "extra", "missing", "linked"])
def test_unhealthy_or_modified_generation_is_never_switched(root, failure):
    clock = Clock()
    settle_into_a(root, clock)
    release = root / "releases" / B
    probe = ok
    if failure == "probe_false":
        probe = lambda _p: False  # noqa: E731
    elif failure == "probe_raises":
        def probe(_p):
            raise RuntimeError("gtk import failed")
    elif failure == "dirty":
        os.chmod(release, 0o700)
        os.chmod(release / "main.py", 0o600)
        (release / "main.py").write_text("tampered\n")
    elif failure == "extra":
        (release / "evil.py").write_text("x")
    elif failure == "missing":
        (release / "main.py").unlink()
    else:
        (release / "link.py").symlink_to("/etc/passwd")
    with pytest.raises(ma.ActivationError):
        ma.activate(root, B, probe=probe, clock=clock)
    assert ma.read_active(root) == {"current": A, "previous": None, "seq": 1}
    assert not (root / ma.LEASE).exists()
    assert ma.recover(root, clock=clock) == "aborted"


def test_unstaged_and_invalid_commits_are_refused(root):
    for commit in ("d" * 40, "../x", "A" * 40, None):
        with pytest.raises(ma.ActivationError):
            ma.activate(root, commit, probe=ok)
    assert ma.read_active(root)["current"] is None


def test_wrong_commit_ack_and_late_ack_roll_back(root):
    clock = Clock()
    settle_into_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    with pytest.raises(ma.ActivationError, match="wrong generation"):
        ma.acknowledge(root, txn, C, clock=clock)  # same-version/new-SHA impostor
    assert ma.read_active(root) == {"current": A, "previous": None, "seq": 3}
    txn = ma.activate(root, B, probe=ok, clock=clock, ack_seconds=60)
    clock.now += 61
    with pytest.raises(ma.ActivationError, match="expired"):
        ma.acknowledge(root, txn, B, clock=clock)
    assert ma.read_active(root)["current"] == A
    with pytest.raises(ma.ActivationError):
        ma.acknowledge(root, "feedfacefeedface", A, clock=clock)  # no such txn
    with pytest.raises(ma.ActivationError):
        ma.acknowledge(root, txn, B, clock=clock)  # already settled


def test_explicit_rollback_restores_previous_and_is_not_repeatable(root):
    clock = Clock()
    settle_into_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    assert ma.rollback(root, txn) == "rolled_back"
    assert ma.read_active(root)["current"] == A
    with pytest.raises(ma.ActivationError):
        ma.rollback(root, txn)
    # first-ever activation rolls back to "no managed generation" (flat install)
    flat = ma.activate(root, C, probe=ok, clock=clock)
    ma.rollback(root, flat)
    assert (root / "releases" / A).is_dir() and (root / "releases" / C).is_dir()


def test_live_lease_blocks_second_activator_but_expiry_allows_takeover(root):
    clock = Clock()
    txn = ma.activate(root, A, probe=ok, clock=clock, ack_seconds=60)
    with pytest.raises(ma.ActivationError, match="lease"):
        ma.activate(root, B, probe=ok, clock=clock)
    assert ma.recover(root, clock=clock) == "busy"
    clock.now += 61  # owner vanished; pid reuse is irrelevant, only expiry counts
    txn2 = ma.activate(root, B, probe=ok, clock=clock)
    assert txn2 != txn
    assert ma.read_active(root)["current"] == B  # A was never acknowledged: rolled back first
    assert ma.read_active(root)["previous"] is None
    assert ma.acknowledge(root, txn2, B, clock=clock) == "acked"


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership model")
def test_lease_for_another_user_fails_closed(root):
    clock = Clock()
    ma.activate(root, A, probe=ok, clock=clock)
    path = root / ma.LEASE
    ma._atomic_write(path, {"txn": "x", "uid": os.getuid() + 1, "expires": clock.now + 999},
                     ma._noop)
    with pytest.raises(ma.ActivationError, match="another user"):
        ma.activate(root, B, probe=ok, clock=clock)
    with pytest.raises(ma.ActivationError, match="another user"):
        ma.recover(root, clock=clock)


@pytest.mark.parametrize("name", [ma.ACTIVE, ma.JOURNAL, ma.LEASE])
@pytest.mark.parametrize("junk", [b"", b"{", b"[]", b'{"current": "../x"}', b"\xff" * 10])
def test_corrupt_state_files_fail_closed_without_guessing(root, name, junk):
    clock = Clock()
    settle_into_a(root, clock)
    (root / name).write_bytes(junk)
    with pytest.raises(ma.ActivationError):
        ma.activate(root, B, probe=ok, clock=clock)
    assert (root / "releases" / A).is_dir()


def test_disk_full_while_switching_leaves_reference_and_releases_intact(root, monkeypatch):
    clock = Clock()
    settle_into_a(root, clock)
    full = {"on": False}
    real = os.fsync

    def fsync(fd):
        if full["on"]:
            raise OSError(28, "No space left on device")
        return real(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    before = tree_digest(root)

    def probe(_path):
        full["on"] = True  # the disk fills right after the health probe
        return True

    with pytest.raises(ma.ActivationError):
        ma.activate(root, B, probe=probe, clock=clock)
    full["on"] = False
    assert ma.read_active(root) == {"current": A, "previous": None, "seq": 1}
    clock.now += 10_000
    assert ma.recover(root, clock=clock) in ("aborted", "rolled_back")
    assert tree_digest(root) == before and not list(root.glob(".*.tmp"))


def test_concurrent_activators_exactly_one_wins(root):
    clock = Clock()
    results, gate = [], threading.Barrier(6)

    def worker(commit):
        gate.wait()
        try:
            results.append(("ok", ma.activate(root, commit, probe=ok, clock=clock)))
        except ma.ActivationError as exc:
            results.append(("refused", str(exc)))

    threads = [threading.Thread(target=worker, args=(c,)) for c in (A, B, C, A, B, C)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for kind, _ in results if kind == "ok") == 1
    winner = ma.read_active(root)
    assert winner["current"] in (A, B, C) and winner["seq"] == 1


def test_staged_notice_only_when_current_differs_from_running(root):
    clock = Clock()
    assert ma.staged_notice(root, A) is None
    txn = ma.activate(root, A, probe=ok, clock=clock)
    ma.acknowledge(root, txn, A, clock=clock)
    assert ma.staged_notice(root, A) is None
    txn = ma.activate(root, B, probe=ok, clock=clock)
    ma.acknowledge(root, txn, B, clock=clock)
    assert "not yet running" in ma.staged_notice(root, A)
    assert ma.staged_notice(root, B) is None


@pytest.mark.parametrize("filename", ["main.py", "stage-manifest.json"])
def test_release_with_hardlinked_file_is_rejected_before_switch(root, tmp_path, filename):
    clock = Clock()
    settle_into_a(root, clock)
    target = root / "releases" / B / filename
    # The bytes still match. A second writable name makes the release mutable.
    os.link(target, tmp_path / "external-alias")
    with pytest.raises(ma.ActivationError, match="link|ordinary private file"):
        ma.activate(root, B, probe=ok, clock=clock)
    assert ma.read_active(root)["current"] == A


@pytest.mark.parametrize("metadata", [
    None, {"size": True, "sha256": "a" * 64},
    {"size": -1, "sha256": "a" * 64},
    {"size": mg.MAX_FILE_BYTES + 1, "sha256": "a" * 64},
    {"size": 1, "sha256": "not-a-hash"},
])
def test_release_reuses_staging_manifest_schema(root, metadata):
    manifest = root / "releases" / B / "stage-manifest.json"
    manifest.write_text(json.dumps({"commit": B, "files": {"main.py": metadata}}))
    with pytest.raises(ma.ActivationError, match="invalid file metadata"):
        ma.verify_release(root, B)


def test_release_rejects_file_larger_than_declared_without_reading_body(root, monkeypatch):
    target = root / "releases" / B / "main.py"
    with target.open("ab") as handle:
        handle.write(b"unexpected append")
    real = ma.hashlib.sha256

    def no_payload_hash(*args, **kwargs):
        digest = real(*args, **kwargs)
        class NoUpdate:
            def update(self, _block):
                pytest.fail("file larger than manifest must be refused before hashing")
            def hexdigest(self):
                return digest.hexdigest()
        return NoUpdate()

    monkeypatch.setattr(ma.hashlib, "sha256", no_payload_hash)
    with pytest.raises(ma.ActivationError, match="failed verification"):
        ma.verify_release(root, B)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO fixture")
def test_fifo_manifest_and_state_files_fail_without_blocking(root):
    manifest = root / "releases" / B / "stage-manifest.json"
    manifest.unlink()
    os.mkfifo(manifest)
    with pytest.raises(ma.ActivationError, match="ordinary private file"):
        ma.verify_release(root, B)
    active = root / ma.ACTIVE
    os.mkfifo(active)
    with pytest.raises(ma.ActivationError, match="ordinary private file"):
        ma.read_active(root)


def test_release_directory_cannot_be_redirected_via_symlink(root, tmp_path):
    releases = root / "releases"
    moved = tmp_path / "outside-releases"
    releases.rename(moved)
    releases.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ma.ActivationError, match="ordinary release directory"):
        ma.verify_release(root, B)

@pytest.mark.parametrize("expires", [float("nan"), float("inf"), -float("inf"), True])
def test_nonfinite_lease_cannot_authorise_recovery(root, expires):
    clock = Clock()
    txn = ma.activate(root, A, probe=ok, clock=clock)
    lease = ma._read(root / ma.LEASE)
    lease["expires"] = expires
    ma._atomic_write(root / ma.LEASE, lease, ma._noop)
    before = ma.read_active(root)
    with pytest.raises(ma.ActivationError, match="lease is corrupt"):
        ma.recover(root, clock=clock)
    with pytest.raises(ma.ActivationError, match="lease is corrupt"):
        ma.acknowledge(root, txn, A, clock=clock)
    assert ma.read_active(root) == before


def test_acknowledgement_cannot_borrow_another_transactions_lease(root):
    clock = Clock()
    txn = ma.activate(root, A, probe=ok, clock=clock)
    lease = ma._read(root / ma.LEASE)
    lease["txn"] = "differenttransaction"
    ma._atomic_write(root / ma.LEASE, lease, ma._noop)
    before = ma.read_active(root)
    with pytest.raises(ma.ActivationError, match="does not own"):
        ma.acknowledge(root, txn, A, clock=clock)
    assert ma.read_active(root) == before
    assert ma._read(root / ma.LEASE) == lease
    assert ma._read(root / ma.JOURNAL)["state"] == "switched"


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), True])
def test_invalid_lease_duration_refused_before_state_mutation(root, duration):
    with pytest.raises(ma.ActivationError, match="duration"):
        ma.activate(root, A, probe=ok, clock=Clock(), ack_seconds=duration)
    assert not (root / ma.LEASE).exists()
    assert not (root / ma.JOURNAL).exists()
    assert ma.read_active(root)["current"] is None


@pytest.mark.parametrize("name", [ma.ACTIVE, ma.JOURNAL, ma.LEASE])
def test_deeply_nested_state_is_reported_as_activation_error(root, name):
    clock = Clock()
    settle_into_a(root, clock)
    state = root / name
    state.write_text('{"nested":' + "[" * 10000 + "]" * 10000 + "}")
    with pytest.raises(ma.ActivationError, match="corrupt"):
        ma.activate(root, B, probe=ok, clock=clock)
    assert (root / "releases" / A / "main.py").is_file()


@pytest.mark.parametrize("state", [[], {}, None, 123])
def test_non_string_journal_state_is_refused_without_mutation(root, state):
    clock = Clock()
    settle_into_a(root, clock)
    txn = ma.activate(root, B, probe=ok, clock=clock)
    journal = ma._read(root / ma.JOURNAL)
    journal["state"] = state
    ma._atomic_write(root / ma.JOURNAL, journal, ma._noop)
    before = ma.read_active(root)
    with pytest.raises(ma.ActivationError, match="corrupt"):
        ma.recover(root, clock=clock)
    with pytest.raises(ma.ActivationError, match="corrupt"):
        ma.rollback(root, txn)
    assert ma.read_active(root) == before
    assert ma._read(root / ma.JOURNAL) == journal


def test_rollback_cannot_borrow_another_transactions_lease(root):
    clock = Clock()
    txn = ma.activate(root, A, probe=ok, clock=clock)
    lease = ma._read(root / ma.LEASE)
    lease["txn"] = "differenttransaction"
    ma._atomic_write(root / ma.LEASE, lease, ma._noop)
    before = ma.read_active(root)
    with pytest.raises(ma.ActivationError, match="does not own"):
        ma.rollback(root, txn)
    assert ma.read_active(root) == before
    assert ma._read(root / ma.LEASE) == lease
    assert ma._read(root / ma.JOURNAL)["state"] == "switched"
