from src import transfer_progress as P

MB = P.MIB


def meter(*samples):
    m = P.Meter()
    for t, b in samples:
        m.sample(t, b)
    return m


def test_ema_smooths_and_resets_on_resume_rewind():
    m = meter((0, 0), (1, 10 * MB), (2, 30 * MB))
    assert m.inst == 20 * MB and round(m.speed / MB, 1) == 13.0   # .3*20+.7*10
    m.sample(3, 5 * MB)
    assert m.speed == 0
    m.sample(float("nan"), 1)
    m.sample(4, True)
    assert m.last == (3, 5 * MB)


def test_eta_is_a_range_not_false_precision():
    assert P.eta_range(0, 0) == "a moment" and P.eta_range(100, 0) is None
    assert P.eta_range(5 * MB, 1 * MB) == "a few seconds"
    assert P.eta_range(100 * MB, 2 * MB) == "35–75 seconds"
    assert P.eta_range(3000 * MB, 5 * MB) == "7–15 minutes"


def row(**kw):
    s = {"name": "a.mp4", "state": "transferring", "size": 100 * MB, "received_bytes": 40 * MB, "durable_bytes": 0, "target": {"node": "Den PC"}}
    s.update(kw)
    return s


def test_view_progress_speed_route_and_aria():
    v = P.view(row(), meter((0, 0), (1, 10 * MB)), dest="Lounge TV")
    assert v["percent"] == 40 and v["label"] == "Sending" and v["can_pause"]
    assert v["detail"].startswith("40.0 MB of 100.0 MB · 10.0 MB/s · about ")
    assert v["route"] == "This device → Den PC → Lounge TV · Still on your device"
    assert v["aria"] == "a.mp4: Sending, 40 percent"
    assert "Stored on Den PC" in P.view(row(durable_bytes=1), P.Meter())["route"]


def test_never_claims_playing_before_receiver_confirms():
    assert P.view(row(state="playing"), P.Meter())["label"] == "Ready to play"
    assert P.view(row(state="playing"), P.Meter(), receiver_confirmed=True)["label"] == "Playing"


def test_lost_file_offers_resume_invitation_not_auto_continue():
    v = P.view(row(), P.Meter(), file_available=False)
    assert v["label"] == "Paused" and "same file again" in v["resume"] and v["can_cancel"] and not v["can_pause"]


def test_unknown_state_and_junk_numbers_are_safe():
    v = P.view({"state": "weird", "size": "x", "received_bytes": -1}, P.Meter())
    assert v["label"] == "Didn't work" and v["percent"] == 0 and v["detail"] == ""


def test_same_file_check():
    a = {"name": "a.mp4", "size": 5, "last_modified": 1}
    assert P.same_file(a, {"name": "a.mp4", "size": 5})
    assert not P.same_file(a, {"name": "a.mp4", "size": 6})
    assert not P.same_file(a, {"name": "a.mp4", "size": 5, "last_modified": 2})


def test_cast_confirm_never_silently_picks():
    assert P.cast_confirm("Film", "TV", ["TV", "Den"]) == {"ask": "Cast Film to TV?", "suggest": "TV", "can_confirm": True}
    r = P.cast_confirm("Film", None, ["Den"])
    assert r["suggest"] == "Den" and not r["can_confirm"]
    assert "Up Next" in P.cast_confirm("Film", "TV", [])["ask"]
