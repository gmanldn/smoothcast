"""Trusted media-tool resolution for the frozen Windows build (#530). GTK-free."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import errors
import media_tools

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def frozen_windows(tmp_path, monkeypatch):
    root = tmp_path / "Smooth Cast ünï"          # spaces and non-ASCII are legal install paths
    (root / "ffmpeg").mkdir(parents=True)
    monkeypatch.setattr(media_tools, "_strict", lambda: True)
    monkeypatch.setattr(media_tools, "_install_root", lambda: root)
    return root


def _ship(root, *names):
    for name in names:
        (root / "ffmpeg" / f"{name}.exe").write_bytes(b"MZ")


def test_source_mode_keeps_the_bare_name_and_path_lookup(monkeypatch):
    monkeypatch.setattr(media_tools, "_strict", lambda: False)
    monkeypatch.setattr(media_tools.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert media_tools.resolve_media_tool("ffmpeg") == "ffmpeg"
    assert media_tools.find_media_tool("ffprobe") == "/usr/bin/ffprobe"


def test_frozen_windows_uses_the_shipped_absolute_path_never_path(frozen_windows, monkeypatch):
    _ship(frozen_windows, "ffmpeg", "ffprobe", "ffplay")
    hostile = []
    monkeypatch.setattr(media_tools.shutil, "which", lambda name: hostile.append(name) or "C:/evil/ffmpeg.exe")
    for name in media_tools.TOOLS:
        path = Path(media_tools.resolve_media_tool(name))
        assert path.is_absolute() and path.name == f"{name}.exe"
        assert path.parent == (frozen_windows / "ffmpeg").resolve()
        assert media_tools.find_media_tool(name) == str(path)
    assert hostile == []                           # PATH was never consulted


def test_missing_sidecar_fails_closed_with_a_catalogued_error(frozen_windows, monkeypatch):
    monkeypatch.setattr(media_tools.shutil, "which", lambda name: "C:/ambient/ffmpeg.exe")
    with pytest.raises(media_tools.MediaToolMissing) as caught:
        media_tools.resolve_media_tool("ffmpeg")
    assert caught.value.code == media_tools.MISSING_CODE in errors.CATALOGUE
    assert isinstance(caught.value, FileNotFoundError)   # existing "not installed" handling still applies
    assert "Reinstall SmoothCast" in caught.value.user_message
    assert media_tools.find_media_tool("ffmpeg") is None   # no ambient fallback either


def test_a_sidecar_that_resolves_outside_the_install_folder_is_refused(frozen_windows, tmp_path):
    outside = tmp_path / "elsewhere.exe"
    outside.write_bytes(b"MZ")
    link = frozen_windows / "ffmpeg" / "ffmpeg.exe"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(media_tools.MediaToolMissing):
        media_tools.resolve_media_tool("ffmpeg")


def test_a_directory_named_like_a_tool_is_not_a_tool(frozen_windows):
    (frozen_windows / "ffmpeg" / "ffmpeg.exe").mkdir()
    with pytest.raises(media_tools.MediaToolMissing):
        media_tools.resolve_media_tool("ffmpeg")


def test_unknown_tool_names_are_rejected():
    for bad in ("sh", "ffmpeg.exe", "../ffmpeg", ""):
        with pytest.raises(ValueError):
            media_tools.resolve_media_tool(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            media_tools.find_media_tool(bad)  # type: ignore[arg-type]


def test_probe_reports_without_running_anything(frozen_windows):
    _ship(frozen_windows, "ffmpeg")
    report = media_tools.probe()
    assert report["strict"] is True and report["ok"] is False
    assert report["tools"]["ffmpeg"] and report["tools"]["ffprobe"] is None


def test_no_source_module_runs_a_media_tool_by_bare_name_or_path_lookup():
    """Regression detector: every command goes through media_tools."""
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        if path.name == "media_tools.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
                first = node.elts[0]
                second = node.elts[1] if len(node.elts) > 1 else None
                if (isinstance(first, ast.Constant) and first.value in media_tools.TOOLS
                        and isinstance(second, ast.Constant) and str(second.value).startswith("-")):
                    offenders.append(f"{path.name}:{node.lineno} raw argv")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "which" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in media_tools.TOOLS):
                offenders.append(f"{path.name}:{node.lineno} shutil.which")
    assert offenders == []


def _fake_run(outputs):
    import subprocess

    def run(argv, **_kw):
        name = Path(argv[0]).stem
        code, text = outputs.get(name, (0, ""))
        return subprocess.CompletedProcess(argv, code, stdout=text, stderr="")
    return run


def test_report_checks_versions_without_paths(frozen_windows):
    _ship(frozen_windows, "ffmpeg", "ffprobe", "ffplay")
    run = _fake_run({"ffmpeg": (0, "ffmpeg version 6.1.1-gyan Copyright\nmore"),
                     "ffprobe": (0, "ffprobe version 6.1.1"), "ffplay": (0, "ffplay version 6.1.1")})
    result = media_tools.report(run=run)
    assert result["ok"] is True and result["strict"] is True
    assert result["tools"]["ffmpeg"]["version"].startswith("ffmpeg version 6.1.1")
    assert str(frozen_windows) not in str(result)


def test_report_names_each_problem_and_fails(frozen_windows):
    _ship(frozen_windows, "ffmpeg", "ffprobe")           # ffplay deliberately absent
    run = _fake_run({"ffmpeg": (0, "ffmpeg version 4.4.2"), "ffprobe": (1, "")})
    result = media_tools.report(run=run)
    tools = result["tools"]
    assert result["ok"] is False
    assert tools["ffmpeg"]["problem"] == "needs FFmpeg 5.0 or newer"
    assert tools["ffprobe"]["ok"] is False
    assert tools["ffplay"] == {"found": False, "version": "", "ok": False, "problem": "missing"}


def test_report_survives_a_tool_that_cannot_start(frozen_windows):
    _ship(frozen_windows, "ffmpeg", "ffprobe", "ffplay")

    def run(*_a, **_k):
        raise OSError("blocked")
    result = media_tools.report(run=run)
    assert result["ok"] is False
    assert all(e["problem"] == "OSError" for e in result["tools"].values())
