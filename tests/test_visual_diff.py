import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import visual_diff as v

W, H = 20, 10


def img(rgb=(200, 200, 200), ch=3):
    return bytes(list(rgb) + ([255] if ch == 4 else [])) * (W * H)


def poke(buf, n, rgb, ch=3):
    b = bytearray(buf)
    for k in range(n): b[k * ch:k * ch + 3] = bytes(rgb)
    return bytes(b)


def test_identical_images_pass_and_noise_within_tolerance_passes():
    a = img(); assert v.compare(a, a, W, H) == {"ok": True, "changed": 0, "ratio": 0.0}
    noisy = poke(a, 50, (205, 198, 203)); assert v.compare(a, noisy, W, H)["ok"] and v.compare(a, noisy, W, H)["changed"] == 0


def test_real_difference_over_threshold_fails_and_small_one_passes_with_looser_threshold():
    a = img(); b = poke(a, 20, (0, 0, 0))
    r = v.compare(a, b, W, H); assert r == {"ok": False, "changed": 20, "ratio": 0.1}
    assert v.compare(a, b, W, H, threshold=0.1)["ok"] and not v.compare(a, poke(a, 1, (0, 0, 0)), W, H, threshold=0.001)["ok"]
    assert v.compare(img(ch=4), poke(img(ch=4), 20, (0, 0, 0), 4), W, H, 4)["changed"] == 20


def test_size_mismatch_and_bad_geometry_fail_closed():
    assert v.compare(img(), img()[:-3], W, H) == {"ok": False, "error": "size mismatch", "changed": None, "ratio": 1.0}
    for g in ((0, 5, 3), (5, -1, 3), (5, 5, 2), (5000, 5000, 3)): assert v.compare(b"", b"", *g)["ok"] is False
    assert v.diff_image(img(), img()[:-3], W, H) is None


def test_diff_image_marks_changed_pixels_red_and_dims_the_rest():
    a = img((90, 90, 90)); b = poke(a, 2, (0, 0, 0)); d = v.diff_image(a, b, W, H)
    assert d[:6] == b"\xff\x00\x00\xff\x00\x00" and d[6:9] == bytes([200, 200, 200]) and len(d) == len(a)
    assert v.diff_image(img(ch=4), img(ch=4), W, H, 4)[3] == 255


def test_report_and_fixed_scenario_matrix():
    ok, lines = v.report({"a": {"ok": True, "ratio": 0.0}, "b": {"ok": False, "ratio": 0.1}, "c": {"ok": False, "error": "size mismatch", "ratio": 1.0}})
    assert not ok and lines == ["b: 10.0% pixels differ", "c: size mismatch"] and v.report({"a": {"ok": True, "ratio": 0}}) == (True, [])
    assert v.scenario_names() == ["desktop-compact-light", "desktop-compact-dark", "desktop-wide-light", "desktop-wide-dark", "web-360px-default", "web-1024px-default"]
