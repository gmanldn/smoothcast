"""P0 #14: executable in-window route-check coordination, without GTK/LAN."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import network_route_ui


def report(**changes):
    values = {
        "selected_source_ipv4": "192.168.1.25",
        "selected_interface": "eth0",
        "receiver_cast_port": "reachable",
        "local_hls_health": "healthy",
        "second_host_health_url": "http://192.168.1.25:8767/_smoothcast/health",
        "route_error": None,
    }
    values.update(changes)
    return values


def window(*, host="192.168.1.41", dlna=False):
    target = ["Living Room"]
    jobs = []
    session = object()
    w = SimpleNamespace(
        _device=lambda: target[0],
        _device_host=mock.Mock(return_value=host),
        _dlna_renderer=lambda device: object() if dlna else None,
        network_check_button=mock.Mock(),
        network_detail=mock.Mock(),
        toast=mock.Mock(),
        _closing=False,
        session=session,
    )
    def enqueue(work, done=None, failed=None):
        jobs.append((work, done, failed))
    return w, target, jobs, enqueue


def test_opt_in_check_uses_selected_host_and_never_probes_until_worker_runs():
    w, target, jobs, enqueue = window()
    with mock.patch.object(network_route_ui.network_routes, "report", return_value=report()) as probe:
        network_route_ui.start(w, enqueue)
        probe.assert_not_called()  # no synchronous GUI stall or unsolicited probe
        assert len(jobs) == 1
        w.network_check_button.set_sensitive.assert_called_with(False)
        assert "Checking" in w.network_detail.set_text.call_args.args[0]
        network_route_ui.start(w, enqueue)
        assert len(jobs) == 1  # single-flight
        work, done, _ = jobs.pop()
        text = work()
        probe.assert_called_once_with("192.168.1.41")
        done(text)
    assert w._network_check_busy is False
    w.network_check_button.set_sensitive.assert_called_with(True)
    assert "Cast TCP 8009: reachable" in w.network_detail.set_text.call_args.args[0]
    assert "192.168.1.25:8767" in w.network_detail.set_text.call_args.args[0]
    assert w.session is not None  # never steals a running cast or changes state
    w.toast.assert_not_called()


def test_selection_changed_while_worker_runs_never_shows_previous_tv_result():
    """INV-010: Stale receiver probe results must be rejected."""
    """INV-010: Network probe must discard results from an obsolete target."""
    w, selected, jobs, enqueue = window()
    network_route_ui.start(w, enqueue)
    selected[0] = "Bedroom"
    jobs[0][1]("Sensitive data from old target")
    w.network_check_button.set_sensitive.assert_called_with(True)
    text = w.network_detail.set_text.call_args.args[0]
    assert "Receiver changed" in text
    assert "Sensitive data" not in text


def test_reused_device_name_with_different_host_discards_stale_result():
    w, _, jobs, enqueue = window()
    network_route_ui.start(w, enqueue)
    w._device_host.return_value = "192.168.1.99"
    jobs[0][1]("Stale previous-IP result")
    assert "Receiver changed" in w.network_detail.set_text.call_args.args[0]
    assert "Stale previous-IP" not in w.network_detail.set_text.call_args.args[0]


def test_close_during_worker_ignores_pending_widget_callbacks():
    w, _, jobs, enqueue = window()
    network_route_ui.start(w, enqueue)
    w._closing = True
    w.network_check_button.set_sensitive.reset_mock()
    w.network_detail.set_text.reset_mock()
    jobs[0][1]("old result")
    w.network_check_button.set_sensitive.assert_not_called()
    w.network_detail.set_text.assert_not_called()
    assert w._network_check_busy is False


def test_failed_probe_releases_button_and_reports_error_without_claiming_a_cause():
    w, _, jobs, enqueue = window()
    network_route_ui.start(w, enqueue)
    jobs[0][2]("network route not found")
    assert w._network_check_busy is False
    w.network_check_button.set_sensitive.assert_called_with(True)
    assert "Connection check failed: network route not found" in (
        w.network_detail.set_text.call_args.args[0]
    )


def test_no_host_or_dlna_selection_refuses_check_without_any_worker():
    for kwargs, message in (
        ({"host": None}, "Select a discovered"),
        ({"dlna": True}, "not DLNA"),
    ):
        w, _, jobs, enqueue = window(**kwargs)
        network_route_ui.start(w, enqueue)
        assert not jobs
        assert message in w.toast.call_args.args[0]
        assert w.toast.call_args.kwargs == {"error": True}
        w.network_check_button.set_sensitive.assert_not_called()


def test_summary_distinguishes_local_health_from_second_host_reachability():
    text = network_route_ui.summary(report())
    assert "Local route: 192.168.1.25 (eth0)" in text
    assert "Local HLS: healthy" in text
    assert "While HLS is running" in text
    assert "remain unverified" in text

    no_route = network_route_ui.summary(report(
        selected_source_ipv4=None, selected_interface=None,
        second_host_health_url=None, route_error="No usable route",
        receiver_cast_port="not_checked", local_hls_health="not_responding",
    ))
    assert "Local route: unavailable" in no_route
    assert "No private source IPv4" in no_route
    assert "No usable route" in no_route
    assert "http://" not in no_route


def test_ui_wiring_is_explicit_and_stays_in_the_device_card():
    from gui_source import main_window_methods

    source = main_window_methods()["_build_device_card"]
    assert 'Gtk.Button(label="Check connection")' in source
    assert "network_route_ui.start(self, Async.run)" in source
    assert "self.network_detail.set_selectable(True)" in source
