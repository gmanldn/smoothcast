"""Malformed advisory state must never abort receiver planning (#514)."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receiver_memory import Outcome, ReceiverMemory  # noqa: E402

KEY = "a" * 64
SIGNATURE = "b" * 64


def payload(timestamp):
    return json.dumps({"schema": 1, "receivers": {
        KEY: {SIGNATURE: [{"mode": "direct", "ok": False, "at": timestamp}]}
    }}).encode()


@pytest.mark.parametrize("data", [
    payload(10 ** 400),
    payload(-(10 ** 400)),
    b"[" * 20000 + b"0" + b"]" * 20000,
    payload(float("inf")),
    payload(float("nan")),
])
def test_corrupt_state_is_quarantined_and_ignored(tmp_path, data):
    path = tmp_path / "receiver_memory.json"
    path.write_bytes(data)
    store = ReceiverMemory(path)
    assert store._read() == {}
    assert not path.exists()
    assert path.with_name(path.name + ".corrupt").read_bytes() == data
    assert store._read() == {}
    path.write_bytes(payload(100.0))
    assert store._read() == {KEY: {SIGNATURE: [Outcome("direct", False, 100.0)]}}


def test_valid_state_preserved(tmp_path):
    path = tmp_path / "receiver_memory.json"
    data = payload(100.0)
    path.write_bytes(data)
    assert ReceiverMemory(path)._read() == {
        KEY: {SIGNATURE: [Outcome("direct", False, 100.0)]}}
    assert path.read_bytes() == data
    assert not path.with_name(path.name + ".corrupt").exists()
