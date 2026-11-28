"""Contract test: every QueuePort implementation behaves the same (#691)."""
import pytest

from room_events import QueuePort, QueueState, QueueStore


class FakeQueue:
    """Smallest correct QueuePort: a list and a revision, no event log."""

    def __init__(self):
        self.state = QueueState([], 0)
        self._seen = {}

    def submit(self, command_id, kind, *args, expected_revision=None):
        if command_id in self._seen:
            return self._seen[command_id]
        if expected_revision is not None and expected_revision != self.state.revision:
            return ()
        items = self.state.items
        before = list(items)
        if kind == "add":
            items.extend(p for p in args[0] if p not in items)
        elif kind == "remove":
            if 0 <= args[0] < len(items):
                items.pop(args[0])
        elif kind == "move":
            index, pos = args
            if 0 <= index < len(items) and 0 <= pos < len(items):
                items.insert(pos, items.pop(index))
        elif kind == "clear":
            items.clear()
        else:
            raise ValueError(kind)
        changed = (1,) if items != before else ()
        if changed:
            self.state.revision += 1
        self._seen[command_id] = changed
        return changed


@pytest.fixture(params=[QueueStore, FakeQueue], ids=["store", "fake"])
def port(request) -> QueuePort:
    return request.param()


def test_add_dedupes_and_orders(port):
    port.submit("1", "add", ["a", "b"])
    port.submit("2", "add", ["b", "c"])
    assert list(port.state.items) == ["a", "b", "c"]


def test_move_remove_clear(port):
    port.submit("1", "add", ["a", "b", "c"])
    port.submit("2", "move", 2, 0)
    assert list(port.state.items) == ["c", "a", "b"]
    port.submit("3", "remove", 1)
    assert list(port.state.items) == ["c", "b"]
    port.submit("4", "clear")
    assert list(port.state.items) == []


def test_command_ids_are_idempotent(port):
    port.submit("1", "add", ["a"])
    port.submit("1", "add", ["z"])
    assert list(port.state.items) == ["a"]


def test_revision_fence_rejects_stale_edit(port):
    port.submit("1", "add", ["a"])
    rev = port.state.revision
    port.submit("2", "add", ["b"])
    assert port.submit("3", "clear", expected_revision=rev) == ()
    assert list(port.state.items) == ["a", "b"]
