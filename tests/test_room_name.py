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


def test_desktop_rename_uses_existing_config_and_status(monkeypatch):
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    source = Path(__file__).resolve().parents[1] / "src" / "cast_portal_room.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "PortalRoomMixin")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_rename_portal_room")
    calls = []
    namespace = {"save_config": lambda cfg: calls.append(("save", dict(cfg)))}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    owner = SimpleNamespace(cfg={"room_name": "Your room"},
                            _publish_portal_status=lambda: calls.append("publish"),
                            toast=lambda message: calls.append(message))
    rename = namespace["_rename_portal_room"]
    rename(owner, "  Cinema  ")
    assert owner.cfg["room_name"] == "Cinema"
    assert calls == [("save", {"room_name": "Cinema"}), "publish", "Room name updated"]
    rename(owner, "Cinema")
    assert len(calls) == 3
