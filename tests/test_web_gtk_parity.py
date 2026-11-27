"""#708: the web Now Playing card keeps the desktop hero-card vocabulary."""
import portal
import ui_theme


def test_web_now_playing_matches_gtk_hero_card():
    html = portal._HTML
    for needle in ("#playback{padding:22px", "letter-spacing:1px", "font-size:1.65rem", "font-weight:800"):
        assert needle in html
    css = ui_theme.CSS if isinstance(ui_theme.CSS, str) else ui_theme.CSS.decode()
    for needle in ("padding: 22px", "letter-spacing: 1px", "font-size: 1.65em", "font-weight: 800"):
        assert needle in css
