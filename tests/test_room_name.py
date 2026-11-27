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


def test_guest_roster_rename_preserves_selection_and_avoids_unchanged_rebuild():
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    source = Path(__file__).resolve().parents[1] / "src" / "cast_portal_host.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "PortalHostMixin")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_sync_portal_guest_roster")
    invalid = 2**32 - 1
    ns = {"Gtk": SimpleNamespace(StringList=SimpleNamespace(new=list),
                                 INVALID_LIST_POSITION=invalid)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), ns)
    class Dropdown:
        selected = 0
        def __init__(self):
            self.models = []
        def get_selected(self):
            return self.selected
        def set_selected(self, value):
            self.selected = value
        def set_model(self, value):
            self.models.append(value)
            self.selected = 0
        def set_sensitive(self, value):
            self.sensitive = value

    drop = Dropdown()
    owner = SimpleNamespace(portal_guest_dropdown=drop, portal_guest_ids=(),
                            portal_revoke_button=SimpleNamespace(set_sensitive=lambda _: None))
    sync = ns["_sync_portal_guest_roster"]
    guests = [{"id": "a", "name": "Sam"}, {"id": "b", "name": "Jo"}]
    sync(owner, guests)
    drop.selected = 1
    sync(owner, guests)
    assert len(drop.models) == 1
    guests[1]["name"] = "Joseph"
    sync(owner, guests)
    assert drop.models[-1] == ["Sam", "Joseph"]
    assert owner.portal_guest_ids[drop.selected] == "b"
    sync(owner, guests[::-1])
    assert drop.selected == 0 and owner.portal_guest_ids[0] == "b"
    sync(owner, guests[:1])
    assert drop.selected == invalid
    sync(owner, guests[:1])
    assert drop.selected == invalid
    sync(owner, [])
    assert not drop.sensitive


def test_named_room_is_visible_before_login_and_escaped():
    import portal

    room = PortalRoom()
    assert room.name == DEFAULT_ROOM_NAME
    assert b'<h2 id="joinTitle">Join the house</h2>' in portal._page()
    room.set_name("<Cinema & __PIN_REQUIRED__>")
    page = portal._page(room_name=room.name, pin_required=False).decode("utf-8")
    assert '<h2 id="joinTitle">Join &lt;Cinema &amp; __PIN_REQUIRED__&gt;</h2>' in page
    assert '<Cinema &' not in page
    assert 'Change my display name' in page
    room.set_name("Kitchen")
    assert b'<h2 id="joinTitle">Join Kitchen</h2>' in portal._page(room_name=room.name, pin_required=True)


def test_live_room_label_updates_join_title_without_rebuilding(monkeypatch):
    import shutil
    import subprocess

    import pytest
    import portal

    if shutil.which("node") is None:
        pytest.skip("requires Node.js")
    page = portal._page().decode("utf-8")
    helper = page[page.index("function renderRoomIdentity("):page.index("function renderRoom(room){")]
    harness = r"""
const assert=require("node:assert/strict");
let writes=0;
const node={value:"Join the house",get textContent(){return this.value},set textContent(v){writes++;this.value=v}};
const $=id=>id==="joinTitle"?node:null;
"""
    scenario = r"""
renderRoomIdentity({name:"Cinema"});
assert.equal(node.value,"Join Cinema");
renderRoomIdentity({name:"Cinema"});
assert.equal(writes,1);
renderRoomIdentity({name:"<Lounge>"});
assert.equal(node.value,"Join <Lounge>");
renderRoomIdentity({name:"Your room"});
assert.equal(node.value,"Join the house");
renderRoomIdentity(null);
assert.equal(writes,3);
"""
    result = subprocess.run(["node", "-"], input=harness + helper + scenario,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
