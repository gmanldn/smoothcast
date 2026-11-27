import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import private_rooms as pr


def rooms():
    return [{"id": "lounge", "name": "Lounge", "receivers": ["tv"]},
            {"id": "bed", "name": "Sam's room", "receivers": ["spk", "lamp"], "private_to": ["sam"]}]


def test_non_owners_cannot_see_or_control_but_owner_and_host_can():
    r = rooms()[1]
    assert pr.can_see(r, "sam", "resident", 0) and pr.can_see(r, None, "host", 0)
    assert not pr.can_see(r, "mum", "resident", 0) and not pr.can_see(r, None, "guest", 0)
    assert not pr.can_control(r, "mum", "resident", 0) and pr.can_control(r, "sam", "resident", 0)


def test_filters_pickers_status_and_api_rows_not_just_rooms():
    rs = rooms()
    assert [x["id"] for x in pr.visible_rooms(rs, None, "guest", 0)] == ["lounge"]
    rows = [{"id": "tv"}, {"id": "spk"}, {"id": "lamp"}]
    assert [x["id"] for x in pr.filter_receivers(rows, rs, "mum", "resident", 0)] == ["tv"]
    assert len(pr.filter_receivers(rows, rs, "sam", "resident", 0)) == 3 and len(pr.filter_receivers(rows, rs, None, "host", 0)) == 3
    assert pr.hidden_receivers(rs, None, "guest", 0) == {"spk", "lamp"}


def test_temporary_share_expires_and_only_owner_can_share():
    r = rooms()[1]
    assert not pr.share(r, "mum", 3600, 0)[0] and pr.share(r, "sam", 7200, 100)[0]
    assert pr.can_see(r, None, "guest", 7299) and not pr.can_see(r, None, "guest", 7300)
    assert pr.unshare(r, "sam") and not pr.can_see(r, None, "guest", 200) and not pr.unshare(r, "mum")
    pr.share(r, "sam", 10**9, 0); assert r["share_until"] == pr.SHARE_MAX_S


def test_host_stop_is_always_allowed_and_logged():
    log = []
    assert pr.host_stop(rooms()[1], "host", 5, log) and log == [{"at": 5, "actor": "host", "room": "bed", "action": "host_stop_private"}]
    assert pr.host_stop(rooms()[0], "host", 6, log) and len(log) == 1


def test_only_host_or_owner_can_change_privacy_and_owner_deletion_makes_public():
    r = rooms()[1]
    assert not pr.set_private(r, [], "mum", "resident")[0] and pr.set_private(r, ["sam", "alex"], "sam", "resident")[0]
    assert r["private_to"] == ["alex", "sam"]
    rs = [r]
    assert pr.owner_deleted(rs, "sam") == [] and r["private_to"] == ["alex"]
    assert pr.owner_deleted(rs, "alex") == ["Sam's room is no longer private because its owner was removed."]
    assert pr.can_see(r, None, "guest", 0) and pr.lock_tooltip(r, "sam") is None
    assert pr.lock_tooltip({"private_to": ["sam"]}, "sam") == "Only you can see this room"


def test_direct_api_is_404_for_non_owners_and_unknown_rooms():
    bed = rooms()[1]
    assert pr.api_status(bed, "mum", "resident", 0) == 404 and pr.api_status(bed, None, "guest", 0) == 404
    assert pr.api_status(bed, "sam", "resident", 0) == 200 and pr.api_status(bed, None, "host", 0) == 200
    assert pr.api_status(None, None, "host", 0) == 404 and pr.api_status(rooms()[0], None, "guest", 0) == 200
