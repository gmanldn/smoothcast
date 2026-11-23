"""#413: libraries on the network - tree browsing of local and replicated shared folders."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_browse as lb
import library_folders as lf
import library_index_v2 as li
import mesh_library
import replica_store as rs
from test_room_conformance import RoomHarness


@pytest.fixture
def world(tmp_path):
    lib = tmp_path / "Films"
    for rel in ("Alien (1979).mkv", "Kids/Paddington (2014).mkv", "Kids/Paddington 2 (2017).mkv",
                "Kids/Cartoons/Bluey S01E01.mkv", "Kids/Cartoons/Bluey S01E02.mkv"):
        target = lib / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(rel.encode() * 20)
    private = tmp_path / "Private"
    private.mkdir()
    (private / "secret.mkv").write_bytes(b"s" * 100)
    idx = li.LibraryIndexer(tmp_path / "i.sqlite3", probe=lambda p: {})
    idx.set_folders([lf.LibraryFolder("f_1", str(lib), "Films", "video", True),
                     lf.LibraryFolder("f_2", str(private), "Private", "video", False)])
    idx.scan_all()
    store = rs.ReplicaStore(tmp_path / "r.sqlite3")
    store.touch_origin("study", "Study PC", 100.0)
    store.touch_origin("dad", "Dad's laptop", 100.0)
    store.conn.execute("UPDATE origins SET state='fresh' WHERE origin_id='study'")
    store.conn.execute("UPDATE origins SET state='offline' WHERE origin_id='dad'")
    for oid, folder, rel in (("study", "Music", "ABBA/Arrival/Dancing Queen.mp3"),
                             ("study", "Music", "ABBA/Arrival/Fernando.mp3"),
                             ("study", "Music", "Single.mp3"),
                             ("dad", "Holiday", "2019/beach.mp4")):
        store.conn.execute(
            "INSERT INTO rentries(origin_id,content_key,kind,title,sort_title,folder_label,rel_path)"
            " VALUES(?,?,?,?,?,?,?)",
            (oid, f"qh:{abs(hash((oid, rel))) % 10**32:032x}", "music", rel.split("/")[-1][:-4],
             rel.casefold(), folder, rel))
    store.conn.commit()
    return mesh_library.MeshLibrary(idx, store=store)


def names(result):
    return [d["name"] for d in result["dirs"]], [i["title"] for i in result["items"]]


def test_libraries_lists_local_shared_folders_and_peers_with_online_state(world):
    data = world.libraries()
    local, dad, study = data["origins"]      # peers are ordered by name
    assert local["id"] == "local" and [f["label"] for f in local["folders"]] == ["Films"]   # Private hidden
    assert local["folders"][0]["count"] == 5
    assert study["online"] is True and study["folders"] == [{"label": "Music", "count": 3}]
    assert dad["online"] is False and dad["folders"][0]["label"] == "Holiday"


def test_local_tree_walks_one_level_at_a_time(world):
    root = world.browse("local", "Films", "")
    dirs, items = names(root)
    assert dirs == ["Kids"] and items == ["Alien"] and root["dirs"][0]["count"] == 4
    kids = world.browse("local", "Films", "Kids")
    dirs, items = names(kids)
    assert dirs == ["Cartoons"] and sorted(items) == ["Paddington", "Paddington 2"] and kids["path"] == "Kids"
    cartoons = world.browse("local", "Films", "Kids/Cartoons/")
    assert names(cartoons) == ([], ["Bluey S01E01", "Bluey S01E02"])
    assert cartoons["items"][0]["copies"] == [{"origin": "local", "origin_name": "This computer",
                                               "online": True}]


def test_replica_tree_and_availability(world):
    top = world.browse("study", "Music", "")
    assert names(top) == (["ABBA"], ["Single"])
    album = world.browse("study", "Music", "ABBA/Arrival")
    assert sorted(names(album)[1]) == ["Dancing Queen", "Fernando"]
    assert album["items"][0]["copies"][0]["online"] is True
    offline = world.browse("dad", "Holiday", "2019")
    assert offline["items"][0]["copies"][0]["online"] is False


def test_paging_covers_everything_once(world):
    seen, cursor = [], None
    while True:
        page = world.browse("local", "Films", "Kids/Cartoons", cursor, limit=1)
        seen += names(page)[1]
        cursor = page["next"]
        if not cursor:
            break
    assert seen == ["Bluey S01E01", "Bluey S01E02"]


def test_unknown_unshared_and_hostile_requests(world):
    assert world.browse("local", "Private", "") is None            # not shared
    assert world.browse("local", "Nope", "") is None
    assert world.browse("ghost", "Music", "") is None
    for bad in ("../etc", "Kids/../..", "/abs", "a/./b", "x" * 600, "bad\x00"):
        with pytest.raises(lb.BrowseError):
            world.browse("local", "Films", bad)
    assert world.browse("local", "Films", "Kids\\Cartoons")["path"] == "Kids/Cartoons"   # backslashes normalised
    assert world.browse("local", "Films", "no/such/dir")["items"] == []                 # empty, not an error
    assert world.browse("local", "Films", "Ki%")["items"] == [] \
        and world.browse("local", "Films", "K_ds")["items"] == []                       # LIKE wildcards are literal


def test_no_absolute_paths_in_any_response(world, tmp_path):
    blob = json.dumps(world.libraries()) + json.dumps(world.browse("local", "Films", "Kids"))
    assert str(tmp_path) not in blob and "folder_id" not in blob


def test_http_routes_require_a_session_and_map_errors(world):
    harness = RoomHarness(count=1)
    try:
        harness.server.library_browser = world
        status, _, _ = harness.request("GET", "/api/libraries")
        assert status in (401, 403)
        guest = harness.login("Alice")
        status, data, _ = harness.request("GET", "/api/libraries", cookie=guest.cookie)
        assert status == 200 and data["origins"][0]["id"] == "local"
        status, data, _ = harness.request(
            "GET", "/api/libraries/local/Films?path=Kids", cookie=guest.cookie)
        assert status == 200 and data["dirs"][0]["name"] == "Cartoons"
        status, _, _ = harness.request("GET", "/api/libraries/local/Private", cookie=guest.cookie)
        assert status == 404
        status, _, _ = harness.request(
            "GET", "/api/libraries/local/Films?path=..%2Fetc", cookie=guest.cookie)
        assert status == 400
        status, data, _ = harness.request("GET", "/api/libraries/study/Music?path=ABBA", cookie=guest.cookie)
        assert status == 200 and data["dirs"][0]["name"] == "Arrival"
    finally:
        harness.close()


def test_find_page_has_accessible_chips_and_the_libraries_browser():
    import portal
    html = portal._page().decode()
    assert 'id="findChips" role="group" aria-label="Filter results"' in html
    for label in ("Films", "Shows", "Music", "Videos", "Available now"):
        assert f">{label}</button>" in html
    assert html.count('aria-pressed="false"') >= 5
    assert '<details id="libraries"><summary>Libraries on the network</summary>' in html
    find_js = html[html.index('const input=$("findInput")'):]
    assert "innerHTML" not in find_js and "/api/libraries/" in find_js
