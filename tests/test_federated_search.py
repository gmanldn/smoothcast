"""#412: merge, fan-out deadline, SSE order and a two-node loopback integration."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import federated_search as fs
import library_folders as lf
import library_index_v2 as li
import library_replication as lr
import mesh_library
import replica_store as rs


def row(key, title, **kw):
    return {"content_key": key, "kind": "video", "title": title, "sort_title": title.lower(),
            "year": None, "show": None, "season": None, "episode": None, "artist": None,
            "album": None, "duration": None, **kw}


ORIGINS = {"a": {"name": "Study PC", "state": "fresh", "last_synced_at": 1},
           "b": {"name": "Dad's laptop", "state": "offline", "last_synced_at": 1, "last_seen_at": 99}}


def test_merge_dedupes_copies_and_ranks_online_first():
    local = [row("k1", "Paddington")]
    replicas = [row("k1", "Paddington", origin_id="a"), row("k2", "Paddington 2", origin_id="b"),
                row("k3", "Paddington Bear", origin_id="a")]
    merged = fs.merge(local, replicas, ORIGINS)
    assert [m["content_key"] for m in merged] == ["k1", "k3", "k2"]   # offline-only last
    first = merged[0]["copies"]
    assert [c["origin"] for c in first] == ["local", "a"] and all(c["online"] for c in first)
    offline = merged[-1]["copies"][0]
    assert offline["online"] is False and offline["last_seen"] == 99


def test_merge_is_deterministic():
    local = [row("k2", "B"), row("k1", "A")]
    assert fs.merge(local, [], ORIGINS) == fs.merge(list(local), [], ORIGINS)


def make(local=(), replicas=(), origins=None, fetch=None, deadline=0.3):
    return fs.FederatedSearch(lambda t, n: list(local), lambda t, n: list(replicas),
                              lambda: origins or {}, fetch or (lambda *a: (200, {"entries": []})),
                              deadline=deadline)


def test_no_fanout_when_replicas_are_fresh_or_offline():
    calls = []
    svc = make(local=[row("k1", "Alien")], origins=ORIGINS,
               fetch=lambda *a: calls.append(a) or (200, {"entries": []}))
    result = svc.search("alien")
    assert calls == [] and result["pending_origins"] == []
    assert result["groups"][0]["items"][0]["title"] == "Alien"


def test_fanout_adds_late_hits_and_slow_peers_never_block_cached_results():
    origins = {"slow": {"name": "Slow", "state": "stale", "last_synced_at": 1},
               "fast": {"name": "Fast", "state": "stale", "last_synced_at": 1}}
    release = threading.Event()

    def fetch(origin, path, params):
        if origin == "slow":
            release.wait(5)
            return 200, {"entries": []}
        return 200, {"entries": [{"content_key": "kf", "kind": "video", "title": "Fast Film",
                                  "sort_title": "fast film"}]}

    svc = make(local=[row("k1", "Local Film")], origins=origins, fetch=fetch, deadline=0.2)
    started = time.monotonic()
    result = svc.search("film")
    assert time.monotonic() - started < 2.0
    release.set()
    titles = {i["title"] for g in result["groups"] for i in g["items"]}
    assert titles == {"Local Film", "Fast Film"} and result["pending_origins"] == ["slow"]
    assert result["partial"] is True


def test_stream_emits_results_then_more_then_done():
    origins = {"p": {"name": "P", "state": "stale", "last_synced_at": None}}
    svc = make(local=[row("k1", "Local")], origins=origins,
               fetch=lambda *a: (200, {"entries": [{"content_key": "kp", "kind": "video",
                                                    "title": "Remote", "sort_title": "remote"}]}))
    events = list(svc.stream("x"))
    assert [e for e, _ in events] == ["results", "more", "done"]
    assert events[0][1]["pending_origins"] == ["p"]
    more_titles = {i["title"] for g in events[1][1]["groups"] for i in g["items"]}
    assert more_titles == {"Local", "Remote"}


def test_failing_peer_is_ignored():
    origins = {"p": {"name": "P", "state": "stale", "last_synced_at": 1}}

    def boom(*a):
        raise OSError("down")

    result = make(local=[row("k1", "Local")], origins=origins, fetch=boom).search("l")
    assert [i["title"] for g in result["groups"] for i in g["items"]] == ["Local"]


def test_pagination_cursor():
    svc = make(local=[row(f"k{i}", f"Title {i:02d}") for i in range(7)])
    seen, cursor = [], None
    while True:
        page = svc.search("title", limit=3, cursor=cursor)
        seen += [i["id"] for g in page["groups"] for i in g["items"]]
        cursor = page["next"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 7


# --- two real nodes over loopback -------------------------------------------
def node(tmp, name, titles):
    lib = tmp / name
    lib.mkdir()
    for i, title in enumerate(titles):
        (lib / f"{title}.mkv").write_bytes(bytes([i + 7]) * (50 + i + len(name)))
    idx = li.LibraryIndexer(tmp / f"{name}.sqlite3", probe=lambda p: {})
    idx.set_folders([lf.LibraryFolder("f_1", str(lib), name, "video", True)])
    idx.scan_all()
    return idx


def test_two_real_nodes_search_each_others_libraries(tmp_path):
    from test_room_conformance import RoomHarness
    remote = node(tmp_path, "study", ["Paddington 2 (2017)", "Alien (1979)"])
    local = node(tmp_path, "lounge", ["Amelie (2001)"])
    harness = RoomHarness(count=1)                      # plays the remote node's portal
    harness.server.library_replication = lr.Replication(remote, lr.RateLimiter(rate=1000, burst=1000))
    port = harness.server.server_address[1]
    try:
        fetcher = mesh_library.PeerFetcher()
        mesh = mesh_library.MeshLibrary(local, store=rs.ReplicaStore(tmp_path / "r.sqlite3"),
                                        fetcher=fetcher)
        peer = {"id": "study-peer", "name": "study", "compatible": True,
                "url": f"http://127.0.0.1:{port}/"}
        mesh.observe_peers([peer])                      # polls generation, registers origin
        before = mesh.search_service.search("paddington")
        assert any(i["title"] == "Paddington 2" for g in before["groups"] for i in g["items"])  # live fan-out
        assert mesh.manager.sync("study-peer")          # replica pulled over real HTTP
        mesh.manager.on_peer_seen("study-peer", "study", None)
        after = mesh.search_service.search("alien")
        items = [i for g in after["groups"] for i in g["items"]]
        assert items and items[0]["copies"][0]["origin_name"] == "study"
        assert "Amelie" in [i["title"] for g in mesh.search_service.search("amelie")["groups"]
                            for i in g["items"]]
        blob = json.dumps(after)
        assert str(tmp_path) not in blob                # no absolute paths ever
    finally:
        harness.close()


def test_origin_search_route_returns_only_shared_wire_entries(tmp_path):
    from test_room_conformance import RoomHarness
    idx = node(tmp_path, "study", ["Alien (1979)"])
    harness = RoomHarness(count=1)
    try:
        harness.server.library_replication = lr.Replication(idx)
        status, body, _ = harness.request("GET", "/mesh/library/search?q=alien")
        assert status == 200 and body["entries"][0]["title"] == "Alien"
        assert "folder_id" not in body["entries"][0] and str(tmp_path) not in json.dumps(body)
    finally:
        harness.close()


def test_sse_stream_route_orders_events(tmp_path):
    from test_room_conformance import RoomHarness
    svc = make(local=[row("k1", "Local")])
    harness = RoomHarness(count=1)
    try:
        harness.server.library_search_stream = svc.stream
        guest = harness.login("Alice")
        conn = HTTPConnection("127.0.0.1", harness.server.server_address[1], timeout=5)
        conn.request("GET", "/api/search/stream?q=local",
                     headers={"Host": harness.host, "Cookie": guest.cookie})
        reply = conn.getresponse()
        text = reply.read().decode()
        assert reply.status == 200 and reply.getheader("Content-Type") == "text/event-stream"
        assert text.index("event: results") < text.index("event: done")
        status, _, _ = harness.request("GET", "/api/search/stream?q=x")
        assert status in (401, 403)
    finally:
        harness.close()
