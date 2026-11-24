"""Idle join-slate policy (#420): GTK-free, no receiver, no TV."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import idle_slate
from idle_slate import SlateState, decide, is_ours, receiver_is_free, slate_url

PORTAL = "http://192.168.1.20:50000/"
SLATE = PORTAL + "join-slate.png"
BACKDROP = {"player_state": "IDLE", "app_id": "E8C28D3C"}
ROOT = Path(__file__).resolve().parents[1]


def armed(at=100.0, device="Lounge"):
    return SlateState(armed_at=at, device=device)


def ask(state, now=140.0, **over):
    args = dict(now=now, enabled=True, device="Lounge", is_cast=True,
                portal_url=PORTAL, busy=False, session_active=False, info=BACKDROP)
    args.update(over)
    return decide(state, **args)


def test_slate_url_is_numeric_room_url_only():
    assert slate_url(PORTAL) == SLATE
    for bad in (None, "", "http://smoothcast.local:5000/", "http://1.2.3.4:5/x", "https://1.2.3.4:5/"):
        assert slate_url(bad) is None


@pytest.mark.parametrize("info, free", [
    ({"app_id": None, "player_state": "IDLE"}, True),
    (BACKDROP, True),
    ({"app_id": "CC1AD845", "player_state": "IDLE"}, True),       # our finished film
    ({"app_id": "CC1AD845", "player_state": "PLAYING"}, False),
    ({"app_id": "CC1AD845", "player_state": "PAUSED"}, False),
    ({"app_id": "233637DE", "player_state": "IDLE"}, False),       # another app (Netflix etc.)
    ({"player_state": "IDLE"}, False),                             # no proof: fail closed
    ({"app_id": None, "is_stand_by": True}, False),
    ({"app_id": None, "is_active_input": False}, False),
    (None, False), ({}, False), ("IDLE", False),
])
def test_receiver_is_free_fails_closed(info, free):
    assert receiver_is_free(info) is free


def test_casts_once_after_delay_when_free():
    state = armed()
    assert ask(state, now=110.0) == "wait"
    assert ask(state, now=130.0) == "cast"


def test_never_casts_unarmed_or_without_proof():
    assert ask(SlateState()) == "none"
    assert ask(armed(), info={"player_state": "IDLE"}) == "clear"
    assert ask(armed(), info={"player_state": "IDLE", "app_id": "233637DE"}) == "clear"
    assert ask(armed(), info=None) == "wait"


@pytest.mark.parametrize("over", [
    {"enabled": False}, {"is_cast": False}, {"device": "Kitchen"}, {"session_active": True},
    {"portal_url": None}, {"portal_url": "http://smoothcast.local:5000/"},
])
def test_other_conditions_clear_the_arming(over):
    assert ask(armed(), **over) == "clear"


def test_busy_waits_and_long_wait_gives_up():
    assert ask(armed(), busy=True) == "wait"
    assert ask(armed(), now=100 + idle_slate.GIVE_UP_SECONDS + 1, busy=True) == "clear"


def test_after_cast_it_is_never_recast():
    state = armed()
    state.shown_url, state.shown_at = SLATE, 140.0
    shown = {"app_id": "CC1AD845", "player_state": "IDLE", "content_id": SLATE}
    assert ask(state, now=150.0, info=shown) == "none" and state.seen
    assert ask(state, now=151.0, info=BACKDROP) == "clear"     # ended or replaced
    assert ask(armed(), now=1e9, info=BACKDROP) == "clear"


def test_unreported_cast_is_forgotten_not_repeated():
    state = armed()
    state.shown_url, state.shown_at = SLATE, 140.0
    assert ask(state, now=150.0, info=BACKDROP) == "none"
    assert ask(state, now=140.0 + idle_slate.UNSEEN_SECONDS + 1, info=BACKDROP) == "clear"


def test_is_ours_requires_exact_url():
    assert is_ours({"content_id": SLATE}, SLATE)
    assert not is_ours({"content_id": SLATE + "?x"}, SLATE)
    assert not is_ours({"content_id": SLATE}, None) and not is_ours(None, SLATE)


def window(enabled=True, renderer=None, info=BACKDROP):
    calls = []
    win = SimpleNamespace(
        cfg={"idle_join_slate": enabled}, busy=False, session=None, device_info=info,
        _portal=SimpleNamespace(url=PORTAL), _console=lambda m: calls.append(("log", m)),
        _device=lambda: "Lounge", _dlna_renderer=lambda _d=None: renderer)
    return win, calls


def test_arm_requires_setting_and_cast_target():
    win, _ = window(enabled=False)
    idle_slate.arm(win)
    assert win._slate.armed_at is None
    win, _ = window(renderer=object())
    idle_slate.arm(win)
    assert win._slate.armed_at is None
    win, _ = window()
    idle_slate.arm(win)
    assert win._slate.armed_at is not None and win._slate.device == "Lounge"
    idle_slate.clear(win)
    assert win._slate.armed_at is None


def test_tick_casts_exact_url_without_touching_ownership(monkeypatch):
    import castctl
    sent = []
    monkeypatch.setattr(castctl, "command", lambda *a, **k: sent.append(a) or (True, ""))
    win, _ = window()
    idle_slate.arm(win)
    win._slate.armed_at -= 31
    ran = []
    idle_slate.tick(win, lambda fn, **kw: ran.append(fn()) or kw["done"](ran[-1]))
    assert sent == [("Lounge", "cast", "--no-subs", SLATE)]
    assert win._slate.shown_url == SLATE
    assert (win.busy, win.session) == (False, None) and not hasattr(win, "external")
    idle_slate.tick(win, lambda *a, **k: pytest.fail("must not cast twice"))


def test_tick_failure_clears_and_logs_quietly(monkeypatch):
    import castctl
    monkeypatch.setattr(castctl, "command", lambda *a, **k: (False, "no"))
    win, calls = window()
    idle_slate.arm(win)
    win._slate.armed_at -= 31
    idle_slate.tick(win, lambda fn, **kw: kw["done"](fn()))
    assert win._slate.armed_at is None and calls and calls[0][0] == "log"


def test_slate_module_never_assigns_ownership_state():
    source = (ROOT / "src" / "idle_slate.py").read_text()
    for name in ("win.busy =", "win.session =", "win.external =", "win.now_playing =", "_url_cast_url ="):
        assert name not in source
