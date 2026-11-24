"""Headless regressions for damaged and oversized room checkpoints."""
import json
import sys

import pytest

import room_checkpoint as rc


def test_deep_json_is_reported_without_escaping_recovery(tmp_path):
    path = tmp_path / "room.json"
    depth = 10_000
    path.write_text("[" * depth + "]" * depth, encoding="utf-8")
    assert rc.load_checkpoint(path).error == "Checkpoint could not be read"


def test_integer_conversion_limit_is_reported(tmp_path):
    limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
    if not limit:
        pytest.skip("Python integer conversion limit is not enabled")
    path = tmp_path / "room.json"
    path.write_text('{"schema_version": ' + "9" * (limit + 1) + '}', encoding="utf-8")
    assert rc.load_checkpoint(path).error == "Checkpoint could not be read"


def test_escaped_unicode_size_limit_preserves_previous_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "room.json"
    rc.write_checkpoint(path, [])
    old = path.read_bytes()
    item = str(tmp_path / ("\U0001f600" * 40 + ".mkv"))
    (tmp_path / ("\U0001f600" * 40 + ".mkv")).write_bytes(b"media")
    payload = {"schema_version": rc.SCHEMA_VERSION, "items": [item]}
    encoded_size = len(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(rc, "MAX_CHECKPOINT_BYTES", encoded_size - 1)
    with pytest.raises(ValueError, match="supported limit"):
        rc.write_checkpoint(path, [item])
    assert path.read_bytes() == old
    monkeypatch.setattr(rc, "MAX_CHECKPOINT_BYTES", encoded_size)
    rc.write_checkpoint(path, [item])
    assert len(path.read_bytes()) == encoded_size
    assert rc.load_checkpoint(path).items == (item,)


def test_writer_consumes_at_most_limit_plus_one(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "MAX_ITEMS", 2)

    def items():
        for _ in range(3):
            yield str(tmp_path / "film.mkv")
        pytest.fail("writer consumed beyond its item limit")

    with pytest.raises(ValueError, match="checkpoint limit"):
        rc.write_checkpoint(tmp_path / "room.json", items())
