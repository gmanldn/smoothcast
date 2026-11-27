"""Headless strict GTK row contract for mesh churn (#707)."""
import ast
from pathlib import Path
from types import SimpleNamespace


def _update():
    source = Path(__file__).resolve().parents[1] / "src" / "mesh_ui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Section")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "update")
    namespace = {"vm": SimpleNamespace(Row=object)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["update"]


class Row:
    def __init__(self):
        self.parent = None

    def get_parent(self):
        return self.parent

    def get_index(self):
        assert self.parent is not None, "unattached row indexed"
        return self.parent.items.index(self)


class ListBox:
    def __init__(self):
        self.items = []
        self.mutations = 0

    def insert(self, item, index):
        assert item.parent is None, "row already parented"
        self.items.insert(index, item)
        item.parent = self
        self.mutations += 1

    def remove(self, item):
        assert item.parent is self, "non-child removal"
        self.items.remove(item)
        item.parent = None
        self.mutations += 1


def _section():
    return SimpleNamespace(list=ListBox(), rows={}, order=[],
                           _make=lambda _: (Row(), {}),
                           _fill=lambda *_: None)


def _apply(section, *keys):
    _update()(section, tuple(SimpleNamespace(key=k) for k in keys))
    assert section.list.items == [section.rows[k][0] for k in dict.fromkeys(keys)]
    assert section.order == list(dict.fromkeys(keys))


def test_initial_insert_reorder_remove_and_stable_rows():
    section = _section()
    _apply(section, "a", "b")
    a, b = (section.rows[k][0] for k in ("a", "b"))
    count = section.list.mutations
    _apply(section, "a", "b")
    assert section.list.mutations == count
    _apply(section, "b", "c", "a")
    assert section.rows["a"][0] is a and section.rows["b"][0] is b
    _apply(section, "a")
    assert b.parent is None
    _apply(section)
    _apply(section, "b")


def test_detached_or_foreign_row_and_duplicate_keys_are_safe():
    section = _section()
    _apply(section, "a", "b")
    a = section.rows["a"][0]
    section.list.remove(a)
    _apply(section, "a", "b")
    assert section.rows["a"][0] is a
    section.list.remove(a)
    other = ListBox()
    other.insert(a, 0)
    _apply(section, "a", "a", "b")
    assert other.items == [a]
    assert section.rows["a"][0] is not a
    b = section.rows["b"][0]
    section.list.remove(b)
    _apply(section, "a")
