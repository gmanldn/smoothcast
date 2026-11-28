"""Portable entrypoint routes to the actual installation, never a second GUI."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("portable_entry", str(ROOT / "sc.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    # Real launcher routing, fake runtime boundary. Never call GTK or setup.
    runtime = mock.Mock()
    runtime.ensure_single_instance.return_value = None
    runtime.runtime_ready.return_value = True
    runtime.main.return_value = 0
    monkeypatch.setitem(sys.modules, "launch", runtime)
    refresher = mock.Mock()
    refresher.refresh.return_value = 0
    refresher.read_version.return_value = (2, 0, 5)
    refresher.installed_revision.return_value = "a" * 40
    monkeypatch.setitem(sys.modules, "checkout_refresh", refresher)
    monkeypatch.setitem(sys.modules, "installed_update", mock.Mock())
    sys.modules["installed_update"].refresh.return_value = 0
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    monkeypatch.setattr(module, "_target", lambda: "linux")
    monkeypatch.setattr(module, "_install_desktop", mock.Mock())
    monkeypatch.setattr(module, "_bootstrap", mock.Mock(return_value=0))
    monkeypatch.setattr(module, "_launch_installed", mock.Mock(return_value=0))
    monkeypatch.setattr(module, "_installed_root", mock.Mock(return_value=None))
    return module, runtime


def test_installed_wins_even_if_checkout_runtime_exists(entry, tmp_path, monkeypatch):
    module, runtime = entry
    installed = tmp_path / "My apps" / "SmoothCast"
    module._installed_root.return_value = installed
    monkeypatch.chdir(tmp_path)
    args = ["relative film.mkv", "https://example.org/a?b=c"]
    refresher = sys.modules["checkout_refresh"]
    refresher.installed_revision.side_effect = ["a" * 40, "b" * 40]

    def refresh(root, target, _running):
        assert root == installed and target == "linux"
        assert os.environ["SMOOTHCAST_LAUNCH_SOURCE"] == str(module.ROOT.resolve())
        os.environ["SMOOTHCAST_LATEST_DEVELOP_TIP"] = "b" * 40
        return 0

    sys.modules["installed_update"].refresh.side_effect = refresh
    assert module.main(args) == 0
    module._launch_installed.assert_called_once_with(installed, args, updated=True)
    sys.modules["installed_update"].refresh.assert_called_once()
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
    loader = importlib.machinery.SourceFileLoader("portable_entry_direct", str(ROOT / "sc.py"))
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
    call.assert_called_once_with([sys.executable, str(script), *args],
                                 env=mock.ANY)
    assert call.call_args.kwargs["env"]["SMOOTHCAST_HANDOFF"] == "1"
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
    loader = importlib.machinery.SourceFileLoader("portable_entry_location", str(ROOT / "sc.py"))
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
    locations.config_path.return_value = tmp_path / "no-pointer"  # absent: no saved path
    monkeypatch.setitem(sys.modules, "install_location", locations)
    assert actual._installed_root("linux") == (tmp_path / expected if expected else None)


def test_checkout_updates_registered_install_before_handoff(entry, tmp_path):
    module, runtime = entry
    module._installed_root.return_value = tmp_path
    assert module.main([]) == 0
    sys.modules["checkout_refresh"].refresh.assert_not_called()
    sys.modules["installed_update"].refresh.assert_called_once()
    module._launch_installed.assert_called_once_with(tmp_path, [], updated=True)
    runtime.main.assert_not_called()

def test_version_query_never_refreshes_installed_files(entry, tmp_path):
    module, _runtime = entry
    module._installed_root.return_value = tmp_path
    assert module.main(["--version"]) == 0
    sys.modules["checkout_refresh"].refresh.assert_not_called()


def test_new_install_handoff_uses_canonical_script(entry, tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("canonical_direct", str(ROOT / "sc.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    actual = importlib.util.module_from_spec(spec)
    loader.exec_module(actual)
    (tmp_path / "sc.py").touch()
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "launch.py").touch()
    call = mock.Mock(return_value=0)
    monkeypatch.setattr(actual.subprocess, "call", call)
    assert actual._launch_installed(tmp_path, ["relative.mkv"]) == 0
    call.assert_called_once_with([sys.executable, str(tmp_path / "sc.py"), "relative.mkv"],
                                 env=mock.ANY)


def test_registered_root_repairs_missing_runtime_in_place(entry):
    module, runtime = entry
    module._installed_root.return_value = ROOT
    runtime.runtime_ready.side_effect = [False, True]
    assert module.main([]) == 0
    module._bootstrap.assert_called_once_with("linux", in_place=True)
    runtime.main.assert_called_once_with([], prechecked=True)


def test_compatibility_wrapper_delegates_all_arguments(monkeypatch):
    import runpy
    canonical = mock.Mock()
    canonical.main.return_value = 17
    monkeypatch.setitem(sys.modules, "sc", canonical)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "smoothcast"), run_name="__main__")
    assert result.value.code == 17
    canonical.main.assert_called_once_with()


def test_running_primary_is_activated_before_remote_check(entry):
    module, runtime = entry
    module._installed_root.return_value = ROOT
    runtime.ensure_single_instance.return_value = 0
    assert module.main([]) == 0
    sys.modules["installed_update"].refresh.assert_not_called()
    runtime.main.assert_not_called()


def test_refreshed_shortcut_restarts_new_launcher(entry, tmp_path, monkeypatch):
    module, runtime = entry
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SMOOTHCAST_HANDOFF", "1")
    module._installed_root.return_value = ROOT
    refresher = sys.modules["checkout_refresh"]
    refresher.installed_revision.side_effect = ["a" * 40, "b" * 40]
    assert module.main(["film.mkv"]) == 0
    sys.modules["installed_update"].refresh.assert_called_once()
    module._launch_installed.assert_called_once_with(ROOT, ["film.mkv"], updated=True)
    runtime.main.assert_not_called()


def test_relaunched_build_does_not_repeat_remote_check(entry, monkeypatch):
    module, runtime = entry
    module._installed_root.return_value = ROOT
    monkeypatch.setenv("SMOOTHCAST_UPDATE_APPLIED", "1")
    assert module.main([]) == 0
    sys.modules["installed_update"].refresh.assert_not_called()
    runtime.main.assert_called_once_with([], prechecked=True)


def test_clean_start_names_latest_confirmed_develop_build(entry):
    import os

    module, runtime = entry
    module._installed_root.return_value = ROOT
    revision = "a" * 40
    sys.modules["checkout_refresh"].installed_revision.return_value = revision

    def refresh(*_args):
        os.environ["SMOOTHCAST_LATEST_DEVELOP_TIP"] = revision
        return 0

    sys.modules["installed_update"].refresh.side_effect = refresh
    assert module.main([]) == 0
    sys.modules["checkout_refresh"].announce.assert_called_once_with(
        (2, 0, 5), revision, "Starting latest develop version", latest_develop=True)
    runtime.main.assert_called_once_with([], prechecked=True)

def _real_sc():
    loader = importlib.machinery.SourceFileLoader("sc_real_launcher", str(ROOT / "sc.py"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("payload", [b"\xff\xfe\x00bad", b"", b"relative/path"])
def test_unreadable_or_odd_install_pointer_is_not_fatal(tmp_path, monkeypatch, payload):
    pointer = tmp_path / "install-location"
    pointer.write_bytes(payload)
    locations = mock.Mock()
    locations.config_path.return_value = pointer
    locations.previous_directory.return_value = None
    locations.default_directory.return_value = tmp_path / "default"
    monkeypatch.setitem(sys.modules, "install_location", locations)
    assert _real_sc()._installed_root("linux") is None
    locations.check_install_idle.assert_called_once_with(tmp_path / "default")


def test_busy_installer_is_reported_civilly_not_as_a_traceback(monkeypatch, capsys):
    module = _real_sc()
    monkeypatch.delenv("SMOOTHCAST_TEST_CONTEXT", raising=False)
    monkeypatch.setitem(sys.modules, "launch", mock.Mock())
    monkeypatch.setattr(module, "_target", lambda: "linux")
    busy = OSError("Another setup is active for /x; retry when it finishes.")
    monkeypatch.setattr(module, "_installed_root", mock.Mock(side_effect=busy))
    assert module.main([]) == 1
    err = capsys.readouterr().err
    assert "Another setup is active" in err and "Traceback" not in err


def test_ctrl_c_during_launch_is_quiet(monkeypatch, capsys):
    module = _real_sc()
    monkeypatch.setattr(module, "_main", mock.Mock(side_effect=KeyboardInterrupt))
    assert module.main([]) == 130
    assert capsys.readouterr().err == ""


def test_handoff_marker_prevents_launcher_ping_pong(entry, monkeypatch, tmp_path):
    module, runtime = entry
    module._installed_root.return_value = tmp_path / "elsewhere"
    monkeypatch.setenv("SMOOTHCAST_HANDOFF", "1")
    module.main([])
    module._launch_installed.assert_not_called()


def test_handoff_child_receives_marker_and_arguments(monkeypatch, tmp_path):
    module = _real_sc()
    (tmp_path / "sc.py").write_text("")
    calls = []
    monkeypatch.setattr(module.subprocess, "call",
                        lambda cmd, **kw: calls.append((cmd, kw)) or 0)
    assert module._launch_installed(tmp_path, ["a b.mkv"]) == 0
    cmd, kw = calls[0]
    assert cmd[-1] == "a b.mkv" and kw["env"]["SMOOTHCAST_HANDOFF"] == "1"
    assert kw["env"]["SMOOTHCAST_LAUNCH_SOURCE"] == str(module.ROOT.resolve())
