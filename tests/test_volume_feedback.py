"""Acknowledged volume feedback without importing GTK or contacting receivers."""
from __future__ import annotations

import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods


def window(*, renderer=None):
    method = main_window_methods()["_commit_volume"]
    code = "class Extracted:\n" + textwrap.indent(textwrap.dedent(method), "    ")
    jobs = []
    namespace = {
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **kwargs:
                jobs.append((work, done, failed, kwargs)),
        ),
        "castctl": SimpleNamespace(volume=mock.Mock(return_value=(True, ""))),
        "dlna": SimpleNamespace(volume=mock.Mock(return_value=None)),
    }
    exec(compile(code, "<volume-feedback>", "exec"), namespace)

    class Window(namespace["Extracted"]):
        def __init__(self):
            self._volume_job = object()
            self._volume_target = "TV A"
            self.device = "TV A"
            self.device_state = "PLAYING"
            self._closing = False
            self.volume_scale = SimpleNamespace(get_value=lambda: 74)
            self._renderer = renderer
            self.toast = mock.Mock()
            self._reject_volume = mock.Mock()

        def _device(self):
            return self.device

        def _dlna_renderer(self, _device):
            return self._renderer

        def _volume_control_available(self):
            return True

    return Window(), jobs


def test_cast_volume_shows_feedback_only_after_acknowledgement():
    host, jobs = window()
    assert host._commit_volume() is False
    assert host.toast.call_count == 0
    work, done, _failed, options = jobs[0]
    assert options["domain"] == "transport"
    assert options["valid"]()
    assert work() == (True, "")
    done((True, ""))
    host.toast.assert_called_once_with("Volume 74%")
    host._reject_volume.assert_not_called()


def test_rejected_volume_never_shows_success_feedback():
    host, jobs = window()
    host._commit_volume()
    _work, done, _failed, _options = jobs[0]
    done((False, "receiver refused"))
    host._reject_volume.assert_called_once_with("receiver refused")
    host.toast.assert_not_called()


def test_stale_receiver_or_superseded_value_drops_volume_feedback():
    host, jobs = window()
    host._commit_volume()
    _work, done, _failed, options = jobs[0]
    host.device = "TV B"
    assert options["valid"]() is False
    done((True, ""))
    host.toast.assert_not_called()

    host.device = "TV A"
    host.volume_scale.get_value = lambda: 55
    done((True, ""))
    host.toast.assert_not_called()


def test_dlna_volume_feedback_uses_transport_acknowledgement():
    host, jobs = window(renderer=object())
    host._commit_volume()
    work, done, _failed, options = jobs[0]
    assert options["domain"] == "transport"
    assert options["valid"]()
    assert work() is None
    done(None)
    host.toast.assert_called_once_with("Volume 74%")
