import pip_support as p


def test_wayland_never_claims_always_on_top():
    c = p.capability("wayland", "GNOME")
    assert c["always_on_top"] is False and "Always on Top" in c["message"]
    assert "Always on Top" not in p.capability("wayland", "KDE")["message"]


def test_x11_and_other_platforms():
    assert p.capability("x11")["always_on_top"] is True
    assert "ignore" in p.capability("x11")["message"]
    assert p.capability("", platform="win32")["always_on_top"] is True


def test_unknown_session_is_conservative():
    for s in (None, "", "mir"):
        c = p.capability(s)
        assert c["always_on_top"] is False and c["floating"] is True
