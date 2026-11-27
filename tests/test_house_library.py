import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from house_library import Catalogue


def three():
    c = Catalogue("A")
    c.snapshot("A", "Living-room PC", [{"key": "k1", "title": "Heat", "height": 1080}, {"key": "k2", "title": "Zulu"}], 1)
    c.snapshot("B", "Dad's laptop", [{"key": "k1", "title": "Heat", "height": 2160}, {"key": "k3", "title": "Alien"}], 1)
    c.snapshot("C", "Den", [{"key": "k1", "title": "Heat", "height": 720}], 1)
    return c


def test_dedupes_by_key_and_lists_every_copy():
    rows = three().entries()
    heat = next(r for r in rows if r["title"] == "Heat")
    assert len(rows) == 3 and {x["node"] for x in heat["copies"]} == {"A", "B", "C"}


def test_best_copy_prefers_local_then_resolution_fit_and_skips_offline():
    c = three()
    assert c.best_copy("k1")["node"] == "A"                       # local wins
    c.set_online("A", False)
    assert c.best_copy("k1", 0)["node"] == "B"                    # highest res when unconstrained
    assert c.best_copy("k1", 1080)["node"] == "C"                 # 4K doesn't fit the receiver: best that does
    for n in "ABC":
        c.set_online(n, False)
    assert c.best_copy("k1") is None


def test_offline_only_items_sort_last_with_reason():
    c = three(); c.set_online("B", False)
    rows = c.entries()
    assert rows[-1]["title"] == "Alien" and not rows[-1]["playable"]
    assert rows[-1]["availability"] == "Only on Dad's laptop (offline)"
    heat = next(r for r in rows if r["title"] == "Heat")
    assert heat["availability"] == "On Living-room PC, Den · Also on Dad's laptop (offline)"


def test_delta_monotonic_replay_ignored_and_remove():
    c = three()
    assert c.delta("B", 2, add=[{"key": "k9", "title": "New"}], remove=["k3"])
    assert not c.delta("B", 2, add=[{"key": "kx"}]) and not c.delta("Z", 5)
    titles = [r["title"] for r in c.entries()]
    assert "New" in titles and "Alien" not in titles and "kx" not in titles


def test_shared_embedded_ids_merge_different_keys_and_metadata_prefers_tags():
    c = Catalogue("A")
    c.snapshot("A", "PC", [{"key": "q1", "title": "heat.1995.mkv", "tags": {}, "mtime": 9}], 1)
    c.snapshot("B", "Lap", [{"key": "q2", "title": "Heat", "tags": {"imdb": "tt0113277"}, "mtime": 1}], 1)
    c.snapshot("C", "Den", [{"key": "q3", "title": "Heat (4K)", "tags": {"imdb": "tt0113277"}, "mtime": 2}], 1)
    rows = c.entries()
    assert [(r["title"], len(r["copies"])) for r in rows] == [("Heat (4K)", 2), ("heat.1995.mkv", 1)]
