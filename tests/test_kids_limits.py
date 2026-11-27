import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import kids_limits as kl

L = {"max_rating": "PG", "unrated": "block", "budget_minutes": 60,
     "bedtime": {"mon": [["20:00", "07:00"]], "sat": [["22:00", "23:00"]]}}


def at(day, hh, mm=0):                   # 2026-11-23 is a Monday
    return datetime(2026, 11, 23 + day, hh, mm)


def test_rating_scale_unrated_and_strictest_wins():
    assert kl.rating_allowed(["G"], L)[0] and kl.rating_allowed(["PG"], L)[0]
    assert not kl.rating_allowed(["12"], L)[0] and not kl.rating_allowed([None], L)[0]
    assert not kl.rating_allowed(["G", "15"], L)[0] and kl.strictest(["PG", "12", None]) == "12"
    assert kl.rating_allowed([None], {**L, "unrated": "allow"})[0] and kl.rating_allowed(["18"], {})[0]


@pytest.mark.parametrize("day,h,m,expect", [(0, 19, 59, False), (0, 20, 0, True), (0, 23, 59, True),
                                           (1, 0, 30, True), (1, 6, 59, True), (1, 7, 0, False),
                                           (5, 22, 30, True), (5, 23, 0, False), (3, 21, 0, False)])
def test_bedtime_including_midnight_crossing(day, h, m, expect):
    assert kl.in_bedtime(L, at(day, h, m)) is expect


def test_decisions_gate_starts_only_and_override_is_explicit():
    night = at(0, 21)
    assert kl.decide("play", "Sam", L, night) == (False, "It's past bedtime on Sam's profile.")
    for a in ("pause", "stop", "volume_down"):
        assert kl.decide(a, "Sam", L, night)[0]
    assert kl.decide("play", "Sam", L, night, override=True)[0]
    day = at(2, 10)
    assert not kl.decide("play", "Sam", L, day, used_minutes=60)[0] and kl.decide("play", "Sam", L, day, used_minutes=59)[0]
    assert not kl.decide("queue_play", "Sam", L, day, item_ratings=["15"])[0]
    assert kl.decide("seek", "Sam", L, night)[0]


def test_kid_listing_hides_blocked_items():
    items = [{"id": 1, "ratings": ["G"]}, {"id": 2, "ratings": ["18"]}, {"id": 3, "ratings": []}]
    assert [i["id"] for i in kl.filter_listing(items, L)] == [1]
