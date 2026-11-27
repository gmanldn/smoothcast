import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import track_choices as tc

TRACKS = [{"kind": "audio", "index": 1, "language": "English", "codec": "aac"},
          {"kind": "audio", "index": 2, "language": "French", "codec": "ac3"},
          {"kind": "subtitle", "index": 3, "language": "English", "codec": "subrip"},
          {"kind": "subtitle", "index": 4, "language": "German", "codec": "hdmv_pgs_subtitle"}]


def test_ids_are_opaque_and_modes_honest():
    d = tc.describe("film-a", 1, TRACKS)
    assert len(d["audio"]) == 2 and len(d["subtitle"]) == 2
    assert "index" not in json.dumps(d) and "/" not in json.dumps(d)
    assert d["subtitle"][0]["mode"] == "live" and d["subtitle"][1]["mode"] == "restart"
    assert not tc.describe("film-a", 1, TRACKS, libass=False)["subtitle"][1]["available"]
    assert not tc.describe("film-a", 1, TRACKS, remote_url=True)["subtitle"][0]["available"]


def test_resolve_maps_to_stream_index_and_rejects_cross_film_ids():
    sid = tc.describe("film-a", 1, TRACKS)["audio"][1]["id"]
    assert tc.resolve("film-a", 1, TRACKS, "audio", sid, True) == (2, "")
    assert tc.resolve("film-b", 1, TRACKS, "audio", sid, True)[0] == -1
    assert tc.resolve("film-a", 2, TRACKS, "audio", sid, True)[0] == -1


def test_permission_off_and_unavailable_paths():
    sid = tc.describe("film-a", 1, TRACKS)["subtitle"][1]["id"]
    assert tc.resolve("film-a", 1, TRACKS, "subtitle", sid, False)[0] == -1
    assert tc.resolve("film-a", 1, TRACKS, "subtitle", "off", True) == (None, "")
    idx, why = tc.resolve("film-a", 1, TRACKS, "subtitle", sid, True, libass=False)
    assert idx == -1 and "burn-in" in why
    assert tc.resolve("film-a", 1, TRACKS, "video", "x", True)[0] == -1
