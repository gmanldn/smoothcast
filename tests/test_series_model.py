import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import series_model as sm

CASES = [
    ("Breaking.Bad.S02E05.720p.BluRay.x264.mkv", ("Breaking Bad", 2, 5, None)),
    ("The Office (US) - S03E10 - Business Ethics.mkv", ("The Office (US)", 3, 10, None)),
    ("show.name.s1e2.mp4", ("show name", 1, 2, None)),
    ("Show Name 1x02 Pilot.avi", ("Show Name", 1, 2, None)),
    ("Show Name - Season 1 Episode 2 - Pilot.mkv", ("Show Name", 1, 2, None)),
    ("Friends S01E01-E02.mkv", ("Friends", 1, 1, 2)),
    ("Friends.S01E01E02.mkv", ("Friends", 1, 1, 2)),
    ("Doctor Who S00E01 Special.mkv", ("Doctor Who", 0, 1, None)),
    ("[Group] Naruto - 012 [720p].mkv", ("Naruto", 1, 12, None)),
    ("One Piece - 1015.mkv", ("One Piece", 1, 1015, None)),
    ("Heat (1995).mkv", None), ("Blade Runner 2049 - 2017.mkv", None), ("holiday video.mp4", None),
    ("Seinfeld/Season 2/Seinfeld S02E03.mkv", ("Seinfeld", 2, 3, None)),
]


@pytest.mark.parametrize("name,expect", CASES)
def test_filename_table(name, expect):
    p = sm.parse(name)
    got = None if p is None else (p["show"], p["season"], p["episode"], p["episode_end"])
    assert got == expect


def test_tags_win_and_titles_cleaned():
    p = sm.parse("whatever.mkv", {"show": "Lost", "season": "2", "episode": "4", "title": "Fire"})
    assert (p["show"], p["season"], p["episode"], p["title"]) == ("Lost", 2, 4, "Fire")
    assert sm.parse("The.Fog.S02E06.The.Fog.1080p.WEB-DL.mkv")["title"] == "The Fog"


def lib():
    return sm.group([{"key": f"k{s}{e}", "name": f"Show.S0{s}E0{e}.mkv"} for s in (1, 2) for e in (1, 2, 3)]
                    + [{"key": "sp", "name": "Show.S00E01.mkv"}, {"key": "f", "name": "Heat (1995).mkv"}])


def test_group_orders_and_next_episode_crosses_seasons_specials_last():
    shows, films = lib()
    seasons = shows["show"]
    assert [f["key"] for f in films] == ["f"] and sorted(seasons) == [0, 1, 2]
    assert sm.next_episode(seasons, "k13")["key"] == "k21" and sm.next_episode(seasons, "k23")["key"] == "sp"
    assert sm.next_episode(seasons, "sp") is None and sm.next_episode(seasons, "nope") is None


def test_next_never_skips_a_blocked_episode():
    seasons = lib()[0]["show"]
    assert sm.next_episode(seasons, "k11", allowed=lambda e: e["key"] != "k12") is None


def test_autoplay_countdown_cancel_and_still_watching():
    a = sm.Autoplay(); nxt = {"key": "k", "season": 2, "episode": 6, "title": "The Fog"}
    assert a.offer(nxt)["message"] == "Next: S02E06 'The Fog' in 10…"
    for _ in range(3):
        a.started_automatically()
    assert a.offer(nxt)["kind"] == "still_watching"
    a.interaction(); assert a.offer(nxt)["kind"] == "countdown"
    a.cancel(); assert a.offer(nxt) is None and sm.Autoplay(False).offer(None) is None
