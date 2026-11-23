"""GTK-free publication and copy isolation for LAN status snapshots."""
from __future__ import annotations

import portal_status


def test_published_status_is_versioned_aged_and_isolated_from_mutation():
    now = [10.0]
    snapshot = portal_status.PublishedStatus(clock=lambda: now[0])
    assert snapshot.read() is None
    source = {"queue": [{"title": "Film"}]}
    assert snapshot.publish(source) == 1
    source["queue"][0]["title"] = "Changed after publish"
    first = snapshot.read()
    assert first is not None
    assert first["queue"][0]["title"] == "Film"
    assert first["snapshot_version"] == 1 and first["snapshot_age_ms"] == 0
    first["queue"][0]["title"] = "Changed by HTTP enrichment"
    now[0] = 10.025
    second = snapshot.read()
    assert second is not None
    assert second["queue"][0]["title"] == "Film"
    assert second["snapshot_version"] == 1 and second["snapshot_age_ms"] == 25
    assert snapshot.publish({"queue": []}) == 2

