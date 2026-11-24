"""#589: the assignment ledger survives crashes and corruption safely."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import mesh_acquisition_assignment as ma
from mesh_acquisition_store import NAME, LedgerStore

KEY = ma.source_key("youtube", "abcdefghijk")
JOB = "job-00000001"
CONTENT = "c" * 64


class Crash(BaseException):
    pass


def running_ledger():
    ledger = ma.AssignmentLedger()
    ledger.create(JOB, KEY, 0)
    node, gen = ledger.assign(JOB, "n1", 0)
    ledger.report(JOB, node, gen, "downloading", 1, received=3, total=9)
    return ledger, node, gen


def test_roundtrip_marks_running_jobs_ambiguous_and_keeps_owner_only_mode(tmp_path):
    store = LedgerStore(tmp_path / "state")
    assert store.load() is None
    ledger, _node, gen = running_ledger()
    store.save(ledger)
    loaded = store.load()
    assert loaded.jobs[JOB].ambiguous and loaded.jobs[JOB].generation == gen
    with pytest.raises(ma.LedgerError, match="assignable"):
        loaded.assign(JOB, "n2", 5)  # a reboot alone never causes a second download
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "state").stat().st_mode & 0o077 == 0
    assert not list((tmp_path / "state").glob(".*.tmp"))


def test_completed_enqueue_is_remembered_across_restarts(tmp_path):
    store = LedgerStore(tmp_path)
    ledger, node, gen = running_ledger()
    ledger.finished(JOB, node, gen, CONTENT, 2)
    assert ledger.enqueue_once(JOB, CONTENT)
    store.save(ledger)
    assert store.load().enqueue_once(JOB, CONTENT) is False


@pytest.mark.parametrize("point", ["tmp_written", "replaced"])
def test_crash_during_save_leaves_old_or_new_complete_snapshot(tmp_path, point):
    old, *_ = running_ledger()
    LedgerStore(tmp_path).save(old)
    new = ma.AssignmentLedger()
    new.create("job-00000002", ma.source_key("magnet", "a" * 40), 0)

    def crash(step):
        if step == point:
            raise Crash(step)

    with pytest.raises(Crash):
        LedgerStore(tmp_path, hook=crash).save(new)
    survivor = LedgerStore(tmp_path).load()
    assert set(survivor.jobs) in ({JOB}, {"job-00000002"})  # whole, never merged or torn


def test_disk_full_leaves_previous_snapshot_and_no_temp_file(tmp_path):
    ledger, *_ = running_ledger()
    store = LedgerStore(tmp_path)
    store.save(ledger)
    ledger.create("job-00000002", ma.source_key("magnet", "b" * 40), 1)
    with mock.patch.object(os, "fsync", side_effect=OSError(errno.ENOSPC, "full")):
        with pytest.raises(ma.LedgerError, match="cannot persist"):
            store.save(ledger)
    assert set(store.load().jobs) == {JOB}
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("junk", [b"", b"{", b"[]", b"\xff\xfe", b'{"v": 2, "jobs": []}',
                                  b'{"v": 1, "jobs": [{"job_id": "x"}]}', b"9" * 100])
def test_damaged_file_is_never_treated_as_an_empty_ledger(tmp_path, junk):
    store = LedgerStore(tmp_path)
    store.path.write_bytes(junk)
    with pytest.raises(ma.LedgerError):
        store.load()
    ledger, problem = store.load_or_quarantine()
    assert problem and not ledger.jobs
    assert not store.path.exists()
    assert len(list(tmp_path.glob(NAME + ".corrupt-*"))) == 1  # kept for inspection


def test_oversized_file_and_symlink_are_refused(tmp_path):
    store = LedgerStore(tmp_path)
    store.path.write_bytes(b" " * (4 << 20) + b"x")
    with pytest.raises(ma.LedgerError, match="oversized"):
        store.load()
    store.path.unlink()
    if hasattr(os, "O_NOFOLLOW"):
        target = tmp_path / "elsewhere.json"
        target.write_text("{}")
        store.path.symlink_to(target)
        with pytest.raises(ma.LedgerError):
            store.load()


def test_missing_file_gives_an_empty_ledger_without_a_warning(tmp_path):
    ledger, problem = LedgerStore(tmp_path / "new").load_or_quarantine()
    assert problem is None and not ledger.jobs
