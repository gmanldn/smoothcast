"""#207: the recent-error ring is safe under concurrent handlers and cannot be edited by callers."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import errors


def setup_function(_f):
    errors.reset_recent()


def test_ring_stays_bounded_and_keeps_the_newest_in_order():
    for i in range(50):
        errors.record("cast.receiver_offline", {"n": str(i)})
    rows = errors.recent()
    assert len(rows) == 20
    assert [r["context"]["n"] for r in rows] == [str(i) for i in range(30, 50)]


def test_exported_history_cannot_be_used_to_edit_the_stored_history():
    errors.record("cast.receiver_offline", {"device": "TV"})
    errors.recent()[0]["context"]["device"] = "tampered"
    errors.recent()[0]["code"] = "x"
    assert errors.recent()[0]["context"] == {"device": "TV"}
    assert errors.recent()[0]["code"] == "cast.receiver_offline"


def test_concurrent_record_reset_and_snapshot_never_raise():
    failures, stop = [], threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            errors.record("cast.receiver_offline", {"i": str(i)})
            i += 1

    def resetter():
        while not stop.is_set():
            errors.reset_recent()

    def reader():
        try:
            for _ in range(3000):
                rows = errors.recent()
                assert len(rows) <= 20 and all(r["code"] in errors.CATALOGUE for r in rows)
        except Exception as exc:  # noqa: BLE001
            failures.append(repr(exc))

    threads = [threading.Thread(target=writer) for _ in range(3)]
    threads += [threading.Thread(target=resetter)]
    readers = [threading.Thread(target=reader) for _ in range(3)]
    for t in threads + readers:
        t.start()
    for t in readers:
        t.join(timeout=30)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    assert failures == []


def test_unknown_codes_fall_back_and_context_is_clipped():
    errors.record("not.a.code", {f"k{i}": "v" * 500 for i in range(20)})
    row = errors.recent()[0]
    assert row["code"] == errors.FALLBACK.code
    assert len(row["context"]) <= 6 and all(len(v) <= 120 for v in row["context"].values())
