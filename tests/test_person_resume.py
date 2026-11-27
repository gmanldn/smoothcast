import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import person_resume as pr


def test_residents_are_independent_and_guests_never_write():
    s = pr.ResumeStore("A")
    assert s.record("sam", "film", 600, 6000, 1) and s.record("mum", "film", 1200, 6000, 2)
    assert s.get("sam", "film")["pos"] == 600 and s.get("mum", "film")["pos"] == 1200
    assert not s.record(None, "film", 900, 6000, 3) and s.get("sam", "film")["pos"] == 600


def test_source_time_after_speed_change_and_prompt_text():
    assert pr.source_position(600, 1.5, 100) == 1000
    s = pr.ResumeStore("A"); s.record("sam", "f", 4360, 9000, 1)
    assert s.prompt("sam", "f") == "Resume from 1:12:40" and s.prompt("sam", "x") is None


def test_finished_or_barely_started_clears_point():
    s = pr.ResumeStore("A"); s.record("sam", "f", 600, 1000, 1)
    s.record("sam", "f", 960, 1000, 2); assert s.get("sam", "f") is None
    s.record("sam", "f", 5, 1000, 3); assert s.get("sam", "f") is None


def test_merge_newest_wins_tiebreak_idempotent_and_no_regression():
    a, b = pr.ResumeStore("A"), pr.ResumeStore("B")
    a.record("sam", "f", 100, 1000, 10); b.record("sam", "f", 500, 1000, 20)
    assert a.apply(b.delta()) == 1 and a.get("sam", "f")["pos"] == 500
    assert a.apply(b.delta()) == 0                                   # idempotent
    assert b.apply(a.delta()) == 0
    old = [{"resident": "sam", "content_key": "f", "pos": 50, "dur": 1000, "updated_at": 5, "node_id": "C"}]
    assert a.apply(old) == 0 and a.get("sam", "f")["pos"] == 500     # stale peer can't regress
    t1 = [{"resident": "sam", "content_key": "g", "pos": 1, "dur": 100, "updated_at": 7, "node_id": "A"}]
    t2 = [{**t1[0], "pos": 2, "node_id": "B"}]
    x, y = pr.ResumeStore("X"), pr.ResumeStore("Y")
    x.apply(t1); x.apply(t2); y.apply(t2); y.apply(t1)
    assert x.records == y.records                                     # order independent


def test_bad_records_dropped_eviction_and_continue_order():
    s = pr.ResumeStore("A")
    assert s.apply([{"resident": "r"}, {"resident": "r", "content_key": "k", "pos": 9, "dur": 5, "updated_at": 1, "node_id": "B"}]) == 0
    for i in range(pr.MAX_PER_RESIDENT + 5):
        s.record("sam", f"k{i}", 100, 1000, i + 1)
    assert len(s.records["sam"]) == pr.MAX_PER_RESIDENT and s.get("sam", "k0") is None
    assert s.continue_row("sam", 1)[0]["content_key"] == f"k{pr.MAX_PER_RESIDENT + 4}"
    s.forget_resident("sam"); assert s.continue_row("sam") == []
