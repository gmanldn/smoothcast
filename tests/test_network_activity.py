from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import castctl
import dlna
import network_activity


def test_snapshot_reports_only_active_discovered_cast_and_dlna_receivers():
    cast = castctl.Device(name="Family Room", host="192.168.1.8")
    cast_idle = castctl.Device(name="Spare TV", host="192.168.1.9")
    renderer = dlna.Renderer(
        name="Bedroom", host="192.168.1.10", location="",
        transport_url="", transport_service="",
    )

    def cast_status(target, timeout=0):
        assert timeout == 3
        return {
            "player_state": "PLAYING" if target.endswith(".8") else "IDLE",
            "title": "  A Film\nTitle ", "current_time": "61.5", "duration": 3600,
        }

    entries = network_activity.snapshot(
        [cast, cast_idle], [renderer], cast_status=cast_status,
        dlna_status=lambda _renderer: {
            "player_state": "PAUSED", "media_title": "Documentary",
            "current_time": 15, "duration": 180,
        },
    )

    assert [(row["protocol"], row["receiver"], row["title"], row["state"])
            for row in entries] == [
        ("DLNA", "Bedroom", "Documentary", "PAUSED"),
        ("Google Cast", "Family Room", "A Film Title", "PLAYING"),
    ]
    assert entries[1]["position"] == 61.5 and entries[1]["duration"] == 3600


def test_snapshot_addresses_cast_by_host_deduplicates_and_skips_bad_receivers():
    devices = [
        castctl.Device(name="Shared name", host="192.168.1.8"),
        castctl.Device(name="Shared name", host="192.168.1.8"),
        castctl.Device(name="Broken", host="192.168.1.9"),
        castctl.Device(name="No address"),
    ]
    queried = []

    def status(target, timeout=0):
        queried.append(target)
        if target.endswith(".9"):
            raise OSError("unreachable")
        return {"player_state": "BUFFERING", "title": "A\x00 title"}

    entries = network_activity.snapshot(devices, [], cast_status=status)

    assert queried == ["192.168.1.8", "192.168.1.9"]
    assert len(entries) == 1
    assert entries[0]["title"] == "A title"


def test_snapshot_never_probes_non_private_cast_endpoints():
    queried = []
    entries = network_activity.snapshot(
        [castctl.Device(name="Public record", host="8.8.8.8")], [],
        cast_status=lambda target, timeout=0: queried.append(target),
    )

    assert queried == []
    assert entries == []


def test_portal_entries_omit_receiver_addresses_and_mark_local_cast():
    rows = [{
        "protocol": "Google Cast", "receiver": "Living Room", "host": "192.168.1.8",
        "title": "Movie", "state": "PLAYING", "position": 12, "duration": 120,
    }]

    result = network_activity.portal_entries(rows, "192.168.1.8")

    assert result == [{
        "protocol": "Google Cast", "receiver": "Living Room", "title": "Movie",
        "state": "PLAYING", "position": 12, "duration": 120, "is_local": True,
    }]
    assert "host" not in result[0]
