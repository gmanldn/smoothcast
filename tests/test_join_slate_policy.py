"""Idle join-slate decisions: never take a TV someone else is using (#420)."""
import pytest

import join_slate_policy as policy
from join_slate_policy import (BACKDROP_APP_ID, DEFAULT_MEDIA_RECEIVER_APP_ID,
                               is_showing, receiver_is_free, should_clear,
                               should_show, slate_url)

URL = "http://192.168.1.20:8080/join-slate.png"
IDLE = {"player_state": "IDLE", "app_id": ""}


def show(**over):
    args = dict(enabled=True, is_cast_target=True, session_active=False,
                external=False, queue_len=0, busy=False, info=IDLE, url=URL,
                idle_seconds=120.0)
    args.update(over)
    return should_show(**args)


def test_shows_only_when_everything_proves_the_room_is_idle():
    assert show() is True
    assert show(info={"player_state": "IDLE", "app_id": BACKDROP_APP_ID}) is True
    # Film just finished on SmoothCast's own Default Media Receiver.
    assert show(info={"player_state": "IDLE", "idle_reason": "FINISHED",
                      "content_id": "http://x/film.mp4",
                      "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID}) is True


@pytest.mark.parametrize("over", [
    {"enabled": False}, {"is_cast_target": False}, {"url": None},
    {"session_active": True}, {"external": True}, {"queue_len": 1},
    {"busy": True}, {"idle_seconds": 59.0}, {"backoff_remaining": 5.0},
    {"info": None},
])
def test_any_unmet_condition_blocks_the_slate(over):
    assert show(**over) is False


@pytest.mark.parametrize("info", [
    {"player_state": "IDLE", "app_id": "233637DE"},        # YouTube running
    {"player_state": "IDLE"},                              # backend cannot see the app
    {"player_state": "PLAYING", "app_id": ""},
    {"player_state": "PAUSED", "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID},
    {"player_state": "BUFFERING", "app_id": BACKDROP_APP_ID},
])
def test_other_apps_unknown_apps_and_active_playback_are_never_replaced(info):
    assert receiver_is_free(info) is False
    assert show(info=info) is False


def test_already_showing_slate_is_not_cast_again():
    info = {"player_state": "PLAYING", "content_id": URL,
            "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID}
    assert is_showing(info, URL) is True
    assert show(info=info) is False


def test_clear_only_when_receiver_still_shows_our_exact_slate():
    ours = {"player_state": "IDLE", "content_id": URL,
            "app_id": DEFAULT_MEDIA_RECEIVER_APP_ID}
    assert should_clear(ours, URL) is True
    assert should_clear({**ours, "content_id": URL + "?x"}, URL) is False
    assert should_clear({**ours, "app_id": "233637DE"}, URL) is False
    assert should_clear(None, URL) is False and should_clear(ours, None) is False


@pytest.mark.parametrize("room, expected", [
    ("http://192.168.1.20:8080/", "http://192.168.1.20:8080/join-slate.png"),
    ("http://127.0.0.1:8080/", None),
    ("http://0.0.0.0:8080/", None),
    ("http://smoothcast.local:8080/", None),
    ("http://192.168.1.20:8080/?pin=1", None),
    (None, None),
])
def test_slate_url_is_only_a_lan_reachable_numeric_address(room, expected):
    assert slate_url(room) == expected


def test_policy_module_has_no_gtk_dependency():
    assert "gi" not in vars(policy)
