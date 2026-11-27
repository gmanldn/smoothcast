import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import house_rules as hr

KIDS = {"days": ["mon", "tue", "wed", "thu", "sun"], "start": "19:30", "end": "07:00", "cap": 0.3, "block_new": False}
HOUSE = {"days": [], "start": "23:00", "end": "23:59", "cap": 0.5, "block_new": True}
MON = datetime(2026, 11, 23)      # Monday


def at(day, h, m=0):
    return MON + timedelta(days=day, hours=h, minutes=m)


@pytest.mark.parametrize("day,h,m,expect", [(0, 19, 29, False), (0, 19, 30, True), (1, 6, 59, True), (1, 7, 0, False),
                                           (4, 20, 0, False), (5, 3, 0, False), (5, 23, 0, False), (6, 20, 0, True), (0, 3, 0, True)])
def test_midnight_crossing_belongs_to_start_day(day, h, m, expect):
    assert bool(hr.active([KIDS], at(day, h, m))) is expect          # Fri night not in days; Sat 03:00 tail is Fri's -> False; Mon 03:00 tail is Sun's -> True


def test_clamp_and_message_and_marker():
    e = hr.effective([KIDS], at(0, 21))
    assert e["cap"] == 0.3 and e["message"] == "Quiet hours: max 30% until 7:00."
    assert hr.clamp(0.8, e) == (0.3, True) and hr.clamp(0.2, e) == (0.2, False)
    assert hr.effective([KIDS], at(0, 12))["cap"] is None and hr.clamp(1.0, hr.effective([], at(0, 12))) == (1.0, False)


def test_strictest_wins_with_guest_ceiling_and_block_new():
    both = hr.effective([KIDS, {**HOUSE, "days": list(hr.DAYS), "start": "19:00", "end": "23:59"}], at(0, 23, 10), guest_ceiling=0.2)
    assert both["cap"] == 0.2 and both["block_new"]
    assert hr.effective([KIDS], at(0, 21), guest_ceiling=0.6)["cap"] == 0.3
    assert hr.effective([], at(0, 12), guest_ceiling=0.6)["cap"] == 0.6


def test_fade_only_when_quiet_just_started_and_too_loud():
    e = hr.effective([KIDS], at(0, 19, 30))
    assert hr.fade_plan(0.7, e, True) == {"from": 0.7, "to": 0.3, "seconds": 5.0}
    assert hr.fade_plan(0.2, e, True) is None and hr.fade_plan(0.7, e, False) is None
    assert hr.transitioned([KIDS], at(0, 19, 29), at(0, 19, 30)) and not hr.transitioned([KIDS], at(0, 19, 30), at(0, 19, 31))


def test_block_new_message_host_bypass_and_override_expires_after_one_hour():
    e = hr.effective([{**HOUSE, "days": list(hr.DAYS)}], at(1, 23, 10))
    ok, why = hr.can_start(e); assert not ok and "quiet time" in why and hr.can_start(e, host=True)[0]
    until = hr.override(1000.0)
    assert until == 1000 + 3600
    r = [{**HOUSE, "days": list(hr.DAYS)}]
    during = hr.effective(r, at(1, 23, 10), override_until=until, now=2000)
    assert during["override"] and during["cap"] is None and not during["block_new"]
    after = hr.effective(r, at(1, 23, 10), override_until=until, now=until)
    assert not after["override"] and after["block_new"]


def test_bad_rules_are_ignored_not_fatal():
    assert hr.active([{"start": "bogus"}, {}, None], at(0, 21)) == []
