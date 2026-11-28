"""#691: retry decisions are pure and GTK-free."""
from types import SimpleNamespace as NS

import retry_component as rc


def test_labels():
    assert rc.action_label("alternate_target", "Den TV") == "Continue on Den TV"
    assert rc.action_label("alternate_encoding", "x") == "Convert and retry"
    assert rc.action_label("unknown", "x") == "Try again"


def test_identity_saved_dlna_unique_and_ambiguous():
    base = dict(cast_targets=["Saved"], devices=[NS(name="TV", uuid="u1", host="h")], saved_uuid="")
    assert rc.receiver_identity("", host_for_saved=None, **base) is None
    assert rc.receiver_identity("Saved", host_for_saved="10.0.0.2", **base) == ("Saved", "", "10.0.0.2")
    assert rc.receiver_identity("DLNA · X", host_for_saved=None, **base) is None
    assert rc.receiver_identity("TV", host_for_saved=None, **base) == ("TV", "u1", "h")
    twice = dict(base, devices=base["devices"] * 2)
    assert rc.receiver_identity("TV", host_for_saved=None, **twice) is None
    assert rc.receiver_identity("TV", host_for_saved=None, **dict(base, saved_uuid="other")) is None


def test_guards():
    ok = dict(closing=False, token=1, current_token=1, busy=False, external=False, session_active=False)
    assert rc.playback_changed(**ok) is False
    for key, value in (("closing", True), ("token", 2), ("busy", True), ("external", True),
                       ("session_active", True)):
        assert rc.playback_changed(**dict(ok, **{key: value})) is True
    same = dict(selection="TV", current_selection="TV", identity=("TV", "u", "h"),
                current_identity=("TV", "u", "h"), kind="retry")
    assert rc.receiver_changed(**same) is False
    assert rc.receiver_changed(**dict(same, current_selection="Other")) is True
    assert rc.receiver_changed(**dict(same, current_identity=("TV", "u2", "h"))) is True
    assert rc.receiver_changed(**dict(same, identity=None, current_identity=None)) is True
    assert rc.receiver_changed(**dict(same, identity=None, current_identity=None, kind="alternate_target")) is False
