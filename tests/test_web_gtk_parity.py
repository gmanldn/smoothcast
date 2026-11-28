"""#708: the web Now Playing card keeps the desktop hero-card vocabulary."""
import portal
import settings_catalog
import ui_theme
import ui_tokens


def test_web_now_playing_matches_gtk_hero_card():
    html = portal._HTML
    for needle in ("#playback{padding:22px", "letter-spacing:1px", "font-size:var(--sc-type-hero)", "font-weight:800"):
        assert needle in html
    css = ui_theme.CSS if isinstance(ui_theme.CSS, str) else ui_theme.CSS.decode()
    for needle in ("padding: 22px", "letter-spacing: 1px", "font-size: 1.65em", "font-weight: 800"):
        assert needle in css


def test_front_page_has_at_a_glance_tiles_fed_by_room_state():
    html = portal._HTML
    for needle in ('id="glance"', 'id="glanceTitle"', 'id="glanceWhere"', 'id="glanceWho"', "renderGlance(room)"):
        assert needle in html


def test_room_glance_labels_are_shared_by_gtk_and_web():
    from pathlib import Path

    gtk = (Path(__file__).resolve().parents[1] / "src" / "cast_ui.py").read_text(encoding="utf-8")
    assert ui_tokens.web_glance_html() in portal._HTML
    assert "for field in ui_tokens.ROOM_GLANCE_FIELDS" in gtk
    assert 'if field["gtk_slot"] != "summary"' in gtk
    for field in ui_tokens.ROOM_GLANCE_FIELDS:
        assert f'<span class="glance-label">{field["label"]}</span>' in portal._HTML
        assert field["web_id"] in portal._HTML
    assert "__SC_ROOM_GLANCE__" not in portal._HTML


def test_web_settings_map_tracks_desktop_preferences_pages_and_groups():
    from html import escape
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gtk_preferences = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "src").glob("*preferences*ui.py")
    )
    gtk_preferences += (root / "src/library_folders_ui.py").read_text(encoding="utf-8")
    web = portal._page().decode("utf-8")
    for page, groups in settings_catalog.PREFERENCES:
        assert f'<h4>{escape(page)}</h4>' in web
        assert f'"{page}"' in gtk_preferences
        for group, summary in groups:
            assert f'<strong>{escape(group)}</strong>' in web
            assert group in gtk_preferences
            assert settings_catalog.group_description(page, group) == summary
            assert escape(summary) in web
    assert "__SC_SETTINGS_CATALOG__" not in web
    assert "managed on the computer running SmoothCast" in web


def test_host_settings_controls_stay_hidden_until_authorized_values_load():
    web = portal._page().decode("utf-8")
    assert '<section id="hostSettingsControls" class="preference-map" hidden' in web
    assert 'fetch("/api/settings"' in web
    assert 'if(!canRename&&hostControls)hostControls.hidden=true' in web
    assert 'renderHostSettings(data.settings);$("hostSettingsControls").hidden=false' in web
