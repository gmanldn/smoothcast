"""Host-only appearance setting dispatch stays narrow and runs on GTK owner."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import cast_portal
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
    window._portal = SimpleNamespace(server=_HostServer(is_host))
    window.cfg = {
        "color_scheme": "prefer-dark", "auto_theme": True,
        "accent": "default", "density": "comfortable",
    }
    window.app = SimpleNamespace(
        scheme_action=SimpleNamespace(state=None, set_state=lambda value: setattr(
            window.app.scheme_action, "state", value)),
        apply_accent=lambda value: setattr(window.app, "accent", value),
        apply_density=lambda value: setattr(window.app, "density", value),
    )
    window._apply_color_scheme = lambda: setattr(window, "scheme_applied", True)
    window._refresh_responsive_layout = lambda: setattr(window, "density_applied", True)
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
    assert window.app.accent == "teal" and window.app.density == "compact"
    assert window.density_applied and len(saved) == 3


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
    for key, descriptor in settings_catalog.HOST_CONTROLS.items():
        assert cast_widgets.DEFAULTS[key] == descriptor["default"]
        if descriptor["kind"] == "choice":
            assert key in preference_choices.OPTIONS
            assert settings_catalog.validate_host_setting(
                key, descriptor["default"])[1] == descriptor["default"]
