"""No hard-coded receiver (issue #239): nothing is commanded until one is chosen."""
from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import castctl
import config_control
import streamer
from test_discovery_identity import device, window


def test_default_device_is_empty_and_survives_config_loading():
    assert castctl.DEFAULT_DEVICE == ""
    # The GUI defaults take the device from the constant (parsed, not imported: no GTK).
    assert '"device": castctl.DEFAULT_DEVICE' in (ROOT / "src" / "cast_widgets.py").read_text()
    defaults = {"device": castctl.DEFAULT_DEVICE}
    for raw in ({}, {"device": ""}, {"device": "   "}):
        assert config_control.sanitise_config(raw, defaults)["device"] == ""
    kept = config_control.sanitise_config({"device": "Kitchen"}, defaults)
    assert kept["device"] == "Kitchen"


@pytest.mark.parametrize("blank", ["", "  "])
def test_castctl_never_spawns_catt_for_a_blank_device(blank):
    with mock.patch.object(castctl, "_run") as run:
        assert castctl.command(blank, "play") == (False, castctl.NO_DEVICE_MESSAGE)
        assert castctl.pause(blank) == (False, castctl.NO_DEVICE_MESSAGE)
        assert castctl.info(blank) is None
    run.assert_not_called()


@pytest.mark.parametrize("starter", ["start_transcode", "start_direct"])
def test_streamer_rejects_a_blank_device_before_any_process(starter):
    session = streamer.Session()
    kwargs = dict(device=" ", subs_file=None, title="t")
    if starter == "start_transcode":
        kwargs.update(quality="auto", audio_profile="original", burn_subs=False)
    else:
        kwargs.update(subs_disabled=False)
    with mock.patch("subprocess.Popen") as popen, pytest.raises(streamer.StreamError):
        if starter == "start_direct":
            session.start_direct(mock.Mock(), **kwargs)
        else:
            session.start_transcode(mock.Mock(), 0.0, **kwargs)
    popen.assert_not_called()


def names_in(dropdown):
    model = dropdown.model
    return [model.get_string(i) for i in range(model.get_n_items())]


def test_first_run_scan_shows_a_placeholder_and_saves_nothing_until_the_user_picks():
    import cast_targets
    w, saves = window(name="", uuid="")
    w._scan_done([device("Kitchen", "uuid-a")])
    assert w.cfg["device"] == ""
    # GTK's DropDown cannot show "nothing selected" over a non-empty list, so the
    # placeholder row is what is selected (verified with real widgets by scripts/gui_checks.py).
    assert names_in(w.device_dropdown) == [cast_targets.CHOOSE_RECEIVER, "Kitchen"]
    assert w.device_dropdown.selected == 0
    assert w.badges[-1] == "NOT FOUND"  # existing "choose another receiver" prompt
    assert saves == []


def test_selecting_the_placeholder_never_becomes_a_receiver_but_a_real_pick_is_saved():
    w, saves = window(name="", uuid="")
    w._scan_done([device("Kitchen", "uuid-a")])
    w._on_device_selected(w.device_dropdown, None)             # the placeholder row
    assert w.cfg["device"] == "" and saves == [] and w.polls == 0
    w.device_dropdown.selected = 1                              # the user picks Kitchen
    w._on_device_selected(w.device_dropdown, None)
    assert w.cfg["device"] == "Kitchen"


def test_first_run_with_no_receivers_reports_not_found():
    import cast_targets
    w, _ = window(name="", uuid="")
    w._scan_done([])
    assert w.badges[-1] == "NOT FOUND"
    assert names_in(w.device_dropdown) == [cast_targets.CHOOSE_RECEIVER]


def test_select_index_adds_saved_device_and_uses_a_placeholder_when_unset():
    import cast_targets
    names = ["B", "C"]
    assert cast_targets.select_index(names, "A") == 0 and names == ["A", "B", "C"]
    assert cast_targets.select_index(names, "C") == 2
    unset = ["B"]
    assert cast_targets.select_index(unset, "") == 0 and unset == [cast_targets.CHOOSE_RECEIVER, "B"]
