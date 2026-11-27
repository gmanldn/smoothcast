import zoom_pan as z


def test_one_x_emits_nothing_and_zoom_steps_are_bounded():
    v = z.View()
    assert z.crop_filter(1920, 1080, v) == []
    assert z.step_zoom(v, -1).zoom == 1
    assert z.step_zoom(z.step_zoom(z.step_zoom(v, 1), 1), 1).zoom == 4
    assert z.set_zoom(v, 3).zoom == 1


def test_crop_is_even_and_in_bounds_at_every_zoom_and_corner():
    for zoom in z.ZOOMS:
        for cx, cy in ((0, 0), (1, 1), (0.5, 0.5), (float("nan"), 9)):
            v = z._clamp_view(zoom, cx, cy)
            w, h, x, y = z.crop_rect(1921, 1081, v)
            assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0 and y % 2 == 0
            assert 0 <= x and 0 <= y and x + w <= 1921 and y + h <= 1081


def test_pan_stays_inside_frame():
    v = z.set_zoom(z.View(), 4)
    for _ in range(100):
        v = z.pan(v, -1, -1)
    assert v.cx == 0.125 and v.cy == 0.125
    v = z.pan(z.View(2, 0.5, 0.5), 1, 0)
    assert v.cx > 0.5


def test_manual_crop_validation():
    assert z.validate_manual(1920, 1080, 11, 11, 101, 101) == (100, 100, 10, 10)
    assert z.validate_manual(1920, 1080, 1900, 0, 100, 100) is None
    assert z.validate_manual(1920, 1080, -1, 0, 100, 100) is None
    assert z.validate_manual(1920, 1080, "a", 0, 100, 100) is None
    assert z.crop_filter(1920, 1080, manual=(0, 0, 640, 360)) == ["crop=640:360:0:0"]
    assert z.crop_filter(1920, 1080, manual=(0, 0, 0, 0)) == []
