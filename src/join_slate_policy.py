"""GTK-free decisions for the opt-in "show join code on the TV when idle" slate (#420).

The slate is a still image cast to a Google Cast receiver. It must never take a
TV someone else is using, so every check fails closed: when the receiver status
does not prove the TV is free, nothing is cast.
"""
from __future__ import annotations

import ipaddress
from typing import Mapping

import portal_join

BACKDROP_APP_ID = "E8C28D3C"
DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"
# No app, the Cast home screen, or the Default Media Receiver SmoothCast itself uses.
FREE_APP_IDS = frozenset({"", BACKDROP_APP_ID, DEFAULT_MEDIA_RECEIVER_APP_ID})
IDLE_STATES = frozenset({"IDLE", "UNKNOWN", ""})
MIN_IDLE_SECONDS = 60.0
BACKOFF_SECONDS = 600.0
SLATE_PATH = "join-slate.png"


def slate_url(room_url: object) -> str | None:
    """The slate address a TV can fetch, or None when the room is not LAN-reachable."""
    if not isinstance(room_url, str) or not portal_join.is_room_url(room_url):
        return None
    host = room_url[len("http://"):].split(":", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.is_loopback or address.is_unspecified:
        return None
    return room_url + SLATE_PATH


def is_showing(info: Mapping[str, object] | None, url: str) -> bool:
    """True while the receiver still reports our exact slate (image state varies)."""
    return (isinstance(info, Mapping) and bool(url)
            and str(info.get("content_id") or "").strip() == url
            and info.get("app_id") == DEFAULT_MEDIA_RECEIVER_APP_ID)


def receiver_is_free(info: Mapping[str, object] | None) -> bool:
    """Receiver proven idle and not running someone else's app."""
    if not isinstance(info, Mapping) or "app_id" not in info:
        return False  # older backend or no status: cannot prove it is free
    if info.get("app_id") not in FREE_APP_IDS:
        return False
    return str(info.get("player_state") or "").upper() in IDLE_STATES


def should_show(*, enabled: bool, is_cast_target: bool, session_active: bool,
                external: bool, queue_len: int, busy: bool,
                info: Mapping[str, object] | None, url: str | None,
                idle_seconds: float, backoff_remaining: float = 0.0,
                min_idle: float = MIN_IDLE_SECONDS) -> bool:
    if not (enabled and is_cast_target and url):
        return False
    if session_active or external or busy or queue_len > 0:
        return False
    if backoff_remaining > 0 or idle_seconds < min_idle:
        return False
    if is_showing(info, url):
        return False  # already on screen
    return receiver_is_free(info)


def should_clear(info: Mapping[str, object] | None, url: str | None) -> bool:
    """Stop only while the receiver still shows our slate; never a replacement."""
    return bool(url) and is_showing(info, url or "")
