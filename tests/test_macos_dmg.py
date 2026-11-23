"""No macOS tools, GUI or receiver needed for the DMG packaging contract."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "build_macos_dmg.py"
SPEC = importlib.util.spec_from_file_location("build_macos_dmg", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def app_dist(tmp_path: Path) -> Path:
    app = tmp_path / "SmoothCast.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_text("plist", encoding="utf-8")
    return tmp_path


def test_requires_macos(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="macOS"):
        module.build(tmp_path, system="Linux")


def test_requires_valid_bundle(tmp_path: Path) -> None:
    (tmp_path / "SmoothCast.app").mkdir()
    with pytest.raises(FileNotFoundError, match="bundle"):
        module.build(tmp_path, system="Darwin")


def test_success_checksum_and_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = app_dist(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[-1]).write_bytes(b"compressed-image")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    dest = module.build(dist, system="Darwin")
    assert dest.read_bytes() == b"compressed-image"
    assert (dist / "smoothcast-macos.dmg.sha256").read_text() == (
        hashlib.sha256(b"compressed-image").hexdigest() + "  smoothcast-macos.dmg\n"
    )
    assert calls[0][0][:2] == ["hdiutil", "create"]
    assert calls[0][1]["timeout"] == 300
    assert not (dist / ".smoothcast-macos.partial.dmg").exists()


def test_failing_hdiutil_removes_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = app_dist(tmp_path)

    def failing_run(args, **kwargs):
        Path(args[-1]).write_bytes(b"incomplete")
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(module.subprocess, "run", failing_run)
    with pytest.raises(subprocess.CalledProcessError):
        module.build(dist, system="Darwin")
    assert not list(dist.glob("*.dmg"))
    assert not list(dist.glob("*.sha256"))


def test_no_partial_success_or_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = app_dist(tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="nonempty"):
        module.build(dist, system="Darwin")
    (dist / "smoothcast-macos.dmg").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        module.build(dist, system="Darwin")
    assert (dist / "smoothcast-macos.dmg").read_bytes() == b"keep"
