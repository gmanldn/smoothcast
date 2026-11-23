"""#171: the back-to-start control returns a cast or the preview to zero."""
from __future__ import annotations

import textwrap

from gui_source import main_window_methods


def test_back_to_start_seeks_to_zero():
    namespace = {}
    code = "class M:\n" + textwrap.indent(
        textwrap.dedent(main_window_methods()["_back_to_start"]), "    ")
    exec(compile(code, "<back-to-start>", "exec"), namespace)

    class Fake(namespace["M"]):
        def __init__(self):
            self.calls = []

        def seek_to(self, target):
            self.calls.append(target)

    fake = Fake()
    fake._back_to_start()
    assert fake.calls == [0.0]


def test_back_to_start_is_wired_like_the_other_seek_controls():
    methods = main_window_methods()
    assert 'add("Home", self._back_to_start)' in methods["_install_shortcuts"]
    build = methods["_build_now_playing"]
    assert "Back to start (Home)" in build
    assert "self._back_to_start" in build
    # Enabled/disabled through the same can_seek group as the other steps.
    controls = methods["_refresh_controls"]
    assert "self.start_button, self.back10_button, self.back30_button" in controls
