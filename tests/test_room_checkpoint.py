"""Room checkpoints restore only still-readable local queue files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

import cache_privacy
import room_checkpoint


def test_ten_item_queue_order_round_trips_without_session_data(tmp_path):
    items = []
    for index in range(10):
        item = tmp_path / f"film-{index}.mkv"
        item.write_bytes(f"media-{index}".encode())
        items.append(str(item))
    checkpoint = tmp_path / "private" / "room-checkpoint.json"

    room_checkpoint.write_checkpoint(checkpoint, items)
    result = room_checkpoint.load_checkpoint(checkpoint)

    assert result.items == tuple(items)
    assert result.unavailable == 0
    raw = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert set(raw) == {"schema_version", "items"}
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    if os.name != "nt":
        assert stat.S_IMODE(checkpoint.parent.stat().st_mode) == 0o700


def test_missing_nonregular_and_invalid_references_are_skipped(tmp_path):
    media = tmp_path / "available.mkv"
    media.write_bytes(b"movie")
    folder = tmp_path / "folder"
    folder.mkdir()
    partial = tmp_path / "interrupted.partial"
    partial.write_bytes(b"partial upload")
    checkpoint = tmp_path / "room.json"
    checkpoint.write_text(json.dumps({
        "schema_version": room_checkpoint.SCHEMA_VERSION,
        "items": [str(media), str(tmp_path / "missing.mkv"), str(folder), str(partial),
                  "relative.mkv", "\x00invalid", None],
    }), encoding="utf-8")

    result = room_checkpoint.load_checkpoint(checkpoint)

    assert result.items == (str(media),)
    assert result.unavailable == 6


def test_corrupt_and_unsupported_checkpoints_are_reported(tmp_path):
    checkpoint = tmp_path / "room.json"
    checkpoint.write_text("{broken", encoding="utf-8")
    assert room_checkpoint.load_checkpoint(checkpoint).error == "Checkpoint could not be read"
    checkpoint.write_text(json.dumps({"schema_version": 999, "items": []}), encoding="utf-8")
    assert room_checkpoint.load_checkpoint(checkpoint).error == "Checkpoint version is unsupported"


def test_failed_atomic_checkpoint_write_keeps_previous_queue(tmp_path, monkeypatch):
    checkpoint = tmp_path / "room.json"
    room_checkpoint.write_checkpoint(checkpoint, [str(tmp_path / "film.mkv")])
    previous = checkpoint.read_bytes()
    def fail_replace(_source, _target):
        raise OSError("injected")

    monkeypatch.setattr(cache_privacy.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected"):
        room_checkpoint.write_checkpoint(checkpoint, [str(tmp_path / "new.mkv")])

    assert checkpoint.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [checkpoint]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires a POSIX FIFO")
def test_non_file_checkpoint_is_rejected_without_blocking(tmp_path, monkeypatch):
    checkpoint = tmp_path / "room.json"
    os.mkfifo(checkpoint)
    open_descriptor = os.open

    def checked_open(path, flags, *args, **kwargs):
        if path == checkpoint:
            assert flags & os.O_NONBLOCK
        return open_descriptor(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked_open)
    assert room_checkpoint.load_checkpoint(checkpoint).error == "Checkpoint is not a regular file"


def test_checkpoint_rejects_nonlocal_urls_and_unbounded_queue(tmp_path):
    with pytest.raises(ValueError, match="absolute local file paths"):
        room_checkpoint.write_checkpoint(tmp_path / "room.json", ["https://example.test/movie.mkv"])
    with pytest.raises(ValueError, match="checkpoint limit"):
        room_checkpoint.write_checkpoint(
            tmp_path / "room.json", [str(tmp_path / "film.mkv")] * (room_checkpoint.MAX_ITEMS + 1),
        )
    with pytest.raises(ValueError, match="absolute local file paths"):
        room_checkpoint.write_checkpoint(tmp_path / "room.json", ["/movie/\x00invalid"])


def test_checkpoint_module_is_in_the_installed_wheel_manifest():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert '"room_checkpoint"' in pyproject.read_text(encoding="utf-8")
