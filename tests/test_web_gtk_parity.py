"""#708: the web Now Playing card keeps the desktop hero-card vocabulary."""
import gui_source
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
    # Both surfaces render from ui_tokens.ROOM_GLANCE_FIELDS; assert the shared
    # data is well-formed and that the web page carries every field it defines.
    fields = ui_tokens.ROOM_GLANCE_FIELDS
    assert fields, "no glance fields defined"
    assert len({f["web_id"] for f in fields}) == len(fields)
    assert all(f["label"] and f["web_id"] and f["gtk_slot"] for f in fields)
    assert ui_tokens.web_glance_html() in portal._HTML
    for field in fields:
        assert f'<span class="glance-label">{field["label"]}</span>' in portal._HTML
        assert field["web_id"] in portal._HTML
    assert "__SC_ROOM_GLANCE__" not in portal._HTML


def test_web_settings_map_tracks_the_shared_preferences_catalogue():
    # The desktop preferences are built from settings_catalog too, so the web
    # map is checked against that catalogue rather than against GTK source text.
    from html import escape

    web = portal._page().decode("utf-8")
    assert settings_catalog.PREFERENCES
    for page, groups in settings_catalog.PREFERENCES:
        assert f'<h4>{escape(page)}</h4>' in web
        assert groups, f"page {page!r} has no groups"
        for group, summary in groups:
            assert f'<strong>{escape(group)}</strong>' in web
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
