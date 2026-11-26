"""Freeze the HLS worker to the launch generation so a mid-session pull can't mix code."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamer
import streamer_generation as sg


def _write_source(root: Path) -> None:
    (root / "server.py").write_text(
        "import error_log\nimport stdlib_only\n", encoding="utf-8")
    (root / "error_log.py").write_text(
        "import command_trace\nimport log_jsonl\n", encoding="utf-8")
    (root / "command_trace.py").write_text("import log_jsonl\n", encoding="utf-8")
    (root / "log_jsonl.py").write_text("import json\n", encoding="utf-8")


def test_snapshot_copies_the_worker_and_its_local_closure(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_source(src)
    frozen = sg.freeze_worker(src / "server.py", tmp_path / "cache")
    assert frozen != src / "server.py"
    assert frozen.is_file() and frozen.parent.name.startswith(sg.GENERATION_PREFIX)
    names = {p.name for p in frozen.parent.glob("*.py")}
    assert {"server.py", "error_log.py", "command_trace.py", "log_jsonl.py"} <= names
    assert not (frozen.parent / "stdlib_only.py").exists()


def test_snapshot_file_is_immutable_once_written(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_source(src)
    cache = tmp_path / "cache"
    frozen = sg.freeze_worker(src / "server.py", cache)
    baseline = frozen.read_bytes()
    (src / "server.py").write_text("import error_log\n# pulled\n", encoding="utf-8")
    # The already-written generation is untouched; a fresh freeze is a new one.
    assert frozen.is_file() and frozen.read_bytes() == baseline
    assert sg.freeze_worker(src / "server.py", cache) != frozen


def test_snapshot_is_idempotent_and_generation_keyed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _write_source(src)
    cache = tmp_path / "cache"
    first = sg.freeze_worker(src / "server.py", cache)
    assert sg.freeze_worker(src / "server.py", cache) == first
    (src / "error_log.py").write_text("import command_trace\n", encoding="utf-8")
    second = sg.freeze_worker(src / "server.py", cache)
    assert second != first and second.is_file()


def test_unwritable_cache_falls_back_to_the_live_script(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _write_source(src)
    monkeypatch.setattr(sg.shutil, "rmtree", lambda *_a, **_k: None)
    monkeypatch.setattr(sg.os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("ro")))
    assert sg.freeze_worker(src / "server.py", tmp_path / "cache") == src / "server.py"


def test_is_frozen_worker_only_accepts_the_snapshot_shape():
    assert sg.is_frozen_worker(f"/home/u/.cache/cast-control/{sg.GENERATION_PREFIX}0123456789ab/server.py")
    assert sg.is_frozen_worker(r"C:\u\.cache\cast-control\hls-generation-0123456789ab\server.py")
    assert not sg.is_frozen_worker(f"/home/u/.cache/cast-control/{sg.GENERATION_PREFIX}a/server.py")
    assert not sg.is_frozen_worker("/repo/src/server.py")
    assert not sg.is_frozen_worker(f"/x/{sg.GENERATION_PREFIX}a/other.py")
    assert not sg.is_frozen_worker("server.py")


def test_streamer_launches_from_the_frozen_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(streamer, "ROOT", tmp_path / "cache")
    monkeypatch.setattr(streamer, "_frozen_server_script", None)
    script = streamer._hls_server_script()
    assert sg.is_frozen_worker(script)
    assert streamer._hls_server_script() == script      # memoised once per process


def test_frozen_install_still_uses_the_bundled_server(monkeypatch):
    monkeypatch.setattr(streamer, "_frozen_server_script", None)
    monkeypatch.setattr(streamer.frozen_runtime, "is_frozen", lambda: True)
    assert streamer._hls_server_script() == str(streamer.SERVER_SCRIPT)
