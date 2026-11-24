"""Offline tests of installed refresh; no GUI, package manager, or network."""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import checkout_refresh as refresh


SHA = "a" * 40


def version(root, patch):
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "version.py").write_text(
        f"MAJOR = 2\nMINOR = 0\nPATCH = {patch}\n", encoding="utf-8")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    source, installed = tmp_path / "checkout", tmp_path / "installed"
    version(source, 3)
    version(installed, 2)
    monkeypatch.setattr(refresh.install_location, "_clean_source_revision", lambda _: SHA)
    def git(_root, *args):
        return Mock(returncode=0, stdout="develop" if args[0] == "symbolic-ref" else SHA)
    monkeypatch.setattr(refresh, "git", git)
    return source, installed


def test_refreshes_old_install_and_verifies_identity(roots, monkeypatch):
    source, installed = roots
    def bootstrap(_args):
        version(installed, 3)
        (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
        return 0
    call = Mock(side_effect=bootstrap)
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    call.assert_called_once()
    assert str(installed) in call.call_args.args[0]


def test_never_downgrades_newer_install(roots, monkeypatch):
    source, installed = roots
    version(installed, 4)
    call = Mock()
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    call.assert_not_called()


def test_running_gui_is_not_overwritten(roots, monkeypatch):
    source, installed = roots
    call = Mock()
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: [123]) == 3
    call.assert_not_called()


def test_success_without_new_files_is_refused(roots, monkeypatch):
    source, installed = roots
    monkeypatch.setattr(refresh.subprocess, "call", Mock(return_value=0))
    assert refresh.refresh(source, installed, "linux", lambda: []) == 1


def test_dirty_checkout_is_not_installed(roots, monkeypatch):
    source, installed = roots
    monkeypatch.setattr(refresh.install_location, "_clean_source_revision", lambda _: None)
    call = Mock()
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 1
    call.assert_not_called()


def test_exact_installed_revision_skips_reinstall(roots, monkeypatch):
    source, installed = roots
    version(installed, 3)
    (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
    call = Mock()
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    call.assert_not_called()
