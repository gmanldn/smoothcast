"""Portable entrypoint routes to the actual installation, never a second GUI."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("portable_entry", str(ROOT / "smoothcast"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    # Real launcher routing, fake runtime boundary. Never call GTK or setup.
    runtime = mock.Mock()
    runtime.ensure_single_instance.return_value = None
    runtime.runtime_ready.return_value = True
    runtime.main.return_value = 0
    monkeypatch.setitem(sys.modules, "launch", runtime)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    monkeypatch.setattr(module, "_target", lambda: "linux")
    monkeypatch.setattr(module, "_install_desktop", mock.Mock())
    monkeypatch.setattr(module, "_bootstrap", mock.Mock(return_value=0))
    monkeypatch.setattr(module, "_launch_installed", mock.Mock(return_value=0))
    monkeypatch.setattr(module, "_installed_root", mock.Mock(return_value=None))
    return module, runtime


def test_installed_wins_even_if_checkout_runtime_exists(entry, tmp_path):
    module, runtime = entry
    installed = tmp_path / "My apps" / "SmoothCast"
    module._installed_root.return_value = installed
    args = ["relative film.mkv", "https://example.org/a?b=c"]
    assert module.main(args) == 0
    module._launch_installed.assert_called_once_with(installed, args)
    runtime.ensure_single_instance.assert_not_called()
    runtime.runtime_ready.assert_not_called()
    module._bootstrap.assert_not_called()
    module._install_desktop.assert_not_called()


def test_fresh_install_routes_to_new_saved_location(entry, tmp_path):
    module, runtime = entry
    installed = tmp_path / "installed"
    runtime.runtime_ready.return_value = False
    module._installed_root.side_effect = [None, installed]
    assert module.main([]) == 0
    module._bootstrap.assert_called_once_with("linux")
    module._launch_installed.assert_called_once_with(installed, [])
    runtime.main.assert_not_called()
    module._install_desktop.assert_not_called()


def test_successful_bootstrap_without_runtime_is_failure(entry):
    module, runtime = entry
    runtime.runtime_ready.return_value = False
    assert module.main([]) == 1
    runtime.main.assert_not_called()
    module._install_desktop.assert_not_called()


def test_installed_entry_does_not_recurse(entry):
    module, runtime = entry
    module._installed_root.return_value = ROOT
    assert module.main([]) == 0
    module._launch_installed.assert_not_called()
    runtime.main.assert_called_once_with([], prechecked=True)


def test_existing_primary_still_precedes_bootstrap(entry):
    module, runtime = entry
    runtime.ensure_single_instance.return_value = 0
    assert module.main([]) == 0
    runtime.runtime_ready.assert_not_called()
    module._bootstrap.assert_not_called()


def test_portable_override_is_in_place_and_does_not_replace_shortcuts(entry):
    module, runtime = entry
    runtime.runtime_ready.side_effect = [False, True]
    assert module.main(["--portable", "clip.mkv"]) == 0
    module._installed_root.assert_not_called()
    module._bootstrap.assert_called_once_with("linux", portable=True)
    module._install_desktop.assert_not_called()
    runtime.main.assert_called_once_with(["clip.mkv"], prechecked=True)


def test_headless_version_reports_installed_not_checkout(entry, tmp_path):
    module, runtime = entry
    module._installed_root.return_value = tmp_path
    assert module.main(["--version"]) == 0
    module._launch_installed.assert_called_once_with(tmp_path, ["--version"])
    module._bootstrap.assert_not_called()
    runtime.main.assert_not_called()


def test_test_context_never_delegates_to_real_install(entry, monkeypatch):
    module, runtime = entry
    monkeypatch.setenv("SMOOTHCAST_TEST_CONTEXT", "1")
    module.main([])
    module._installed_root.assert_not_called()
    module._launch_installed.assert_not_called()
    runtime.main.assert_called_once_with([])


def test_delegation_preserves_cwd_and_args_and_propagates_failure(tmp_path, monkeypatch, capsys):
    loader = importlib.machinery.SourceFileLoader("portable_entry_direct", str(ROOT / "smoothcast"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    installed = tmp_path / "My installation"
    script = installed / "setup" / "launch.py"
    script.parent.mkdir(parents=True)
    script.touch()
    call = mock.Mock(return_value=3)
    monkeypatch.setattr(module.subprocess, "call", call)
    cwd = Path.cwd()
    args = ["relative.mkv", "--action", "queue"]
    assert module._launch_installed(installed, args) == 3
    call.assert_called_once_with([sys.executable, str(script), *args])
    assert Path.cwd() == cwd
    assert str(installed) in capsys.readouterr().err
    script.unlink()
    call.reset_mock()
    assert module._launch_installed(installed, args) == 1
    call.assert_not_called()


@pytest.mark.parametrize("remembered,default_manifest,expected", [
    (True, False, "remembered"),
    (False, True, "default"),
    (False, False, None),
])
def test_saved_location_precedes_recognised_default(entry, tmp_path, monkeypatch,
                                                    remembered, default_manifest, expected):
    # Load the actual routing helper rather than the main() fixture's mock.
    loader = importlib.machinery.SourceFileLoader("portable_entry_location", str(ROOT / "smoothcast"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    actual = importlib.util.module_from_spec(spec)
    loader.exec_module(actual)
    saved = tmp_path / "remembered"
    default = tmp_path / "default"
    (default / "setup").mkdir(parents=True)
    (default / "setup" / "bootstrap.py").touch()
    (default / "pyproject.toml").write_text(
        'name = "smoothcast"\n' if default_manifest else 'name = "other"\n', encoding="utf-8")
    locations = mock.Mock()
    locations.previous_directory.return_value = saved if remembered else None
    locations.default_directory.return_value = default
    monkeypatch.setitem(sys.modules, "install_location", locations)
    assert actual._installed_root("linux") == (tmp_path / expected if expected else None)
