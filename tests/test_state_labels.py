"""All public playback-state surfaces share one source of truth."""
import state_labels


def test_all_receiver_states_have_readable_accessible_labels():
    for raw in ("PLAYING", "PAUSED", "BUFFERING", "IDLE", "OFFLINE", "UNKNOWN"):
        display = state_labels.present(raw)
        assert display.label and display.accessible and display.icon and display.short
        assert display.label != raw
        assert display.mpris in {"Playing", "Paused", "Stopped"}
    assert state_labels.present("broken future enum") == state_labels.STATES["UNKNOWN"]


def test_notifications_use_central_state_vocabulary():
    import notifications
    assert notifications.event_title(notifications.DEVICE_LOST) == state_labels.present("OFFLINE").label
    assert notifications.event_title(notifications.ERROR) == state_labels.present("ERROR").label


def test_mpris_vocabulary_comes_from_state_labels():
    assert {state_labels.present(r).mpris for r in ("PLAYING", "PAUSED", "IDLE")} == {"Playing", "Paused", "Stopped"}
