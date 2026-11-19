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
    import cast_widgets  # lazy: importing it loads GTK, which other tests forbid
    assert castctl.DEFAULT_DEVICE == ""
    assert cast_widgets.DEFAULTS["device"] == ""
    for raw in ({}, {"device": ""}, {"device": "   "}):
        assert config_control.sanitise_config(raw, cast_widgets.DEFAULTS)["device"] == ""
    kept = config_control.sanitise_config({"device": "Kitchen"}, cast_widgets.DEFAULTS)
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


def test_first_run_scan_selects_nothing_and_asks_the_user_to_choose():
    w, saves = window(name="", uuid="")
    w._scan_done([device("Kitchen", "uuid-a")])
    assert w.cfg["device"] == ""
    assert w.device_dropdown.selected == 2 ** 32 - 1  # Gtk.INVALID_LIST_POSITION
    assert [w.device_dropdown.model.get_string(i)
            for i in range(w.device_dropdown.model.get_n_items())] == ["Kitchen"]
    assert w.badges[-1] == "NOT FOUND"  # existing "choose another receiver" prompt
    assert saves == []


def test_first_run_with_no_receivers_reports_not_found():
    w, _ = window(name="", uuid="")
    w._scan_done([])
    assert w.badges[-1] == "NOT FOUND"
    assert w.device_dropdown.model.get_n_items() == 0


def test_select_index_adds_saved_device_and_never_invents_one():
    import cast_targets
    names = ["B", "C"]
    assert cast_targets.select_index(names, "A") == 0 and names == ["A", "B", "C"]
    assert cast_targets.select_index(names, "C") == 2
    assert cast_targets.select_index(["B"], "") == cast_targets.NO_SELECTION
