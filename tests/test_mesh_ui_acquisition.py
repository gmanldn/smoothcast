"""Network popover opt-ins for remote link acquisition (#589)."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS

import cast_mesh
import mesh_service
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_switch_persists_the_right_key_flushes_then_restarts(monkeypatch):
    order = []
    window = NS(cfg={"device": "TV"}, _mesh_address="192.168.1.2")
    monkeypatch.setattr(cast_mesh, "start", lambda w, address: order.append(("start", address)))
    ok = cast_mesh.set_acquisition(window, "accept_acquisition", True,
                                   save=lambda cfg: order.append(("save", dict(cfg))),
                                   flush=lambda: order.append(("flush",)))
    assert ok and window.cfg["mesh_accept_acquisition"] is True
    assert [step[0] for step in order] == ["save", "flush", "start"]  # on disk before the restart reads it
    assert order[0][1]["mesh_accept_acquisition"] is True and order[2][1] == "192.168.1.2"


@pytest.mark.parametrize("name,value", [("mesh_enabled", True), ("accept_acquisition", "yes"),
                                        ("accept_acquisition", 1), (None, True)])
def test_only_the_two_known_switches_accept_only_booleans(name, value):
    window = NS(cfg={})
    assert cast_mesh.set_acquisition(window, name, value, save=lambda c: None, flush=lambda: None) is False
    assert window.cfg == {}


def test_no_restart_without_a_running_mesh_address_and_failures_never_raise(monkeypatch):
    started = []
    monkeypatch.setattr(cast_mesh, "start", lambda *a: started.append(a))
    window = NS(cfg={})
    assert cast_mesh.set_acquisition(window, "remote_acquisition", True,
                                     save=lambda c: None, flush=lambda: None)
    assert started == []

    def boom(_cfg):
        raise OSError("disk full")

    assert cast_mesh.set_acquisition(window, "remote_acquisition", False,
                                     save=boom, flush=lambda: None) is False


def test_saved_keys_round_trip_through_the_real_settings_reader(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mesh_enabled": True, "mesh_remote_acquisition": True,
                                "mesh_accept_acquisition": "true"}))
    got = mesh_service.load_settings(path)
    assert got["remote_acquisition"] is True and got["accept_acquisition"] is False  # strict booleans


def test_popover_builds_both_switches_with_accessible_labels_and_a_guarded_handler():
    source = (ROOT / "src" / "mesh_ui.py").read_text()
    tree = ast.parse(source)
    assert '"remote_acquisition"' in source and '"accept_acquisition"' in source
    options = ast.get_source_segment(source, next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_link_download_options"))
    assert "AccessibleProperty.LABEL" in options  # each switch is named for screen readers
    toggled = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_toggled")
    assert "_syncing" in ast.get_source_segment(source, toggled)  # programmatic sync cannot re-save
