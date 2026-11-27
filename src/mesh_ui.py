"""Desktop Network popover: the live mesh as one calm, accessible list (#403).

A ``Network`` button (hidden until the mesh runs) opens a popover with Devices,
Remotes/screens and Targets. Rows come from ``mesh_view_model`` and are updated
**in place** by key, so churn never rebuilds the list, steals focus or resets
scroll. Every state has text, not just a colour dot. All mesh data arrives via
``MeshService.view`` (an immutable snapshot), so nothing here blocks the mesh.
"""
from __future__ import annotations

from gi.repository import GLib, Gtk, Pango

import mesh_diagram
import update_button
import node_profile

import mesh_view_model as vm

_COLOURS = {"ready": "#2fa36b", "self": "#2fa36b", "alive": "#2fa36b", "busy": "#c99a00",
            "stale": "#9a8f6a", "unreachable": "#d6453a", "cached": "#7e8a99",
            "suspect": "#c99a00"}


def _dot(state: str) -> str:
    return f'<span foreground="{_COLOURS.get(state, "#7e8a99")}">●</span>'


class _Section:
    def __init__(self, title: str) -> None:
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading = Gtk.Label(label=title, xalign=0.0)
        heading.add_css_class("heading")
        heading.set_margin_top(8)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_tooltip_text(title)
        self.box.append(heading)
        self.box.append(self.list)
        self.rows: dict[str, tuple[Gtk.ListBoxRow, dict[str, Gtk.Label]]] = {}
        self.order: list[str] = []

    def _make(self, row: vm.Row) -> tuple[Gtk.ListBoxRow, dict[str, Gtk.Label]]:
        grid = Gtk.Grid(column_spacing=10, row_spacing=2, margin_top=6, margin_bottom=6,
                        margin_start=10, margin_end=10)
        dot = Gtk.Label(use_markup=True, valign=Gtk.Align.CENTER)
        title = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        state = Gtk.Label(xalign=1.0)
        state.add_css_class("dim-label")
        sub = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        why = Gtk.Label(xalign=0.0, wrap=True)
        why.add_css_class("caption")
        grid.attach(dot, 0, 0, 1, 2)
        grid.attach(title, 1, 0, 1, 1)
        grid.attach(state, 2, 0, 1, 1)
        grid.attach(sub, 1, 1, 2, 1)
        grid.attach(why, 1, 2, 2, 1)
        item = Gtk.ListBoxRow(activatable=False, selectable=False, child=grid)
        return item, {"dot": dot, "title": title, "state": state, "sub": sub, "why": why}

    def update(self, rows: tuple[vm.Row, ...]) -> None:
        # A new Gtk.ListBoxRow has no parent or valid sequence iterator.
        # Never ask GTK to remove or index an unattached row.
        by_key = {r.key: r for r in rows}
        for key in list(self.rows):
            if key not in by_key:
                item, _ = self.rows.pop(key)
                if item.get_parent() is self.list:
                    self.list.remove(item)
        for position, (key, row) in enumerate(by_key.items()):
            if key not in self.rows:
                self.rows[key] = self._make(row)
            item, labels = self.rows[key]
            parent = item.get_parent()
            if parent is not None and parent is not self.list:
                # Do not steal a widget from a different container.
                item, labels = self.rows[key] = self._make(row)
                parent = None
            self._fill(item, labels, row)
            if parent is None:
                self.list.insert(item, position)
            elif item.get_index() != position:
                self.list.remove(item)
                self.list.insert(item, position)
        self.order = list(by_key)

    @staticmethod
    def _fill(item: Gtk.ListBoxRow, labels: dict[str, Gtk.Label], row: vm.Row) -> None:
        title = row.title + (" · " + " · ".join(row.badges) if row.badges else "")
        for name, text in (("title", title), ("state", row.state_text),
                           ("sub", " — ".join(p for p in (row.subtitle, row.seen_by) if p)),
                           ("why", row.detail)):
            if labels[name].get_text() != text:
                labels[name].set_text(text)
        labels["why"].set_visible(bool(row.detail))
        dot = _dot(row.state)
        if labels["dot"].get_label() != dot:
            labels["dot"].set_markup(dot)
        try:
            item.update_property([Gtk.AccessibleProperty.LABEL],
                                 [f"{row.title}, {row.state_text}" + (f", {row.detail}" if row.detail else "")])
        except Exception:  # noqa: BLE001 - accessibility labels are best-effort
            pass


class NetworkPopover:
    def __init__(self, window: object | None = None) -> None:
        self._window = window
        self._syncing = False
        self.button = Gtk.MenuButton(label="Network", visible=False)
        self.button.set_tooltip_text("Devices, screens and receivers on your network")
        popover = Gtk.Popover()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=10,
                        margin_bottom=10, margin_start=10, margin_end=10)
        self.summary = Gtk.Label(xalign=0.0)
        self.summary.add_css_class("heading")
        self.hint = Gtk.Label(xalign=0.0, wrap=True)
        self.hint.add_css_class("dim-label")
        self.sections = {"nodes": _Section("Devices"), "clients": _Section("Remotes and screens"),
                         "targets": _Section("Targets")}
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      propagate_natural_height=True, max_content_height=420,
                                      min_content_width=360)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for section in self.sections.values():
            inner.append(section.box)
        self.diagram = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, height_request=240)
        self.diagram.update_property([Gtk.AccessibleProperty.LABEL],
                                     ["Diagram of every device, receiver and client on the network"])
        self.details = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        self.details.add_css_class("caption")
        expander = self._profile_expander = Gtk.Expander(label="Network diagram and device detail")
        self._pending_profiles = ()
        self._rendered_profiles = None
        expander.connect("notify::expanded", self._render_profiles)
        expander.connect("map", self._render_profiles)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        holder.append(self.diagram)
        holder.append(self.details)
        expander.set_child(holder)
        inner.append(expander)
        scroller.set_child(inner)
        self.switches: dict[str, Gtk.Switch] = {}
        for widget in (self.summary, self.hint, scroller,
                       self._link_download_options()):
            outer.append(widget)
        popover.set_child(outer)
        self.button.set_popover(popover)
        popover.connect("show", lambda *_: self.sync_switches())
        self.model: vm.NetworkModel | None = None

    def _link_download_options(self) -> Gtk.Widget:
        """Opt-in switches for sharing link downloads on a trusted home network (#589)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8)
        title = Gtk.Label(label="Link downloads", xalign=0.0)
        title.add_css_class("heading")
        box.append(title)
        for name, text, detail in (
            ("remote_acquisition", "Use other devices to download links",
             "Hands YouTube and torrent links to a trusted device here when this computer cannot."),
            ("accept_acquisition", "Download links for other devices",
             "Lets another SmoothCast room on your network use this computer for downloads."),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            main = Gtk.Label(label=text, xalign=0.0, wrap=True)
            note = Gtk.Label(label=detail, xalign=0.0, wrap=True)
            note.add_css_class("dim-label")
            note.add_css_class("caption")
            labels.append(main)
            labels.append(note)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.update_property([Gtk.AccessibleProperty.LABEL], [text])
            switch.connect("notify::active", self._toggled, name)
            self.switches[name] = switch
            row.append(labels)
            row.append(switch)
            box.append(row)
        self.sync_switches()
        return box

    def sync_switches(self) -> None:
        """Reflect the saved opt-ins (read from disk, the single source of truth)."""
        try:
            import mesh_service
            saved = mesh_service.load_settings()
        except Exception:  # noqa: BLE001 - settings read failure leaves the panel unsynced
            return
        self._syncing = True
        try:
            for name, switch in self.switches.items():
                if switch.get_active() != bool(saved.get(name)):
                    switch.set_active(bool(saved.get(name)))
        finally:
            self._syncing = False

    def _toggled(self, switch: Gtk.Switch, _param: object, name: str) -> None:
        if self._syncing or self._window is None:
            return
        import cast_mesh
        if not cast_mesh.set_acquisition(self._window, name, bool(switch.get_active())):
            self.sync_switches()  # not applied: show the truth, not the click

    def show_profiles(self, profiles) -> None:
        """Store the latest immutable profiles, even when details are hidden."""
        self._pending_profiles = tuple(profiles)
        self._render_profiles()

    def _render_profiles(self, *_args) -> None:
        # No SVG encoding/decoding while the popover is hidden or collapsed.
        if not self._profile_expander.get_mapped() or not self._profile_expander.get_expanded():
            return
        profiles = self._pending_profiles
        if profiles == self._rendered_profiles:
            return
        self._paint_profiles(profiles)
        self._rendered_profiles = profiles

    def _paint_profiles(self, profiles) -> None:
        """Decode a changed snapshot only; textual detail remains on failure."""
        try:
            from gi.repository import Gdk
            svg = mesh_diagram.render(profiles).encode("utf-8")
            self.diagram.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg)))
        except Exception:  # noqa: BLE001 - diagram render failure clears the picture
            self.diagram.set_paintable(None)
        self.details.set_text("\n\n".join(self.describe(p) for p in profiles))

    @staticmethod
    def describe(p: node_profile.NodeProfile) -> str:
        lines = [f"{p.name} — {p.role} · {p.headline}"]
        for label, values in (("Address", p.addresses), ("Can", p.capabilities), ("Receivers", p.targets),
                              ("Clients", p.clients), ("Shares", p.sources)):
            if values:
                lines.append(f"  {label}: {', '.join(values)}")
        if p.ports:
            lines.append(f"  Ports: {p.ports}")
        lines += [f"  Link to {link.peer[:8]}: {link.text}" for link in p.links]
        return "\n".join(lines)

    def show(self, model: vm.NetworkModel | None) -> None:
        """Apply a model, or hide the button when there is no running mesh."""
        self.button.set_visible(model is not None)
        if model is None:
            self.model = None
            self._pending_profiles = ()
            self._rendered_profiles = None
            return
        if self.model is not None and vm.diff_rows(self.model.all_rows(), model.all_rows()).empty \
                and self.model.summary == model.summary and self.model.empty_hint == model.empty_hint:
            return
        self.sections["nodes"].update(model.nodes)
        self.sections["clients"].box.set_visible(bool(model.clients))
        self.sections["clients"].update(model.clients)
        self.sections["targets"].box.set_visible(bool(model.targets))
        self.sections["targets"].update(model.targets)
        self.summary.set_text(model.summary)
        self.hint.set_text(model.empty_hint)
        self.hint.set_visible(bool(model.empty_hint))
        self.model = model


def build_button(window: object) -> Gtk.MenuButton:
    """Create the Network button once; refreshed by :func:`refresh`."""
    popover = NetworkPopover(window)
    window._mesh_ui = popover                       # type: ignore[attr-defined]
    updater = update_button.UpdateButton(window)
    window._update_button = updater                 # type: ignore[attr-defined]
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(updater.button)
    box.append(popover.button)
    return box


def refresh(window: object) -> None:
    """Rebuild the model from the running mesh (called ~1 Hz on the GTK thread)."""
    updater = getattr(window, "_update_button", None)
    if updater is not None:
        updater.refresh()
    popover = getattr(window, "_mesh_ui", None)
    if popover is None:
        return
    service = getattr(window, "_mesh", None)
    view = service.view if service is not None else None
    if view is None:
        popover.show(None)
        return
    try:
        diag = service.diagnostics()
        warm = service.warm_start()
        cached = [(p.node_id, p.name, max(0, int(GLib.get_real_time() / 1_000_000) - p.last_seen))
                  for p in (warm.peers if warm else ())]
        popover.show_profiles(node_profile.profile(r, local_id=view.local_id, primary_id=service.roles.primary,
                                             now=GLib.get_real_time() / 1_000_000)
                              for r in view.nodes)
        popover.show(vm.build_model(view, primary_id=service.roles.primary, cached_peers=cached,
                                    multicast_hint=diag.get("multicast_hint", "")))
    except Exception:  # noqa: BLE001 - popover failure must not break the UI
        return
