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

def test_current_build_announces_exact_version_and_local_scope(roots, monkeypatch, capsys):
    source, installed = roots
    version(installed, 3)
    (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    message = capsys.readouterr().err
    assert "Loading latest checked-out version v2.0.3" in message
    assert SHA[:12] in message
    assert "remote freshness not checked" in message


def test_refresh_announces_latest_only_after_copy_verification(roots, monkeypatch, capsys):
    source, installed = roots

    def bootstrap(_args):
        assert "Loading latest" not in capsys.readouterr().err
        version(installed, 3)
        (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
        return 0

    monkeypatch.setattr(refresh.subprocess, "call", bootstrap)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    assert "Loading latest local develop version v2.0.3" in capsys.readouterr().err


def test_failed_refresh_does_not_announce_latest(roots, monkeypatch, capsys):
    source, installed = roots
    monkeypatch.setattr(refresh.subprocess, "call", Mock(return_value=0))
    assert refresh.refresh(source, installed, "linux", lambda: []) == 1
    assert "Loading latest" not in capsys.readouterr().err

def test_recorded_source_resolves_only_separate_checkout(tmp_path):
    import json
    source = tmp_path / "My checkout"
    installed = tmp_path / "Installed"
    (source / ".git").mkdir(parents=True)
    (source / "setup").mkdir()
    (source / "setup" / "bootstrap.py").touch()
    (source / "pyproject.toml").write_text('name = "smoothcast"')
    (installed / "src").mkdir(parents=True)
    marker = installed / "src" / refresh.install_location.SOURCE_MARKER
    marker.write_text(json.dumps(str(source)))
    assert refresh.installed_source(installed) == source.resolve()
    for value in (str(installed), "relative", None, str(tmp_path / "missing")):
        marker.write_text(json.dumps(value))
        assert refresh.installed_source(installed) is None


def test_known_behind_checkout_cannot_launch_stale_copy(roots, monkeypatch, capsys):
    source, installed = roots
    version(installed, 3)
    (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
    def git(_root, *args):
        if args[0] == "symbolic-ref":
            return Mock(returncode=0, stdout="develop")
        if args[0] == "rev-parse":
            return Mock(returncode=0, stdout=("b" * 40 if "refs/remotes" in args[-1] else SHA))
        if args == ("merge-base", "--is-ancestor", "b" * 40, SHA):
            return Mock(returncode=1)
        return Mock(returncode=0)
    monkeypatch.setattr(refresh, "git", git)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 3
    assert "behind known origin/develop" in capsys.readouterr().err


@pytest.mark.parametrize("symbolic_ref", [
    Mock(returncode=1, stdout=""),            # detached HEAD (agent/worktree launch)
    Mock(returncode=0, stdout="main\n"),      # a checkout on another branch
])
def test_non_develop_checkout_is_never_refused_as_behind(roots, monkeypatch, capsys,
                                                         symbolic_ref):
    """Only a real develop checkout may be judged against origin/develop (#595)."""
    source, installed = roots
    version(installed, 3)
    (installed / "src" / refresh.install_location.BUILD_MARKER).write_text(SHA)
    def git(_root, *args):
        if args[0] == "symbolic-ref":
            return symbolic_ref
        if args[0] == "rev-parse":
            return Mock(returncode=0, stdout=("b" * 40 if "refs/remotes" in args[-1] else SHA))
        return Mock(returncode=0)
    monkeypatch.setattr(refresh, "git", git)
    # The install already matches the checkout, so this must simply launch.
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    assert "behind known origin/develop" not in capsys.readouterr().err


def test_higher_version_does_not_override_diverged_build(roots, monkeypatch):
    source, installed = roots
    (installed / "src" / refresh.install_location.BUILD_MARKER).write_text("b" * 40)
    def git(_root, *args):
        if args[0] == "merge-base":
            return Mock(returncode=1)
        return Mock(returncode=0, stdout="develop" if args[0] == "symbolic-ref" else SHA)
    monkeypatch.setattr(refresh, "git", git)
    call = Mock()
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 1
    call.assert_not_called()


@pytest.mark.parametrize("payload, expected", [
    (b"a" * 40, "a" * 40),
    (b"a" * 40 + b"\n2026-11-25\n", "a" * 40),
    (b"A" * 64 + b"\n2026-11-25\n", "a" * 64),
    (b"a" * 39, None),
    (b"g" * 40, None),
    (b"a" * 40 + b"x", None),
    (b"a" * 40 + b"\n" + b"x" * 128, None),
    (b"a" * 40 + b"\n\xff", None),
    (b"", None),
])
def test_refresh_marker_bounded_and_compatible(tmp_path, payload, expected):
    version(tmp_path, 3)
    marker = tmp_path / "src" / refresh.install_location.BUILD_MARKER
    marker.write_bytes(payload)
    assert refresh.installed_revision(tmp_path) == expected


def test_same_version_refresh_consumes_real_installer_marker(roots, monkeypatch):
    source, installed = roots
    version(installed, 3)
    marker = installed / "src" / refresh.install_location.BUILD_MARKER
    previous = "b" * 40
    marker.write_text(previous + "\n2026-11-24\n")

    def git(_root, *args):
        if args == ("merge-base", "--is-ancestor", SHA, previous):
            return Mock(returncode=1)
        return Mock(returncode=0, stdout=(
            "develop" if args[0] == "symbolic-ref" else SHA
        ))

    monkeypatch.setattr(refresh, "git", git)
    monkeypatch.setattr(refresh.install_location, "_clean_commit_date",
                        lambda *_: "2026-11-25")

    def bootstrap(_args):
        refresh.install_location._record_source_revision(source, installed, SHA)
        return 0

    call = Mock(side_effect=bootstrap)
    monkeypatch.setattr(refresh.subprocess, "call", call)
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    assert marker.read_text() == SHA + "\n2026-11-25\n"
    assert refresh.installed_revision(installed) == SHA
    assert refresh.refresh(source, installed, "linux", lambda: []) == 0
    call.assert_called_once()
