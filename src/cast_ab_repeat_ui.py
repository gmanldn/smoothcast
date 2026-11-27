"""A–B repeat marking actions for the session transport.

Extracted from ``cast_session.py`` unchanged so that module stays within its
INV-011 read budget; the methods run on the same ``SessionMixin`` instance.
"""
from __future__ import annotations

from cast_widgets import fmt_time


class AbRepeatUiMixin:
    def _ab_current_position(self) -> tuple[float | None, float]:
        preview = self.session is None and self._preview_path is not None and not self.external
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        return (self._preview_position if preview else self.tracker.value(), duration)
    def _mark_ab_start(self) -> None:
        position, duration = self._ab_current_position()
        if position is None or not self.ab_repeat.mark_start(position, duration):
            self.toast("Move to a valid point before the end, then mark A", error=True)
            return
        self.mark_a_button.set_label(f"A · {fmt_time(position)}")
        self.mark_b_button.set_label("Mark B")
        self.toast(f"A–B loop starts at {fmt_time(position)}")
    def _mark_ab_end(self) -> None:
        position, duration = self._ab_current_position()
        if position is None or not self.ab_repeat.mark_end(position, duration):
            self.toast("Mark B after A and before the end of the file", error=True)
            return
        self.mark_b_button.set_label(f"B · {fmt_time(position)}")
        start = self.ab_repeat.start
        self.toast(f"A–B repeat set to {fmt_time(start if start is not None else 0.0)}–{fmt_time(position)}")
    def _clear_ab_repeat(self) -> None:
        self._reset_ab_repeat()
        self.toast("A–B repeat cleared")
    def _reset_ab_repeat(self) -> None:
        repeat = getattr(self, "ab_repeat", None)
        if repeat is not None:
            repeat.clear()
        if getattr(self, "mark_a_button", None) is not None:
            self.mark_a_button.set_label("Mark A")
            self.mark_b_button.set_label("Mark B")
