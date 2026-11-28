import pytest

pytest.importorskip("gi")
import update_button as ub


def test_check_cadence_and_labels():
    assert ub.should_check("idle", 0, 1000) and not ub.should_check("idle", 900, 1000)
    assert not ub.should_check("updating", 0, 10_000) and not ub.should_check("restarting", 0, 10_000)
    assert ub.label_for("available") == "Update and restart" and ub.label_for("current") is None
    assert ub.label_for("restarting") == "Restarting…"
    assert ub.label_for("blocked") == "Update unavailable" and ub.should_check("blocked", 0, 1000)
