"""Adwaita glue for the failure banner (#207). Logic lives in ``error_banner``."""
from __future__ import annotations

import error_banner


def present(window, failure, *, retry=None, timeout: int = 10) -> None:
    """Show a high-priority toast whose button opens the details dialog.

    ``retry`` is an optional ``(label, callback)`` that re-enters the normal action."""
    from gi.repository import Adw
    toast = Adw.Toast.new(failure.message)
    toast.set_timeout(timeout)
    toast.set_priority(Adw.ToastPriority.HIGH)
    toast.set_button_label("Details")
    toast.connect("button-clicked", lambda *_: show_details(window, failure, retry=retry))
    window.toasts.add_toast(toast)


def show_details(window, failure, *, retry=None) -> None:
    from gi.repository import Adw
    banner = error_banner.build(failure, can_retry=retry is not None)
    dialog = Adw.AlertDialog.new(banner.message, error_banner.details_text(banner))
    dialog.add_response("close", "Close")
    dialog.add_response("copy", error_banner.LABELS["copy"])
    if any(action == "retry" for action, _label in banner.actions):
        dialog.add_response("retry", retry[0] if retry else error_banner.LABELS["retry"])
        dialog.set_response_appearance("retry", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("close")

    def answered(_dialog, response):
        if response == "copy":
            window.get_clipboard().set(error_banner.diagnostics_text(failure))
            window.toast("Diagnostics copied")
        elif response == "retry" and retry is not None:
            retry[1]()

    dialog.connect("response", answered)
    dialog.present(window)
