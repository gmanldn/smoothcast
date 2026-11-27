"""Application lifecycle helpers for CastControlApp.

Activation readiness, GLib guard wrappers, the MPRIS sampler and the runtime
notices were extracted from ``cast_control.py`` unchanged so that module stays
within its INV-011 read budget; the methods run on the same ``CastControlApp``
instance.
"""
from __future__ import annotations

import os

import error_banner_ui
import version


class AppLifecycleMixin:
    def _failure_notice_available(self) -> bool:
        window = self.window
        return bool(window is not None and not window._closing and not self.fatal
                    and hasattr(window, "toasts"))
    def _present_unexpected_failure(self, failure) -> None:
        window = self.window
        if not self._failure_notice_available() or window is None:
            return
        error_banner_ui.present(window, failure, timeout=8)
    def _guard_glib(self, callback):
        bridge = self._failure_bridge
        return bridge.guard_glib(callback) if bridge is not None else callback
    def _mpris_tick(self) -> bool:
        """Push a fresh MPRIS2 snapshot; cheap when nothing changed (#266)."""
        if self._mpris is not None:
            self._mpris.refresh()
        return True
    def _publish_activation_ready(self) -> None:
        """Tell a waiting launcher which commit is live."""
        path = os.environ.get("SMOOTHCAST_ACTIVATION_READY")
        commit = version.RUNNING_REVISION
        if not path or not commit:
            return
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as out:
                out.write(commit)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    def _restart_mpris(self) -> None:
        """Re-publish MPRIS2 after a bounce; best-effort like the first start."""
        window = self.window
        current, self._mpris = self._mpris, None
        if current is not None:
            try:
                current.close()
            except Exception:
                pass
        if window is not None:
            import mpris
            self._mpris = mpris.start(window)
    def _present_update_notice(self, notice: str) -> bool:
        window = self.window
        if window is not None and not window._closing:
            # A remote candidate cannot replace the higher-priority warning
            # that this process is already using an older installed generation.
            if not getattr(window, "_installed_version_stale", False):
                window.update_notice = notice
                window._update_header_subtitle()
            window._console(notice)
            window.toast(notice)
        return False
