"""All public playback-state surfaces share one source of truth."""
from pathlib import Path

import state_labels


ROOT = Path(__file__).resolve().parents[1]


def test_all_receiver_states_have_readable_accessible_labels():
    for raw in ("PLAYING", "PAUSED", "BUFFERING", "IDLE", "OFFLINE", "UNKNOWN"):
        display = state_labels.present(raw)
        assert display.label and display.accessible and display.icon and display.short
        assert display.label != raw
        assert display.mpris in {"Playing", "Paused", "Stopped"}
    assert state_labels.present("broken future enum") == state_labels.STATES["UNKNOWN"]


def test_web_cli_desktop_notifications_and_mpris_use_central_states():
    paths = {key: (ROOT / "src" / key).read_text()
             for key in ("cast_discovery.py", "cast_portal.py", "cli_control.py",
                         "portal.py", "cast_ui.py", "notifications.py", "mpris.py")}
    assert 'state_labels.present(self.device_state).short' in paths["cast_discovery.py"]
    for key in ("state_label", "state_short", "state_description", "state_icon"):
        assert f'"{key}"' in paths["cast_portal.py"]
    assert 's.state_label||"State unavailable"' in paths["portal.py"]
    assert "state_labels.present(result['state']).label" in paths["cli_control.py"]
    assert 'state_labels.present(state).mpris' in paths["mpris.py"]
    assert 'notifications.event_title(event)' in paths["cast_ui.py"]
    assert 'state_labels.present("OFFLINE")' in paths["notifications.py"]


def test_json_remains_raw_for_automation_and_protocol_interoperability():
    cli = (ROOT / "src" / "cli_control.py").read_text()
    portal = (ROOT / "src" / "cast_portal.py").read_text()
    assert '"state": castctl.player_state(info)' in cli
    assert '"state": self.device_state' in portal
