import mini_player as m


def test_wide_window_shows_everything():
    lay = m.layout(1200)
    assert lay["mode"] == "full" and set(m.EXTRAS) <= set(lay["visible"])


def test_narrow_or_opted_in_goes_mini_but_keeps_essentials():
    for width, on in ((400, False), (1200, True), (300, False), (None, False), (0, False)):
        assert m.essentials_always_present(width, on)
    assert m.layout(400)["mode"] == "mini" and m.layout(1200, True)["mode"] == "mini"
    assert m.layout(None)["mode"] == "full"


def test_tiny_stacks_and_drops_decoration():
    lay = m.layout(300)
    assert lay["orientation"] == "stacked" and "thumbnail" not in lay["visible"]
    assert m.layout(450)["orientation"] == "row"
