import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import music_catalog as mc

ITEMS = [{"rel": f"Abba/Arrival/{i:02d}.mp3", "title": f"Song {i}", "artist": "Abba", "album": "Arrival", "track": i, "duration": 200}
         for i in range(1, 101)] + [{"rel": "../etc/passwd"}, {"rel": "/abs.mp3"}]


def cat():
    c = mc.Catalog(b"k"); c.share("/music"); c.load("/music", ITEMS); return c


def test_hundred_songs_searchable_paths_hidden_and_traversal_skipped():
    c = cat()
    r = c.search("song 7")
    assert r["total"] == 11 and "/music" not in json.dumps(r) and "rel" not in json.dumps(r)
    assert c.search(artist="Abba")["total"] == 100 and c.search(artist="Nobody")["total"] == 0


def test_pages_are_capped_and_ordered():
    c = cat()
    page = c.search(limit=9999)
    assert len(page["items"]) == mc.PAGE_MAX and page["items"][0]["track"] == 1
    assert c.search(offset=95, limit=10)["items"][-1]["track"] == 100


def test_add_album_ids_in_track_order_and_albums_listing():
    c = cat()
    ids = c.album_ids("Abba", "Arrival")
    assert len(ids) == 100 and c.albums() == [{"artist": "Abba", "album": "Arrival", "tracks": 100}]
    assert [c.entry_for_queue(i)["rel"] for i in ids[:2]] == ["Abba/Arrival/01.mp3", "Abba/Arrival/02.mp3"]


def test_revoke_hides_entries_and_invalidates_queue_refs_and_unshared_load_ignored():
    c = cat(); mid = c.search("song 1")["items"][0]["id"]
    c.revoke("/music")
    assert c.search()["total"] == 0 and c.entry_for_queue(mid) is None and c.albums() == []
    assert c.load("/other", ITEMS) == 0
