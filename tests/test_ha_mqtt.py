import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ha_mqtt as ha

LIVING = {"name": "Living Room", "state": "playing", "volume": 40, "title": "Song", "position": 12.0, "duration": 200.0, "source": "Living Room"}
BED = {"name": "Kids Bedroom", "private": True, "state": "playing", "title": "secret"}
ROOMS = [LIVING, BED, {"name": "Kitchen", "state": "idle", "volume": 0}]


def test_discovery_golden_payload_read_only_and_control():
    topic, p = ha.discovery("Hub", LIVING, ["Kitchen", "Living Room"], control=False, version="2.2.10")
    assert topic == "homeassistant/media_player/hub_living_room/config"
    assert json.loads(p) == {"name": "Living Room", "unique_id": "hub_living_room", "object_id": "smoothcast_living_room",
        "state_topic": "smoothcast/hub/living_room/state", "json_attributes_topic": "smoothcast/hub/living_room/attributes",
        "availability_topic": "smoothcast/hub/status", "payload_available": "online", "payload_not_available": "offline",
        "device": {"identifiers": ["smoothcast_hub"], "name": "SmoothCast Hub", "manufacturer": "SmoothCast", "sw_version": "2.2.10"}}
    c = json.loads(ha.discovery("Hub", LIVING, ["b", "a", "a"], control=True)[1])
    assert c["command_topic"] == "smoothcast/hub/living_room/set" and c["source_list"] == ["a", "b"] and "PLAY" in c["supported_features"] and "sw_version" not in c["device"]


def test_private_rooms_never_published_and_titles_hidden_by_privacy():
    assert ha.discovery("Hub", BED, [], True) is None and ha.state_messages("Hub", BED) == []
    shown = dict(ha.state_messages("Hub", LIVING)[1:2] and [(t, p) for t, p, _ in ha.state_messages("Hub", LIVING)])
    assert json.loads(shown["smoothcast/hub/living_room/attributes"])["media_title"] == "Song"
    hidden = {t: p for t, p, _ in ha.state_messages("Hub", LIVING, privacy_hides_titles=True)}
    assert "Song" not in json.dumps(hidden) and json.loads(hidden["smoothcast/hub/living_room/attributes"])["media_position"] == 12.0
    assert "Song" not in json.dumps(ha.state_messages("Hub", {**LIVING, "hide_title": True}))


def test_state_mapping_volume_and_idle_has_no_media_fields():
    m = {t.rsplit("/", 1)[1]: p for t, p, _ in ha.state_messages("Hub", ROOMS[2])}
    assert m["state"] == "idle" and json.loads(m["attributes"]) == {"volume_level": 0.0}
    assert {t.rsplit("/", 1)[1]: p for t, p, _ in ha.state_messages("Hub", {**LIVING, "state": "stopped"})}["state"] == "idle"
    assert json.loads({t.rsplit("/", 1)[1]: p for t, p, _ in ha.state_messages("Hub", {**LIVING, "volume": 500})}["attributes"])["volume_level"] == 1.0
    assert all(r for _, _, r in ha.state_messages("Hub", LIVING))


def test_read_only_ignores_all_commands_and_control_mode_validates():
    top = "smoothcast/hub/living_room/set"
    assert ha.handle_command(top, "pause", "Hub", ROOMS, control=False) == {"ok": False, "reason": "read_only"}
    assert ha.handle_command(top, "pause", "Hub", ROOMS, True) == {"ok": True, "room": "Living Room", "action": "pause", "arg": None}
    assert ha.handle_command(top, json.dumps({"command": "volume_set", "value": 0.35}), "Hub", ROOMS, True)["arg"] == 35
    assert ha.handle_command(top, json.dumps({"command": "volume_set", "value": 250}), "Hub", ROOMS, True)["arg"] == 100
    assert ha.handle_command(top, json.dumps({"command": "volume_set", "value": "x"}), "Hub", ROOMS, True)["reason"] == "bad_value"
    assert ha.handle_command(top, "reboot", "Hub", ROOMS, True)["reason"] == "unknown_command"
    assert ha.handle_command("smoothcast/hub/kids_bedroom/set", "pause", "Hub", ROOMS, True)["reason"] == "unknown_room"
    assert ha.handle_command("other/topic", "pause", "Hub", ROOMS, True)["reason"] == "unknown_room"
    mv = ha.handle_command(top, json.dumps({"command": "move_to", "value": "Kitchen"}), "Hub", ROOMS, True)
    assert mv["ok"] and mv["arg"] == "Kitchen" and ha.handle_command(top, json.dumps({"command": "move_to", "value": "Kids Bedroom"}), "Hub", ROOMS, True)["ok"] is False
    assert ha.handle_command(top, "{not json", "Hub", ROOMS, True)["reason"] == "unknown_command"


def test_last_will_and_availability_and_backoff():
    assert ha.last_will("Hub") == {"topic": "smoothcast/hub/status", "payload": "offline", "retain": True, "qos": 1}
    assert ha.availability("Hub", True) == ("smoothcast/hub/status", "online", True) and ha.availability("Hub", False)[1] == "offline"
    b = ha.Backoff(); assert [b.next() for _ in range(8)] == [1, 2, 4, 8, 16, 32, 60, 60]
    b.reset(); assert b.next() == 1
    assert ha.slug("  Étage 2 / Kids!! ") == "tage_2_kids" and ha.slug("") == "room"
