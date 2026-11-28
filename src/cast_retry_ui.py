"""One-click recovery after a failed cast (#13): retry, convert, or another receiver.

The failure toast shows ONE button that follows the recovery planner's first
option. Every action re-enters the normal ``_cast_path`` (so all preflight,
ownership and replace rules still apply); this module never stops, kills or
adopts anything, and does nothing if another cast started in the meantime.
"""
from __future__ import annotations

import pathlib

import retry_component
from cast_widgets import fmt_time



class RetryMixin:
    def _retry_receiver_identity(self):
        """Read a unique receiver identity from cached discovery, never the network."""
        name = self._device()
        is_saved = bool(name) and (name.startswith("DLNA · ") or name in self.cfg.get("cast_targets", []))
        return retry_component.receiver_identity(
            name, cast_targets=self.cfg.get("cast_targets", []),
            host_for_saved=self._device_host(name) if is_saved else None,
            devices=self.devices, saved_uuid=self.cfg.get("device_uuid") or "")

    def _retry_action(self):
        """(label, callback) for the plan's first option, or None."""
        plan, path = getattr(self, "_recovery_plan", None), getattr(self, "_last_cast_path", None)
        option = plan.primary if plan is not None else None
        if option is None or path is None:
            return None
        self._cast_failure_id = getattr(self, "_cast_failure_id", 0) + 1
        token = self._cast_failure_id
        label = retry_component.action_label(option.kind, option.device)
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
        if retry_component.playback_changed(
                closing=getattr(self, "_closing", False), token=token,
                current_token=getattr(self, "_cast_failure_id", 0), busy=self.busy,
                external=getattr(self, "external", False),
                session_active=self.session is not None and self.session.active()):
            self.toast("Playback changed; not retrying automatically")
            return
        if retry_component.receiver_changed(
                selection=selection, current_selection=self._device(), identity=identity,
                current_identity=self._retry_receiver_identity() if identity is not None else None,
                kind=kind):
            self.toast("Receiver changed or could not be identified; choose a receiver and cast again")
            return
        if kind == "alternate_target" and not self._select_receiver(device):
            self.toast(f"{device} is not available right now", error=True)
            return
        self._force_transcode_once = kind == "alternate_encoding"
        self._retry_in_flight = True
        self._console(f"Retrying cast at {fmt_time(position)} ({kind.replace('_', ' ')})")
        self._cast_path(pathlib.Path(path), position)
