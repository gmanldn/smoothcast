"""Opt-in join-code slate for an idle Cast TV (#420). GTK-free policy.

After SmoothCast's *own* playback ends or is stopped, and only when the user
enabled "Show join code on the TV when idle", the room's ``/join-slate.png`` is
cast to the same receiver. The TV is demonstrably on at that moment, so this
never wakes a TV through HDMI-CEC. Every guard fails closed: when the receiver
status cannot prove it is free (no ``app_id`` key, another app, TV on standby or
another input) nothing is cast. The slate never touches ``session``,
``external`` or ``busy``, so it cannot take over a receiver or block a command.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DELAY_SECONDS = 30.0      # wait after playback ends before showing the slate
GIVE_UP_SECONDS = 600.0   # stop waiting for a free receiver after this long
UNSEEN_SECONDS = 60.0     # forget a cast the receiver never reported back
BACKDROP_APP_ID = "E8C28D3C"
MEDIA_RECEIVER_APP_ID = "CC1AD845"
SLATE_PATH = "join-slate.png"
_NUMERIC_ROOM_URL = re.compile(r"http://(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}/")


@dataclass
class SlateState:
    armed_at: float | None = None
    device: str | None = None
    shown_url: str | None = None
    shown_at: float = 0.0
    seen: bool = False


def slate_url(portal_url: object) -> str | None:
    """Numeric room URL + slate path; anything else (no portal, a name) is None."""
    if not isinstance(portal_url, str) or not _NUMERIC_ROOM_URL.fullmatch(portal_url):
        return None
    return portal_url + SLATE_PATH


def receiver_is_free(info: object) -> bool:
    """True only when the receiver proves nothing else is using the TV."""
    if not isinstance(info, dict) or "app_id" not in info:
        return False
    if info.get("is_stand_by") is True or info.get("is_active_input") is False:
        return False
    app_id = info["app_id"]
    if app_id in (None, "", BACKDROP_APP_ID):
        return True
    # Our own finished film leaves the default receiver parked and IDLE.
    state = str(info.get("player_state") or "").upper()
    return app_id == MEDIA_RECEIVER_APP_ID and state == "IDLE"


def is_ours(info: object, url: str | None) -> bool:
    """True while the receiver still shows the exact slate URL we cast."""
    if not url or not isinstance(info, dict):
        return False
    return str(info.get("content_id") or "").strip() == url


def decide(state: SlateState, *, now: float, enabled: bool, device: str,
           is_cast: bool, portal_url: object, busy: bool,
           session_active: bool, info: object) -> str:
    """Return ``cast``, ``wait``, ``clear`` or ``none`` for this status poll."""
    if state.armed_at is None:
        return "none"
    if (not enabled or not is_cast or device != state.device or session_active
            or now < state.armed_at):
        return "clear"
    if state.shown_url is not None:
        if is_ours(info, state.shown_url):
            state.seen = True
            return "none"
        if state.seen or now - state.shown_at > UNSEEN_SECONDS:
            return "clear"  # replaced, ended or timed out: never re-cast
        return "none"
    if now - state.armed_at > GIVE_UP_SECONDS or slate_url(portal_url) is None:
        return "clear"
    if busy or now - state.armed_at < DELAY_SECONDS or info is None:
        return "wait"
    return "cast" if receiver_is_free(info) else "clear"


def _state(win) -> SlateState:
    state = getattr(win, "_slate", None)
    if state is None:
        state = win._slate = SlateState()
    return state


def arm(win) -> None:
    """Call when our own playback has ended or was stopped by the user."""
    state = _state(win)
    clear(win)
    if win.cfg.get("idle_join_slate", False) and win._dlna_renderer(win._device()) is None:
        import time
        state.armed_at, state.device = time.monotonic(), win._device()


def clear(win) -> None:
    state = _state(win)
    state.armed_at = state.device = state.shown_url = None
    state.seen = False


def owns(win, info: object) -> bool:
    """True while this window's slate is on screen (not external playback)."""
    return is_ours(info, _state(win).shown_url)


def tick(win, run) -> None:
    """Advance the policy once per receiver poll; ``run`` is ``Async.run``."""
    import time
    state = _state(win)
    if state.armed_at is None:
        return
    device = win._device()
    portal = getattr(win, "_portal", None)
    action = decide(
        state, now=time.monotonic(), enabled=bool(win.cfg.get("idle_join_slate", False)),
        device=device, is_cast=win._dlna_renderer(device) is None,
        portal_url=getattr(portal, "url", None), busy=bool(win.busy),
        session_active=win.session is not None, info=win.device_info,
    )
    if action == "clear":
        clear(win)
    elif action == "cast":
        import castctl
        url = slate_url(portal.url)
        state.shown_url, state.shown_at = url, time.monotonic()

        def failed(message):
            clear(win)
            win._console(f"Join slate not shown: {message}")

        def done(result):
            if not result[0]:
                failed(result[1] or "receiver refused it")

        run(lambda: castctl.command(device, "cast", "--no-subs", url, timeout=30),
            done=done, failed=failed, domain="transport")
