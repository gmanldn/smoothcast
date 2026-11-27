import handoff_accuracy as h


def test_error_sign_and_bad_input():
    assert h.error(100, 98.5) == 1.5
    assert h.error(100, float("nan")) is None
    assert h.error(True, 1) is None


def test_no_compensation_until_enough_samples():
    hist = {}
    h.record(hist, "tv", 2.0)
    h.record(hist, "tv", 2.0)
    assert h.compensation(hist, "tv") == 0.0
    h.record(hist, "tv", 2.0)
    assert h.compensation(hist, "tv") == 2.0


def test_median_ignores_one_outlier_and_implausible_values():
    hist = {}
    for e in (1.5, 1.6, 1.4, 25.0, 99.0):
        h.record(hist, "tv", e)
    assert 1.4 <= h.compensation(hist, "tv") <= 1.6
    assert len(hist["tv"]) == 4  # 99 discarded


def test_small_error_is_left_alone_and_large_is_clamped():
    hist = {"a": [0.1, 0.2, 0.1], "b": [20.0] * 5}
    assert h.compensation(hist, "a") == 0.0
    assert h.compensation(hist, "b") == h.MAX_COMPENSATION_S
    assert h.compensation(hist, "unknown") == 0.0


def test_history_is_bounded_and_receivers_are_separate():
    hist = {}
    for i in range(30):
        h.record(hist, "tv", 1.0)
    h.record(hist, "kitchen", -2.0)
    assert len(hist["tv"]) == h.KEEP and hist["kitchen"] == [-2.0]
    assert h.within_tolerance(0.9) and not h.within_tolerance(1.1)
