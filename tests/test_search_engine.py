"""#409: query parsing and the local FTS5 search engine."""
from __future__ import annotations

from pathlib import Path
import random
import string
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_index_v2 as li
import search_engine
import search_query


def library(tmp_path, rows):
    idx = li.LibraryIndexer(tmp_path / "db.sqlite3", probe=lambda p: {})
    for i, spec in enumerate(rows):
        entry = {c: None for c in li.ENTRY_COLUMNS}
        entry.update(content_key=f"qh:{i:032d}", folder_id="f_1", rel_path=f"{i}.x", kind="video",
                     size=1, mtime_ns=1, ino=str(i), sort_title=spec["title"].casefold())
        entry.update(spec)
        entry["sort_title"] = entry["title"].casefold()
        idx._upsert(entry, None)
    return idx


def titles(result):
    out = []
    for g in result["groups"]:
        for item in g["items"]:
            out.append(item.get("title") or item.get("name"))
    return out


def test_diacritics_prefix_and_typo(tmp_path):
    idx = library(tmp_path, [{"title": "Amélie"}, {"title": "Paddington 2"}, {"title": "Paddington"}])
    assert "Amélie" in titles(idx.search("amelie"))
    assert "Amélie" in titles(idx.search("AMÉL"))               # prefix, accents
    assert "Paddington" in titles(idx.search("padingtn"))       # trigram typo tolerance
    assert titles(idx.search("zzzzqq")) == []


def test_exact_title_ranks_first_and_ties_are_deterministic(tmp_path):
    idx = library(tmp_path, [{"title": "Paddington 2"}, {"title": "Paddington"},
                             {"title": "Paddington Station"}])
    first = titles(idx.search("paddington"))
    assert first[0] == "Paddington"
    assert first == titles(idx.search("paddington"))


def test_filters_kind_year_artist(tmp_path):
    idx = library(tmp_path, [
        {"title": "Dancing Queen", "kind": "music", "artist": "ABBA", "album": "Arrival", "year": 1976},
        {"title": "Thriller", "kind": "music", "artist": "Michael Jackson", "year": 1982},
        {"title": "Alien", "year": 1979},
        {"title": "Dr Who", "show": "Doctor Who", "season": 1, "episode": 1}])
    assert titles(idx.search("kind:music")) == ["ABBA", "Arrival", "Dancing Queen", "Thriller"] \
        or "Dancing Queen" in titles(idx.search("kind:music"))
    assert "Thriller" in titles(idx.search("year:1980s kind:music"))
    assert "Dancing Queen" not in titles(idx.search("year:1980s kind:music"))
    assert "Dancing Queen" in titles(idx.search("artist:abba"))
    assert titles(idx.search("kind:film")) == ["Alien"]
    groups = {g["type"] for g in idx.search("kind:show")["groups"]}
    assert groups == {"shows"}


def test_hostile_fts_syntax_never_raises(tmp_path):
    idx = library(tmp_path, [{"title": "Hello World"}])
    rng = random.Random(7)
    alphabet = string.printable + "éü‮\x00"
    for _ in range(500):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        result = idx.search(text)
        assert isinstance(result["groups"], list)
    for text in ['"', "*", "NEAR(", "a OR", "title:", "-x", "(((", "\\"]:
        idx.search(text)


def test_deadline_returns_partial_instead_of_hanging(tmp_path, monkeypatch):
    idx = library(tmp_path, [{"title": f"Item {i}"} for i in range(50)])
    monkeypatch.setattr(search_engine, "PROGRESS_OPS", 1)
    result = search_engine.search(idx._conn, "item", deadline=-1)
    assert result["partial"] is True and result["groups"] == []


def test_pagination_and_cursor(tmp_path):
    idx = library(tmp_path, [{"title": f"Song {i:02d}", "kind": "music"} for i in range(7)])
    page1 = idx.search("song", limit=3)
    assert page1["next"] and len(titles(page1)) >= 3
    seen = []
    cursor = None
    while True:
        page = idx.search("song", limit=3, cursor=cursor)
        seen += [i["id"] for g in page["groups"] if g["type"] == "songs" for i in g["items"]]
        cursor = page["next"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 7


def test_index_changes_reach_fts(tmp_path):
    idx = library(tmp_path, [{"title": "Old Name"}])
    assert titles(idx.search("old"))
    idx._conn.execute("DELETE FROM entries")
    idx._conn.commit()
    assert titles(idx.search("old")) == []


def test_query_parser():
    q = search_query.parse('Amélie kind:music year:1990s artist:"The Beatles"')
    assert q.terms == ["amelie"] and q.filters["kind"] == "music" and q.filters["artist"] == "the beatles"
    assert search_query.year_range("1990s") == (1990, 1999)
    assert search_query.year_range("abc") is None
    assert search_query.fts_expression(["a", "b"]) == '"a" "b"*'
    assert len(search_query.normalise("x" * 1000)) == search_query.MAX_QUERY


def test_search_api_requires_session_and_returns_groups(tmp_path):
    from test_room_conformance import RoomHarness
    idx = library(tmp_path, [{"title": "Paddington 2"}, {"title": "Dancing Queen", "kind": "music",
                                                          "artist": "ABBA"}])
    harness = RoomHarness(count=1)
    try:
        harness.server.library_search = idx.search
        status, _, _ = harness.request("GET", "/api/search?q=padd")
        assert status in (401, 403)
        guest = harness.login("Alice")
        status, body, _ = harness.request("GET", "/api/search?q=padd", cookie=guest.cookie)
        assert status == 200 and body["groups"][0]["type"] == "films"
        status, body, _ = harness.request("GET", "/api/search?q=", cookie=guest.cookie)
        assert status == 400
        status, body, _ = harness.request("GET", "/api/search?q=%22%20NEAR(%20*", cookie=guest.cookie)
        assert status == 200
    finally:
        harness.close()
