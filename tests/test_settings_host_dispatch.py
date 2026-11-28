"""Host-only appearance setting dispatch stays narrow and runs on GTK owner."""
from __future__ import annotations

import ast
from types import SimpleNamespace

import pytest

import cast_portal
import cast_portal_host
import cast_widgets
import portal
import preference_choices
import settings_catalog


class _HostServer:
    def __init__(self, is_host=True):
        self.is_host = is_host

    @staticmethod
    def session_key_active(_key):
        return True

    def session_key_is_host(self, _key):
        return self.is_host


def _window(is_host=True):
    window = object.__new__(cast_portal.PortalMixin)
    window._closing = False
    window._syncing = False
    window._sync_host_setting_widgets = cast_portal_host.PortalHostController(
        window)._sync_host_setting_widgets
    window._portal = SimpleNamespace(server=_HostServer(is_host))
    window.cfg = {
        "color_scheme": "prefer-dark", "auto_theme": True,
        "accent": "default", "density": "comfortable",
        "autonext": False, "loop": False, "loop_all": False,
    }
    window.app = SimpleNamespace(
        scheme_action=SimpleNamespace(state=None, set_state=lambda value: setattr(
            window.app.scheme_action, "state", value)),
        apply_accent=lambda value: setattr(window.app, "accent", value),
        apply_density=lambda value: setattr(window.app, "density", value),
    )
    window._apply_color_scheme = lambda: setattr(window, "scheme_applied", True)
    window._refresh_responsive_layout = lambda: setattr(window, "density_applied", True)
    window.autonext_switch = SimpleNamespace(
        active=False, set_active=lambda value: setattr(window.autonext_switch, "active", value))
    for name in ("quality_dropdown", "audio_dropdown", "loudness_dropdown", "rotation_dropdown"):
        setattr(window, name, SimpleNamespace(selected=None, set_selected=lambda value, n=name: setattr(
            getattr(window, n), "selected", value)))
    for name in ("direct_switch", "keep_switch", "burn_switch", "music_autogain_switch"):
        setattr(window, name, SimpleNamespace(active=None, set_active=lambda value, n=name: setattr(
            getattr(window, n), "active", value)))
    window.gain_spin = SimpleNamespace(value=None, set_value=lambda value: setattr(
        window.gain_spin, "value", value))
    window._preferences_window = SimpleNamespace(sync_from_owner=lambda: setattr(
        window, "preferences_synced", True))
    return window


def test_host_settings_owner_dispatch_applies_and_persists_allowlisted_values(monkeypatch):
    window = _window()
    saved = []
    monkeypatch.setattr(cast_portal, "save_config", lambda cfg: saved.append(dict(cfg)))
    key = "a" * 64

    values = window._portal_handle("settings_update", {
        "_portal_auth_key": key, "key": "color_scheme", "value": "force-light",
    })
    assert values["color_scheme"] == "force-light" and values["auto_theme"] is False
    assert window.scheme_applied and window.preferences_synced and saved[-1]["auto_theme"] is False

    window._portal_handle("settings_update", {
        "_portal_auth_key": key, "key": "accent", "value": "teal",
    })
    window._portal_handle("settings_update", {
        "_portal_auth_key": key, "key": "density", "value": "compact",
    })
    for setting in ("autonext", "loop", "loop_all"):
        window._portal_handle("settings_update", {
            "_portal_auth_key": key, "key": setting, "value": True,
        })
    assert window.app.accent == "teal" and window.app.density == "compact"
    assert window.density_applied and window.autonext_switch.active
    assert all(window.cfg[key] is True for key in ("autonext", "loop", "loop_all"))
    assert len(saved) == 6


def test_host_settings_owner_dispatch_rejects_guest_and_unknown_key_without_mutation():
    window = _window(is_host=False)
    before = dict(window.cfg)
    with pytest.raises(portal.PortalRequestError) as denied:
        window._portal_handle("settings_update", {
            "_portal_auth_key": "a" * 64, "key": "accent", "value": "teal",
        })
    assert denied.value.status == 403 and window.cfg == before

    window._portal._server = None
    window._portal.server.is_host = True
    with pytest.raises(portal.PortalRequestError) as invalid:
        window._portal_handle("settings_update", {
            "_portal_auth_key": "a" * 64, "key": "config_path", "value": "/etc/passwd",
        })
    assert invalid.value.status == 400 and window.cfg == before


def test_host_control_choices_and_defaults_match_desktop_preferences():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gtk_paths = list((root / "src").glob("*preferences*ui.py")) + [root / "src/cast_settings.py"]
    gtk_preferences = "\n".join(
        node.value
        for path in gtk_paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    html = settings_catalog.host_controls_html()
    for key, descriptor in settings_catalog.HOST_CONTROLS.items():
        assert cast_widgets.DEFAULTS[key] == descriptor["default"]
        assert descriptor["title"] in gtk_preferences
        assert descriptor["description"] in gtk_preferences
        assert descriptor["group"] in {group for page, groups in settings_catalog.PREFERENCES
                                        for group, _summary in groups}
        assert descriptor["apply_timing"]
        if descriptor["kind"] == "choice":
            assert key in preference_choices.OPTIONS
            for _label, option in preference_choices.OPTIONS[key]:
                assert settings_catalog.validate_host_setting(key, option) == (key, option)
            assert settings_catalog.validate_host_setting(
                key, descriptor["default"])[1] == descriptor["default"]
        elif descriptor["kind"] == "number":
            assert settings_catalog.validate_host_setting(key, descriptor["default"]) == (key, descriptor["default"])
            assert f'Default: {descriptor["default"]:g} dB' in html
    assert 'id="hostSettingsControls"' in html
    assert 'aria-describedby="hostSetting-autonext-help"' in html
    assert 'type="number" min="0" max="24" step="1"' in html
    assert "Default: Comfortable" in html
    assert "Applies when the current item finishes." in html


def test_host_playback_and_caption_preferences_sync_with_desktop_controls(monkeypatch):
    window = _window()
    saved = []
    monkeypatch.setattr(cast_portal, "save_config", lambda cfg: saved.append(dict(cfg)))
    key = "a" * 64
    changes = {
        "quality": "high", "rotation": 180, "aspect_override": "fit",
        "direct": False, "keep_streaming": False, "auto_crop": True,
        "auto_deinterlace": True, "audio": "night", "audio_loudness": "programme",
        "audio_gain": 12, "music_autogain": True,
        "burn_subs": True, "subtitle_style": "large",
    }
    for name, value in changes.items():
        window._portal_handle("settings_update", {
            "_portal_auth_key": key, "key": name, "value": value,
        })
    assert {name: window.cfg[name] for name in changes} == changes
    assert window.cfg["quality_auto"] is False
    assert window.quality_dropdown.selected == 0
    assert window.rotation_dropdown.selected == 2
    assert window.audio_dropdown.selected == 2
    assert window.loudness_dropdown.selected == 1
    assert window.gain_spin.value == 12.0
    assert window.direct_switch.active is False
    assert window.keep_switch.active is False
    assert window.burn_switch.active is True
    assert window.music_autogain_switch.active is True
    assert len(saved) == len(changes)


@pytest.mark.parametrize("value", [-1, 25, "nan", True, None])
def test_host_dialogue_gain_rejects_values_outside_its_documented_range(value):
    with pytest.raises(settings_catalog.HostSettingError, match="number from 0 to 24"):
        settings_catalog.validate_host_setting("audio_gain", value)


def test_web_rotation_select_preserves_integer_preference_type():
    assert settings_catalog.validate_host_setting("rotation", "90") == ("rotation", 90)
    with pytest.raises(settings_catalog.HostSettingError, match="listed options"):
        settings_catalog.validate_host_setting("rotation", "91")
