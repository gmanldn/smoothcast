import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import remote_affordances as ra

CAST = {"can_seek": True, "can_pause": True, "can_stop": True, "can_set_volume": True,
        "can_change_tracks": True, "can_switch_output": True}
DLNA = {"can_seek": False, "can_pause": True, "can_stop": True, "can_set_volume": None,
        "can_change_tracks": False, "can_switch_output": True}
CTRL = {"control", "seek", "volume", "change_tracks"}


def test_devices_with_different_capabilities_show_different_states():
    c, d = ra.view(CAST, CTRL), ra.view(DLNA, CTRL)
    assert c["seek"]["state"] == ra.ENABLED and d["seek"]["state"] == ra.UNSUPPORTED
    assert d["volume"]["state"] == ra.UNKNOWN and d["pause"]["state"] == ra.ENABLED
    assert c["output"]["state"] == ra.UNAUTHORISED


def test_offline_or_unprobed_is_never_enabled_and_busy_blocks():
    assert all(v["state"] == ra.UNKNOWN for v in ra.view(None, {"host"}).values())
    assert ra.view(CAST, CTRL, online=False)["seek"]["state"] == ra.UNKNOWN
    assert ra.view(CAST, CTRL, busy=True)["seek"]["state"] == ra.BUSY


def test_crafted_requests_use_same_gate():
    assert ra.check("seek", DLNA, CTRL)[0] is False
    assert ra.check("seek", CAST, {"control"})[0] is False
    assert ra.check("seek", CAST, CTRL) == (True, "")
    assert ra.check("warp", CAST, CTRL)[0] is False


def test_transcode_hint_only_when_real_and_changed_diff():
    v = ra.view(DLNA, CTRL, transcode_changes={"seek"})
    assert "Transcoding" in v["seek"]["reason"] and "Transcoding" not in v["tracks"]["reason"]
    assert ra.changed(ra.view(CAST, CTRL), ra.view(DLNA, CTRL)) == ["seek", "volume", "tracks"]
