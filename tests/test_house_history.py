import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import house_history as h

LOUNGE = {"id": "lounge", "name": "Lounge"}
KIDS = {"id": "kids", "name": "Kids", "private_to": ["sam"]}
FILM = {"content_key": "qh:film-1", "title": "Film One"}


def mk(path=None):
    t = [1_700_000_000.0]; return h.History(path, lambda: t[0]), t


def test_short_plays_are_not_recorded_and_long_ones_are_finalised():
    hh, t = mk(); a = hh.start(LOUNGE, FILM); assert hh.stop(a, 59) and hh.events == []
    b = hh.start(LOUNGE, FILM); assert hh.stop(b, 60) and hh.events[0]["watched_seconds"] == 60
    c = hh.start(LOUNGE, FILM); assert hh.stop(c, None) and len(hh.events) == 1 and hh.stop(999, 100) is False


def test_retention_by_count_and_by_age_and_clear_is_host_only():
    hh, t = mk()
    for i in range(h.MAX_EVENTS + 5): hh.events.append({"seq": i + 1, "ts": t[0], "watched_seconds": 100, "room": "r", "room_id": "r", "title": "t", "content_key": "k", "resident": None, "private_to": []})
    hh.seq = h.MAX_EVENTS + 5; hh.start(LOUNGE, FILM)
    assert len(hh.events) == h.MAX_EVENTS and hh.events[0]["seq"] == 7
    old, t2 = mk(); old.start(LOUNGE, FILM); t2[0] += h.MAX_AGE_S + 1; old.start(LOUNGE, FILM); assert [e["seq"] for e in old.events] == [2]
    assert hh.clear("guest") is False and hh.clear("resident") is False and len(hh.events) == h.MAX_EVENTS and hh.clear("host") and hh.events == []


def test_private_room_events_only_for_owners_not_even_host():
    hh, t = mk(); hh.stop(hh.start(LOUNGE, FILM), 100); hh.stop(hh.start(KIDS, {"content_key": "qh:k", "title": "Secret"}), 100)
    titles = lambda actor, role: [e["title"] for e in hh.listing(actor, role)["events"]]
    assert titles("sam", "resident") == ["Secret", "Film One"]
    assert titles("lee", "resident") == ["Film One"] and titles(None, "host") == ["Film One"] and titles(None, "guest") == ["Something"]


def test_guest_and_privacy_mode_hide_titles_keys_and_people():
    hh, t = mk(); hh.stop(hh.start(LOUNGE, FILM, "sam"), 100)
    g = hh.listing(None, "guest")["events"][0]; assert g["title"] == "Something" and g["content_key"] is None and g["resident"] is None
    p = hh.listing("sam", "resident", privacy="titles_hidden")["events"][0]; assert p["title"] == "Something"
    r = hh.listing("sam", "resident")["events"][0]; assert r["title"] == "Film One" and r["content_key"] == "qh:film-1" and r["resident"] == "sam"
    assert "Film One" not in json.dumps(hh.listing(None, "guest"))


def test_cursor_paging_newest_first_without_gaps_or_dupes():
    hh, t = mk()
    for i in range(7): hh.stop(hh.start(LOUNGE, {"content_key": f"k{i}", "title": f"T{i}"}), 100)
    seen, cur = [], None
    while True:
        pg = hh.listing("x", "resident", cur, limit=3); seen += [e["seq"] for e in pg["events"]]; cur = pg["next_cursor"]
        if cur is None: break
    assert seen == [7, 6, 5, 4, 3, 2, 1]


def test_persistence_drops_unfinished_plays_and_survives_corruption(tmp_path):
    f = tmp_path / "hh.json"; hh, t = mk(f); hh.stop(hh.start(LOUNGE, FILM), 100); hh.start(LOUNGE, FILM)       # second never stopped (crash)
    r = h.History(f); assert [e["seq"] for e in r.events] == [1] and r.seq == 2
    f.write_text("{x"); assert h.History(f).events == []


def test_group_by_day_and_room():
    hh, t = mk()
    for room in (LOUNGE, KIDS, LOUNGE): hh.stop(hh.start(room, FILM), 100)
    t[0] += 86400; hh.stop(hh.start(LOUNGE, FILM), 100)
    g = h.group_by_day_room(hh.listing("sam", "resident")["events"])
    assert [d["day"] for d in g] == ["2023-11-15", "2023-11-14"] and [r["room"] for r in g[1]["rooms"]] == ["Lounge", "Kids"] and len(g[1]["rooms"][0]["events"]) == 2
