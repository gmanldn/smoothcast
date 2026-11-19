"""GTK-free receiver-control overload and callback ownership regressions."""
from __future__ import annotations

import textwrap
from types import SimpleNamespace
from unittest import mock

from gui_source import main_window_methods


def window():
    method = main_window_methods()["_on_cc_toggled"]
    code = "class Extracted:\n" + textwrap.indent(textwrap.dedent(method), "    ")
    jobs = []
    namespace = {
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None, **kwargs:
                jobs.append((work, done, failed, kwargs))
        ),
        "save_config": lambda _cfg: None,
    }
    exec(compile(code, "<captions>", "exec"), namespace)

    class Window(namespace["Extracted"]):
        def __init__(self):
            self.busy = False
            self._syncing = False
            self._closing = False
            self.cfg = {"subs": "auto"}
            self.device = "TV A"
            self._restore_cc_toggle = mock.Mock()
            self.toast = mock.Mock()

        def _device(self):
            return self.device

        def _dlna_renderer(self):
            return None

    return Window(), jobs


def test_caption_command_has_bounded_transport_domain_and_failure_feedback():
    w, jobs = window()
    w._on_cc_toggled(SimpleNamespace(get_active=lambda: True))
    assert len(jobs) == 1
    work, done, failed, options = jobs.pop()
    assert options["domain"] == "transport"
    assert options["valid"]() is True
    failed("Too many queued transport commands")
    w._restore_cc_toggle.assert_called_once_with(False)
    w.toast.assert_called_once_with(
        "Captions failed: Too many queued transport commands", error=True,
    )


def test_caption_reply_from_old_receiver_is_dropped_on_delivery():
    w, jobs = window()
    w._on_cc_toggled(SimpleNamespace(get_active=lambda: True))
    w.device = "TV B"
    assert jobs[0][3]["valid"]() is False
    w.device = "TV A"
    w._closing = True
    assert jobs[0][3]["valid"]() is False


def test_volume_mute_and_preview_work_use_separate_domains():
    methods = main_window_methods()
    assert methods["_commit_volume"].count('domain="transport"') == 2
    assert methods["_on_mute"].count('domain="transport"') == 2
    assert 'domain="media"' in methods["_start_preview"]
