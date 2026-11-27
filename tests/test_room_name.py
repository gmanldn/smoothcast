"""Hosted room labels are independent of join identity and playback."""
from portal_room import DEFAULT_ROOM_NAME, PortalRoom, clean_room_name


def test_room_name_is_printable_bounded_and_has_safe_default():
    assert clean_room_name(None) == DEFAULT_ROOM_NAME
    assert clean_room_name("   \n\t") == DEFAULT_ROOM_NAME
    assert clean_room_name("  Living\tRoom \x00 ") == "Living Room"
    assert clean_room_name("x" * 100) == "x" * 40
    assert clean_room_name("<Lounge & cinema>") == "<Lounge & cinema>"


def test_rename_changes_snapshot_revision_without_resetting_membership():
    room = PortalRoom()
    guest = room.join("Sam")
    room.vote(guest.id, "item", True)
    before = room.snapshot(guest.id)
    assert room.set_name("Cinema")
    after = room.snapshot(guest.id)
    assert after["name"] == "Cinema"
    assert after["seq"] == before["seq"] + 1
    assert after["me"]["id"] == guest.id
    assert after["participants"] == before["participants"]
    assert after["activity"] == before["activity"]
    assert room.votes["item"] == {guest.id}
    assert not room.set_name(" Cinema ")
    assert room.seq == after["seq"]


def test_access_reset_does_not_reset_host_room_name():
    room = PortalRoom()
    room.set_name("Kitchen")
    room.join("Guest")
    room.reset_history()
    assert room.snapshot()["name"] == "Kitchen"
    assert room.snapshot()["participants"] == []
