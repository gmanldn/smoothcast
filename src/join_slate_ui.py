"""Opt-in "show join code on the TV when idle" controller (#420).

Casts ``/join-slate.png`` to the selected Google Cast receiver only when
:mod:`join_slate_policy` proves the TV is free. It rides the existing status poll
(no timer of its own), never marks itself as user playback, and stops the slate
only while the receiver still reports our exact image.
"""
from __future__ import annotations

import time

import castctl
import error_log
import join_slate_policy
from cast_widgets import Async


def add_switch(window, group) -> None:
    """Preferences row; kept here so preferences_ui.py stays small."""
    window._switch(group, "idle_join_slate", "Show join code on the TV when idle",
                   "Cast a QR code and address to the selected Google Cast TV when nothing "
                   "is playing and no other app is running.")


class JoinSlateMixin:
    _slate_cast: tuple[str, str] | None = None  # (device, url) we last sent
    _slate_idle_since: float | None = None
    _slate_armed: str | None = None  # receiver after whose own playback we may show it
    _slate_inflight = False
    _slate_backoff_until = 0.0

    def _join_slate_url(self) -> str | None:
        portal = getattr(self, "_portal", None)
        return join_slate_policy.slate_url(getattr(portal, "url", None))

    def _join_slate_showing(self, info) -> bool:
        """True while the receiver reports the slate we cast (not user playback)."""
        cast = self._slate_cast
        return (cast is not None and cast[0] == self._device()
                and join_slate_policy.is_showing(info, cast[1]))

    def _join_slate_observe(self, info) -> None:
        """Called after every receiver status poll; never raises."""
        try:
            self._join_slate_step(info)
        except Exception:  # an optional extra must never disturb playback
            error_log.log("Join slate check failed", exc_info=True)

    def _join_slate_step(self, info) -> None:
        enabled = bool(self.cfg.get("idle_join_slate", False))
        url = self._join_slate_url()
        device = self._device()
        now = time.monotonic()
        mine_idle = (self.session is None and not self.external and not self.queue)
        free = join_slate_policy.receiver_is_free(info) or self._join_slate_showing(info)
        if not enabled and self._slate_cast is not None and not self._slate_inflight:
            # Switched off: take our slate down, but only if it is still ours.
            self._slate_inflight = True
            self._slate_backoff_until = 0.0

            def cleared(_result):
                self._slate_inflight = False

            Async.run(self._join_slate_clear_now, done=cleared,
                      failed=lambda _m: cleared(None), domain="transport")
        if not enabled or self._slate_armed not in (None, device):
            self._slate_armed = None
        if self.session is not None or self.external:
            self._slate_armed = device  # only after our own playback: the TV is already on
        if not (enabled and mine_idle and free and self._slate_armed == device):
            self._slate_idle_since = None
            return
        if self._slate_idle_since is None:
            self._slate_idle_since = now
        if not join_slate_policy.should_show(
            enabled=enabled, is_cast_target=self._dlna_renderer(device) is None,
            session_active=self.session is not None, external=self.external,
            queue_len=len(self.queue), busy=bool(self.busy) or self._slate_inflight,
            info=info, url=url, idle_seconds=now - self._slate_idle_since,
            backoff_remaining=self._slate_backoff_until - now,
        ):
            return
        assert url is not None
        self._slate_inflight = True

        def work():
            return castctl.command(device, "cast", "--no-subs", url, timeout=30)

        def done(result):
            self._slate_inflight = False
            ok, message = result
            if ok:
                self._slate_cast = (device, url)
                self._slate_armed = None  # shown once per playback; never re-cast on its own
                self._console(f"Join code shown on {device}")
            else:
                self._slate_backoff_until = time.monotonic() + join_slate_policy.BACKOFF_SECONDS
                self._console(f"Join code not shown on {device}: {message or 'receiver refused'}")

        def failed(message):
            self._slate_inflight = False
            self._slate_backoff_until = time.monotonic() + join_slate_policy.BACKOFF_SECONDS
            self._console(f"Join code not shown on {device}: {message}")

        Async.run(work, done=done, failed=failed, domain="transport")

    def _join_slate_clear_now(self) -> bool:
        """Stop the slate if (and only if) the receiver still shows it. Blocking."""
        cast, self._slate_cast = self._slate_cast, None
        self._slate_idle_since = None
        if cast is None:
            return False
        device, url = cast
        try:
            if not join_slate_policy.should_clear(castctl.info(device), url):
                return False
            return bool(castctl.stop(device)[0])
        except (OSError, ValueError, TypeError):
            return False

