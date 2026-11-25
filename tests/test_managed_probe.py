"""GUI-free health probe for staged generations (#580)."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import bootstrap
import managed_generations as mg
import managed_probe as mp

pytestmark = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"), reason="No race-safe staging primitive")

APP = "src/cast_control.py"


def generation(tmp_path: Path, *, with_venv: bool = False) -> Path:
    gen = tmp_path / "generation"
    (gen / "src").mkdir(parents=True)
    (gen / APP).write_text("# app\n")
    if with_venv:
        (gen / ".venv" / "bin").mkdir(parents=True)
        (gen / ".venv" / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
    return gen


def green() -> None:
    """Make every runtime check succeed without running real subprocesses."""
    mock.patch.object(bootstrap, "check_tools", return_value=[]).start()
    mock.patch.object(bootstrap, "python_ok", return_value=True).start()
    mock.patch.object(bootstrap, "works", return_value=True).start()


def test_probe_rejects_generation_without_app_entry(tmp_path):
    gen = tmp_path / "empty"
    gen.mkdir()
    with mock.patch.object(bootstrap, "works",
                           side_effect=AssertionError("no subprocess")):
        assert mp.default_probe(gen) is False


def test_probe_only_runs_import_only_checks(tmp_path):
    calls = []
    gen = generation(tmp_path)
    with mock.patch.object(bootstrap, "check_tools", return_value=[]), \
         mock.patch.object(bootstrap, "python_ok", return_value=True), \
         mock.patch.object(bootstrap, "works",
                           side_effect=lambda _p, code, **_: calls.append(code) or True):
        assert mp.default_probe(gen) is True
    assert calls == [bootstrap.GUI_CHECK, bootstrap.CAST_DEPENDENCIES_CHECK]


def test_probe_prefers_staged_venv_python(tmp_path):
    gen = generation(tmp_path, with_venv=True)
    seen = []
    with mock.patch.object(bootstrap, "check_tools", return_value=[]), \
         mock.patch.object(bootstrap, "python_ok", return_value=True), \
         mock.patch.object(bootstrap, "works",
                           side_effect=lambda p, _code, **_: seen.append(Path(p)) or True):
        assert mp.default_probe(gen) is True
    assert seen == [gen / ".venv" / "bin" / "python"] * 2


def test_probe_falls_back_to_current_interpreter(tmp_path):
    gen = generation(tmp_path)
    seen = []
    with mock.patch.object(bootstrap, "check_tools", return_value=[]), \
         mock.patch.object(bootstrap, "python_ok", return_value=True), \
         mock.patch.object(bootstrap, "works",
                           side_effect=lambda p, _code, **_: seen.append(Path(p)) or True):
        assert mp.default_probe(gen) is True
    assert seen == [Path(sys.executable)] * 2


@pytest.mark.parametrize("failing", ["python", "gui", "cast", "media"])
def test_probe_rejects_failed_runtime_check(tmp_path, failing):
    gen = generation(tmp_path)
    with mock.patch.object(bootstrap, "check_tools",
                           return_value=["ffmpeg (missing)"] if failing == "media" else []), \
         mock.patch.object(bootstrap, "python_ok", return_value=failing != "python"), \
         mock.patch.object(bootstrap, "works",
                           side_effect=[failing != "gui", failing != "cast"]):
        assert mp.default_probe(gen) is False


def test_default_probe_activates_a_staged_generation(tmp_path):
    root = tmp_path / "install"
    root.mkdir(mode=0o700)
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / APP).write_text("# app\n")
    data = (source / APP).read_bytes()
    commit = "a" * 40
    mg.stage_local_snapshot(root, source, commit, {
        APP: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}})
    green()
    try:
        import managed_activation as ma
        txn = ma.activate(root, commit, probe=mp.default_probe)
        ma.acknowledge(root, txn, commit)
        assert ma.read_active(root)["current"] == commit
    finally:
        mock.patch.stopall()
