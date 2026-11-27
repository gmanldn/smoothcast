import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import guest_passes as gp


def test_only_hash_is_stored_and_url_uses_fragment(tmp_path):
    p = gp.Passes(tmp_path / "passes.json")
    tok, _ = p.create("Saturday party", "music", 3600, 5, 0)
    raw = (tmp_path / "passes.json").read_text()
    assert tok not in raw and len(tok) >= 22
    assert gp.Passes.join_url("house.lan", tok) == f"https://house.lan/join#pass={tok}"
    assert gp.Passes(tmp_path / "passes.json").redeem(tok, "d1", 10)[0]["scope"] == "music"


def test_expiry_revokes_immediately_and_reuse_after_expiry_rejected():
    p = gp.Passes(); tok, _ = p.create("x", "remote", 3600, 3, 0)
    assert p.redeem(tok, "d1", 100)[0] and p.validate(tok, "d1", 3599)
    assert p.validate(tok, "d1", 3600) is None
    assert p.redeem(tok, "d2", 3600) == (None, "This pass has expired. Ask the host for a new one.")


def test_max_devices_and_same_device_rejoin():
    p = gp.Passes(); tok, _ = p.create("x", "queue", 100, 2, 0)
    assert p.redeem(tok, "a", 1)[0] and p.redeem(tok, "b", 1)[0] and p.redeem(tok, "a", 2)[0]
    assert p.redeem(tok, "c", 3) == (None, "This pass is full. Ask the host for another.")
    assert p.validate(tok, "c", 3) is None and p.validate(tok, "a", 3)


def test_revoke_and_listing_and_invalid_settings():
    p = gp.Passes(); tok, _ = p.create("Party", "full", 100, 1, 0); p.redeem(tok, "a", 1)
    row = p.listing(10)[0]; assert row["expires_in"] == 90 and row["devices"] == 1
    assert p.revoke(row["id"]) and p.validate(tok, "a", 11) is None and not p.revoke(row["id"])
    assert p.create("x", "root", 100, 1, 0)[0] is None and p.create("x", "queue", 0, 1, 0)[0] is None
    assert p.create("x", "queue", gp.MAX_TTL_S + 1, 1, 0)[0] is None and p.create("x", "queue", 5, 0, 0)[0] is None


def test_expired_passes_are_pruned_so_the_cap_frees_up():
    p = gp.Passes()
    for i in range(gp.MAX_PASSES):
        assert p.create(str(i), "queue", 10, 1, 0)[0]
    assert p.create("x", "queue", 10, 1, 1)[1] == "Too many active passes."
    assert p.create("x", "queue", 10, 1, 11)[0]


ACTIONS = sorted(gp._QUEUE | gp._TRANSPORT | gp._HOST_ONLY)


@pytest.mark.parametrize("scope", gp.SCOPES)
def test_permission_table_covers_every_action(scope):
    for a in ACTIONS:
        assert isinstance(gp.allowed(scope, a, "audio"), bool)
    for host_only in ("settings", "revoke", "pairing", "pass_create", "library_manage"):
        assert not gp.allowed(scope, host_only)
    assert not gp.allowed(scope, "made_up_action")


def test_scope_rules_music_audio_only_votes_and_uploads():
    assert gp.allowed("queue", "vote") and gp.allowed("music", "queue_add", "audio") and not gp.allowed("music", "queue_add", "video")
    assert not gp.allowed("queue", "pause") and gp.allowed("remote", "pause") and not gp.allowed("remote", "upload")
    assert gp.allowed("full", "upload") and not gp.allowed("queue", "upload") and not gp.allowed("music", "seek")
