"""Rollback contract tests for project virtualenv repair (P0 SC-018).

Everything runs under temporary directories with mocked subprocess probes:
no native packages, GUI, pip, or user environment is touched.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "setup"))
import bootstrap


def fake_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if bootstrap.os.name == "nt"
                   else "bin/python")


def existing(root: Path) -> Path:
    python = fake_python(root)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"old runtime")
    (root / "do-not-lose.txt").write_text("precious prior install")
    return python


def replacements(command, **kwargs):
    args = list(map(str, command))
    if "venv" in args:
        root = Path(args[-1])
        python = fake_python(root)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes(b"new runtime")
        (root / "new.txt").write_text("partial replacement")
    elif "pip" in args:
        raise bootstrap.SetupError("simulated pip outage")


def check_works(root, python, code, *, env=None):
    # The original interpreter is not GTK-compatible; replacement is.
    if code == bootstrap.GUI_CHECK:
        return (root / "new.txt").exists()
    if code == bootstrap.CAST_DEPENDENCIES_CHECK:
        return False
    return False


def test_failed_pip_rebuild_restores_exact_previous_install():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        old_python = existing(root)
        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "works",
                               side_effect=lambda python, code, env=None:
                                   check_works(root, python, code, env=env)), \
             mock.patch.object(bootstrap, "checked_run", side_effect=replacements):
            with pytest.raises(bootstrap.SetupError, match="simulated pip outage"):
                bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert old_python.read_bytes() == b"old runtime"
        assert (root / "do-not-lose.txt").read_text() == "precious prior install"
        assert not (root / "new.txt").exists()
        assert not list(root.parent.glob(".venv-incompatible-*"))


def test_failed_native_venv_creation_restores_previous_install():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        old_python = existing(root)

        def fail_create(command, **kwargs):
            if "venv" in command:
                replacement = Path(command[-1])
                replacement.mkdir(parents=True, exist_ok=True)
                (replacement / "partial").touch()
            raise bootstrap.SetupError("venv creation failed")

        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "works", return_value=False), \
             mock.patch.object(bootstrap, "checked_run", side_effect=fail_create):
            with pytest.raises(bootstrap.SetupError, match="venv creation failed"):
                bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert old_python.read_bytes() == b"old runtime"
        assert (root / "do-not-lose.txt").exists()
        assert not (root / "partial").exists()


def test_failed_media_verification_rolls_back_after_successful_pip():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        existing(root)
        state = {"pip": False}

        def good_create(command, **kwargs):
            args = list(map(str, command))
            if "venv" in args:
                replacement = Path(args[-1])
                executable = fake_python(replacement)
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.touch()
                (replacement / "new.txt").touch()
            if "pip" in args:
                state["pip"] = True

        def probe(_python, code, *, env=None):
            return (root / "new.txt").exists() if code == bootstrap.GUI_CHECK else state["pip"]

        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "works", side_effect=probe), \
             mock.patch.object(bootstrap, "checked_run", side_effect=good_create), \
             mock.patch.object(bootstrap, "check_tools", return_value=["ffmpeg (missing)"]):
            with pytest.raises(bootstrap.SetupError, match="Media dependencies are missing"):
                bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert (root / "do-not-lose.txt").exists()
        assert not (root / "new.txt").exists()


def test_brand_new_failed_setup_cleans_only_its_own_partial_environment():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        assert not root.exists()

        def fail(command, **kwargs):
            root.mkdir()
            (root / "partial").touch()
            raise bootstrap.SetupError("no venv module")

        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "checked_run", side_effect=fail):
            with pytest.raises(bootstrap.SetupError, match="no venv module"):
                bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert not root.exists()


def test_preexisting_directory_with_no_python_is_preserved_on_failure():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        root.mkdir()
        (root / "unknown-data.txt").write_text("keep me")

        def fail(command, **kwargs):
            root.mkdir()
            (root / "partial").touch()
            raise bootstrap.SetupError("failure")

        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "checked_run", side_effect=fail):
            with pytest.raises(bootstrap.SetupError, match="failure"):
                bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert (root / "unknown-data.txt").read_text() == "keep me"
        assert not (root / "partial").exists()


def test_successful_rebuild_keeps_prior_environment_as_inspectable_backup():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / ".venv"
        existing(root)

        def create(command, **kwargs):
            if "venv" in command:
                python = fake_python(root)
                python.parent.mkdir(parents=True, exist_ok=True)
                python.write_bytes(b"new runtime")
                (root / "new.txt").touch()

        with mock.patch.object(bootstrap, "VENV", root), \
             mock.patch.object(bootstrap, "venv_python",
                               side_effect=lambda: fake_python(root)), \
             mock.patch.object(bootstrap, "works",
                               side_effect=lambda python, code, env=None:
                                   (root / "new.txt").exists()), \
             mock.patch.object(bootstrap, "checked_run", side_effect=create), \
             mock.patch.object(bootstrap, "check_tools", return_value=[]):
            result = bootstrap.ensure_venv(Path(sys.executable), {}, check=False)
        assert result == fake_python(root)
        assert (root / "new.txt").exists()
        backups = list(root.parent.glob(".venv-incompatible-*"))
        assert len(backups) == 1
        assert (backups[0] / "do-not-lose.txt").read_text() == "precious prior install"
