"""Runtime-binding regression tests; no GTK, receiver or desktop process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import bootstrap
import launch
import native_runtime


def fake_platform(tmp: Path, name: str):
    prefix = tmp / ("My Homebrew Prefix" if name == "macos" else "MSYS2 With Spaces")
    python = (prefix / "bin" / "python3" if name == "macos"
              else prefix / "ucrt64" / "bin" / "python.exe")
    python.parent.mkdir(parents=True)
    python.touch()
    if name == "macos":
        brew = prefix / "bin" / "brew"
        brew.touch()
    return prefix, python


def test_macos_launcher_uses_saved_prefix_not_path_or_default():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        prefix, python = fake_platform(temp, "macos")
        venv = temp / "Project With Spaces" / ".venv"
        native_runtime.save(
            venv, target="macos", native_python=python,
            env={"SMOOTHCAST_NATIVE_PREFIX": str(prefix)},
        )
        with mock.patch.object(launch, "VENV", venv):
            result = launch._runtime_environment_for(
                "macos", {"PATH": "/usr/bin", "HOME": str(temp)},
            )
            assert Path(result["PATH"].split(os.pathsep)[0]).resolve() == (prefix / "bin").resolve()
            assert Path(result["SMOOTHCAST_NATIVE_PREFIX"]).resolve() == prefix.resolve()
            (prefix / "bin" / "brew").unlink()
            try:
                launch._runtime_environment_for("macos", {"PATH": "/usr/bin"})
            except RuntimeError as exc:
                assert "Selected Homebrew prefix moved" in str(exc)
            else:
                raise AssertionError("Moved prefix must not silently fall back")


def test_windows_launcher_respects_recorded_msys2_even_with_foreign_environment():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        prefix, python = fake_platform(temp, "windows")
        venv = temp / ".venv"
        native_runtime.save(
            venv, target="windows", native_python=python,
            env={"MSYS2_ROOT": str(prefix)},
        )
        with mock.patch.object(launch, "VENV", venv):
            result = launch._runtime_environment_for(
                "windows", {"PATH": "fake", "MSYS2_ROOT": "/some/other/runtime"},
            )
            assert Path(result["MSYS2_ROOT"]).resolve() == prefix.resolve()
            assert Path(result["PYGI_DLL_PATH"]).resolve() == (prefix / "ucrt64" / "bin").resolve()
            assert Path(result["PATH"].split(os.pathsep)[0]).resolve() == (prefix / "ucrt64" / "bin").resolve()
            python.unlink()
            try:
                launch._runtime_environment_for("windows", {"PATH": "fake"})
            except RuntimeError as exc:
                assert "Selected native Python moved" in str(exc)
            else:
                raise AssertionError("Missing selected Python must not fall back")


def test_corrupt_manifest_fails_closed_and_legacy_install_still_runs():
    with tempfile.TemporaryDirectory() as directory:
        venv = Path(directory) / ".venv"
        assert native_runtime.load(venv, target="linux") is None
        path = native_runtime.manifest_path(venv)
        path.parent.mkdir()
        for payload in ('{', '{"format": 1, "target": "wrong", "native_python": "p"}',
                        '{"format": 1, "target": "macos", "native_python": "p", "prefix": null}'):
            path.write_text(payload, encoding="utf-8")
            try:
                native_runtime.load(venv, target="macos")
            except RuntimeError as exc:
                assert "Rerun the platform setup script" in str(exc)
            else:
                raise AssertionError("Invalid manifest must be rejected")


def test_setup_records_only_after_successful_verification():
    with tempfile.TemporaryDirectory() as directory:
        venv = Path(directory) / ".venv"
        venv.mkdir()
        chosen = Path(directory) / "Python With Spaces" / "bin" / "python3"
        chosen.parent.mkdir(parents=True)
        chosen.touch()
        with mock.patch.object(bootstrap, "VENV", venv), \
             mock.patch.object(bootstrap, "install_linux",
                               return_value=(chosen, {"PATH": "/usr/bin"})), \
             mock.patch.object(bootstrap, "ensure_venv",
                               return_value=venv / "bin" / "python"), \
             mock.patch.object(bootstrap.platform, "system", return_value="Linux"):
            assert bootstrap.main([
                "--target", "linux", "--in-place", "--no-shortcuts", "--check",
            ]) == 0
            assert not native_runtime.manifest_path(venv).exists()
            assert bootstrap.main([
                "--target", "linux", "--in-place", "--no-shortcuts",
            ]) == 0
        saved = json.loads(native_runtime.manifest_path(venv).read_text())
        assert saved["native_python"] == str(chosen)
        assert saved["target"] == "linux"


def test_launcher_handles_corrupt_record_without_spawning_gui():
    with tempfile.TemporaryDirectory() as directory:
        venv = Path(directory) / ".venv"
        venv.mkdir()
        native_runtime.manifest_path(venv).write_text("bad json")
        with mock.patch.object(launch, "VENV", venv), \
             mock.patch.object(launch, "python_path", return_value=Path(sys.executable)), \
             mock.patch.object(launch.os, "execvpe") as execvpe, \
             mock.patch.dict(os.environ, {"SMOOTHCAST_TEST_CONTEXT": "0"}):
            assert launch.main([]) == 1
        execvpe.assert_not_called()
