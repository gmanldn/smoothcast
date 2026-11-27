import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_undo as qu


def test_undo_reorder_restores_exact_order_once():
    u = qu.UndoLog(); b, a = ["x", "y", "z"], ["z", "x", "y"]
    u.record("move", "z", b, a, 5)
    assert u.undo(a, 5) == (b, "")
    assert u.undo(b, 6) == (None, "Nothing to undo.")


def test_conflicting_later_edit_rejects_without_mutation():
    u = qu.UndoLog(); u.record("remove", "y", ["x", "y"], ["x"], 3)
    res, why = u.undo(["x", "q"], 4)
    assert res is None and "changed" in why
    assert u.undo(["x"], 3) == (["x", "y"], "")


def test_removed_media_unavailable_and_noop_or_bad_ops_ignored():
    u = qu.UndoLog(); u.record("remove", "y", ["x", "y"], ["x"], 3)
    assert u.undo(["x"], 3, available={"x"})[0] is None
    assert len(u._log) == 1
    u.record("clear", "", ["a"], [], 9); u.record("move", "a", ["a"], ["a"], 9)
    assert len(u._log) == 1


def test_history_bounded_and_clearable():
    u = qu.UndoLog()
    for i in range(qu.MAX_HISTORY + 5):
        u.record("add", str(i), [], [str(i)], i)
    assert len(u._log) == qu.MAX_HISTORY
    u.clear(); assert u.undo([], 0)[0] is None
