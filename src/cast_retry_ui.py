"""One-click recovery after a failed cast (#13): retry, convert, or another receiver.

The failure toast shows ONE button that follows the recovery planner's first
option. Every action re-enters the normal ``_cast_path`` (so all preflight,
ownership and replace rules still apply); this module never stops, kills or
adopts anything, and does nothing if another cast started in the meantime.
"""
from __future__ import annotations

import pathlib

from cast_widgets import fmt_time

LABELS = {"retry": "Try again", "alternate_encoding": "Convert and retry"}


class RetryMixin:
    def _retry_receiver_identity(self):
        """Read a unique receiver identity from cached discovery, never the network."""
        name = self._device()
        if not name:
            return None
        if name.startswith("DLNA · ") or name in self.cfg.get("cast_targets", []):
            host = self._device_host(name)
            return (name, "", host) if host else None
        matches = [row for row in self.devices if row.name == name]
        if len(matches) != 1:
            return None
        row = matches[0]
        saved = self.cfg.get("device_uuid") or ""
        uuid = getattr(row, "uuid", "") or ""
        host = getattr(row, "host", "") or ""
        if (saved and uuid != saved) or not (uuid or host):
            return None
        return name, uuid, host

    def _retry_action(self):
        """(label, callback) for the plan's first option, or None."""
        plan, path = getattr(self, "_recovery_plan", None), getattr(self, "_last_cast_path", None)
        option = plan.primary if plan is not None else None
        if option is None or path is None:
            return None
        self._cast_failure_id = getattr(self, "_cast_failure_id", 0) + 1
        token = self._cast_failure_id
        label = (f"Continue on {option.device}" if option.kind == "alternate_target"
                 else LABELS.get(option.kind, "Try again"))
        selection = self._device()
        identity = self._retry_receiver_identity()
        return label, lambda: self._retry_cast(
            token, path, plan.position, option.kind, option.device, selection, identity)

    def _select_receiver(self, name: str) -> bool:
        """Switch receivers through the normal dropdown handler (it refuses mid-cast)."""
        model = self.device_dropdown.get_model()
        for index in range(model.get_n_items() if model is not None else 0):
            if model.get_string(index) == name:
                self.device_dropdown.set_selected(index)
                return self.cfg.get("device") == name
        return False

    def _retry_cast(self, token: int, path, position: float,
                    kind: str, device: str, selection: str, identity) -> None:
        """Re-run the normal cast entry at the saved place, only if nothing else began."""
        if (getattr(self, "_closing", False) or token != getattr(self, "_cast_failure_id", 0)
                or self.busy or getattr(self, "external", False)
                or (self.session is not None and self.session.active())):
            self.toast("Playback changed; not retrying automatically")
            return
        if (self._device() != selection
                or (identity is not None and self._retry_receiver_identity() != identity)
                or (identity is None and kind != "alternate_target")):
            self.toast("Receiver changed or could not be identified; choose a receiver and cast again")
            return
        if kind == "alternate_target" and not self._select_receiver(device):
            self.toast(f"{device} is not available right now", error=True)
            return
        self._force_transcode_once = kind == "alternate_encoding"
        self._retry_in_flight = True
        self._console(f"Retrying cast at {fmt_time(position)} ({kind.replace('_', ' ')})")
        self._cast_path(pathlib.Path(path), position)
