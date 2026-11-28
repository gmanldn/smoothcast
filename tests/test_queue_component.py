from queue_component import QueueComponent


def test_add_skips_duplicates_and_keeps_list_identity():
    q: list[str] = ["a"]
    c = QueueComponent(q)
    assert c.add(["a", "b", "b", "c"]) == ["b", "c"] and q == ["a", "b", "c"] and c.paths is q


def test_remove_moves_selection_like_the_window_did():
    q = ["a", "b", "c"]
    c = QueueComponent(q)
    assert c.remove(0, 2) == ("a", 1)        # selection shifts up with its file
    assert c.remove(1, 1) == ("c", 0)        # removing the selected row picks a neighbour
    assert c.remove(0, 0) == ("b", None) and q == []


def test_remove_out_of_range_changes_nothing():
    q = ["a"]
    assert QueueComponent(q).remove(5, 0) == (None, 0) and QueueComponent(q).remove(-1, 0) == (None, 0) and q == ["a"]


def test_clear_and_reselect():
    q = ["a", "b"]
    c = QueueComponent(q)
    assert c.reselect(1) == 1 and c.reselect(2) is None and c.reselect(None) is None
    c.clear()
    assert q == [] and c.reselect(0) is None


def test_move_keeps_selection_on_same_path():
    q = ["a", "b", "c"]
    sel = QueueComponent(q).move(0, 2, 0)
    assert q == ["b", "c", "a"] and sel == 2
    assert QueueComponent(q).move(1, 0, None) is None and q == ["c", "b", "a"]
